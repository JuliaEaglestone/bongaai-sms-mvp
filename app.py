from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os, httpx, json, hashlib, time
from dotenv import load_dotenv

# ---------- env & config ----------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional for mock
SMS_API_BASE   = os.getenv("SMS_API_BASE", "https://sms-gateway.example.com")
SMS_API_KEY    = os.getenv("SMS_API_KEY", "dev-mock-key")
SENDER_ID      = os.getenv("SENDER_ID", "27820000000")
SUPPORT_PHONE  = os.getenv("SUPPORT_PHONE", "0X-XXX-XXXX")
SUPPORT_EMAIL  = os.getenv("SUPPORT_EMAIL", "bongaai.support@gmail.com")
PRICING_COPY   = os.getenv("PRICING_COPY", "R1/SMS received (std rates apply)")
USE_MOCK_SEND  = os.getenv("USE_MOCK_SEND", "true").lower() == "true"
FAKE_AI_MODE   = os.getenv("FAKE_AI_MODE", "true").lower() == "true" or not OPENAI_API_KEY

STORE_FILE     = os.getenv("STORE_FILE", "store.json")

app = FastAPI(title="BongaAI SMS MVP")

# ---------- tiny store (json) ----------
def _load_store():
    if not os.path.exists(STORE_FILE):
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"users":{}, "logs":[]}, f)
    with open(STORE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_store(store):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)

def _hash_msisdn(msisdn: str) -> str:
    return hashlib.sha256(msisdn.encode("utf-8")).hexdigest()

# ---------- helpers ----------
def split_for_sms(text: str):
    # GSM-7-ish simple splitter (keeps it simple for MVP)
    limit_first = 160
    limit_next  = 153
    parts = []
    text = (text or "").strip()
    while text:
        parts.append(text[:limit_first])
        text = text[limit_first:]
        limit_first = limit_next
    return parts or [""]

async def ai_reply(user_text: str) -> str:
    """Mock by default. If you set OPENAI_API_KEY and FAKE_AI_MODE=false, it will call OpenAI."""
    if FAKE_AI_MODE:
        # keep it short to mimic SMS
        return f"(mock) You said: {user_text[:200]}"
    # Real OpenAI call (kept minimal; you can switch models later)
    import openai  # lazy import
    openai.api_key = OPENAI_API_KEY
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":"You are BongaAI, an SMS assistant in South Africa. Keep answers under 3 SMS parts, plain text."},
            {"role":"user","content": user_text}
        ],
        max_tokens=300,
        temperature=0.2
    )
    return resp["choices"][0]["message"]["content"].strip()

async def send_sms(to_msisdn: str, text: str):
    """Sends SMS via provider. In mock mode, write to outbox.log instead."""
    parts = split_for_sms(text)
    if USE_MOCK_SEND:
        with open("outbox.log","a",encoding="utf-8") as f:
            for p in parts:
                f.write(f"{int(time.time())}|MOCK_SEND|to={to_msisdn}|from={SENDER_ID}|{p}\n")
        return

    # Example generic POST. Adjust fields to match SMSPortal when you switch to live.
    headers = {"Authorization": f"Bearer {SMS_API_KEY}"}
    async with httpx.AsyncClient(timeout=15) as client:
        for p in parts:
            payload = {
                "to":   to_msisdn,     # may be "msisdn" or "destination" in some APIs
                "from": SENDER_ID,     # may be "sender" or omitted if configured server-side
                "text": p
            }
            r = await client.post(f"{SMS_API_BASE}/messages", json=payload, headers=headers)
            r.raise_for_status()

def welcome_text():
    return (f"BongaAI: AI over SMS. Cost {PRICING_COPY}. "
            f"Reply HELP for help, STOP to cancel. Support {SUPPORT_PHONE} • {SUPPORT_EMAIL}")

def help_text():
    return (f"BongaAI answers questions by SMS. Cost {PRICING_COPY}. "
            f"Reply STOP to cancel. Support {SUPPORT_PHONE} • {SUPPORT_EMAIL}")

def get_user(store, msisdn):
    h = _hash_msisdn(msisdn)
    users = store.get("users", {})
    if h not in users:
        users[h] = {"msisdn_hash": h, "welcome_sent": False, "opted_out": False, "lang": "en", "last_seen": int(time.time())}
        store["users"] = users
    return users[h], h

def log_event(store, direction, msisdn, text, extra=None):
    store["logs"].append({
        "ts": int(time.time()),
        "direction": direction,
        "msisdn_hash": _hash_msisdn(msisdn),
        "text": (text or "")[:800],
        "extra": extra or {}
    })

# ---- rate limits ----
DAY_SECS = 24*60*60
def can_proceed(store, msisdn, per_hour=20, per_day=200):
    h = _hash_msisdn(msisdn)
    rl = store.setdefault("ratelimit", {})
    u = rl.setdefault(h, {"hour": {"t": 0, "n": 0}, "day": {"t": 0, "n": 0}})
    now = int(time.time())
    hb, db = now // 3600, now // DAY_SECS
    if u["hour"]["t"] != hb:
        u["hour"] = {"t": hb, "n": 0}
    if u["day"]["t"]  != db:
        u["day"]  = {"t": db, "n": 0}
    if u["hour"]["n"] >= per_hour or u["day"]["n"] >= per_day:
        return False
    u["hour"]["n"] += 1
    u["day"]["n"]  += 1
    rl[h] = u
    store["ratelimit"] = rl
    return True

# ---------- routes ----------
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/sms/inbound")
async def inbound(request: Request):
    # Robust content-type handling:
    # 1) If header says JSON -> parse JSON.
    # 2) If header says form-encoded -> parse form (needs python-multipart installed).
    # 3) If header is missing/wrong -> try JSON first, then fall back to form.

    content_type = (request.headers.get("content-type") or "").lower()

    from_msisdn, text = None, ""
    data, form = None, None

    if "application/json" in content_type:
        data = await request.json()
        from_msisdn = data.get("from") or data.get("msisdn") or data.get("sender")
        text = (data.get("text") or data.get("message") or "").strip()

    elif "application/x-www-form-urlencoded" in content_type:
        # Note: requires python-multipart in requirements.txt to avoid runtime error
        form = await request.form()
        from_msisdn = form.get("from") or form.get("msisdn") or form.get("sender")
        text = (form.get("text") or form.get("message") or "").strip()

    else:
        # Header missing or odd → try JSON, then fall back to form
        try:
            data = await request.json()
            from_msisdn = data.get("from") or data.get("msisdn") or data.get("sender")
            text = (data.get("text") or data.get("message") or "").strip()
        except Exception:
            form = await request.form()
            from_msisdn = form.get("from") or form.get("msisdn") or form.get("sender")
            text = (form.get("text") or form.get("message") or "").strip()

        
    # ---------- Inbound idempotency (drop duplicate deliveries) ----------
    store = _load_store()  # load early so we can record seen ids
    mid = None
    if isinstance(data, dict):
        mid = (data.get("messageId") or data.get("id") or data.get("msgid"))
    if not mid and form is not None:
        mid = (form.get("messageId") or form.get("id") or form.get("msgid"))

    # Fallback when provider omits messageId: make a 60s-bucket fingerprint
    if not mid:
        bucket = int(time.time()) // 60  # 60-second window
        raw = f"{from_msisdn}|{(text or '')[:40]}|{bucket}"
        mid = "fk:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

    seen = store.setdefault("seen", {})
    now = int(time.time())

    # purge >24h to keep file small
    for k, t in list(seen.items()):
        if now - t > 24*3600:
            seen.pop(k, None)

    # if already handled, log and ACK fast (prevents double costs)
    if mid in seen:
        log_event(store, "DUP", from_msisdn, text, {"messageId": mid})
        _save_store(store)
        return {"ok": True}

    # remember this id so a retry won't reprocess
    if mid:
        seen[mid] = now
        store["seen"] = seen
        _save_store(store)
    # ---------------------------------------------------------------

    if not from_msisdn:
        return JSONResponse({"ok": False, "reason": "missing sender"}, status_code=400)

    user, user_key = get_user(store, from_msisdn)
    user["last_seen"] = int(time.time())

    low = (text or "").lower()

    # compliance keywords
    if low in ("stop","unsubscribe","cancel"):
        user["opted_out"] = True
        _save_store(store)
        await send_sms(from_msisdn, "You’re unsubscribed. No further messages. HELP for info.")
        log_event(store, "MT", from_msisdn, "STOP confirm")
        _save_store(store)
        return {"ok": True}

    if user.get("opted_out"):
        log_event(store, "BLOCK", from_msisdn, text, {"reason": "opted_out"})
        _save_store(store)
        return {"ok": True}

    if low in ("help","info"):
        await send_sms(from_msisdn, help_text())
        log_event(store, "MT", from_msisdn, "HELP")
        _save_store(store)
        return {"ok": True}

    # welcome once
    if not user.get("welcome_sent"):
        await send_sms(from_msisdn, welcome_text())
        user["welcome_sent"] = True

    # rate-limit guard (protect costs)
    if not can_proceed(store, from_msisdn, per_hour=20, per_day=200):
        await send_sms(from_msisdn, "BongaAI: You’ve hit today’s limit. Try again later.")
        log_event(store, "MT", from_msisdn, "rate-limit notice")
        _save_store(store)
        return {"ok": True}

    # AI reply
    answer = await ai_reply(text)
    if len(answer) > 480:
        answer = answer[:477] + "..."

    await send_sms(from_msisdn, answer)

    log_event(store, "MO", from_msisdn, text)
    log_event(store, "MT", from_msisdn, answer)
    _save_store(store)
    return {"ok": True}

@app.post("/sms/dlr")
async def dlr(_: Request):
    # delivery receipts could be stored here
    return {"ok": True}

@app.post("/billing/callback")
async def billing(_: Request):
    # handle DCB callbacks later
    return {"ok": True}
