# BongaAI — SMS-only AI (SA-first) MVP

This repo is a tiny FastAPI service that powers **BongaAI** over **SMS**. It:
- Receives an inbound SMS (webhook)
- Sends the text to AI (mock by default, or OpenAI if you set a key)
- Replies by SMS (mock to `outbox.log` by default; or your gateway when you switch off mock)

---

## 1) Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# mac/linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
- `USE_MOCK_SEND=true` keeps SMS sending **offline** and writes messages to `outbox.log`.
- `FAKE_AI_MODE=true` makes AI replies **mock** without calling OpenAI.

Later, set:
- `OPENAI_API_KEY=sk-...` and `FAKE_AI_MODE=false` to use real AI.
- Replace `SMS_API_BASE`, `SMS_API_KEY`, `SENDER_ID` with your provider (e.g., SMSPortal).

## 2) Run locally

```bash
uvicorn app:app --reload --port 8000
```

Test health:
- http://127.0.0.1:8000/health

## 3) Simulate inbound SMS (no provider required)

### Form-encoded (common)
```bash
curl -X POST http://127.0.0.1:8000/sms/inbound \  -H "Content-Type: application/x-www-form-urlencoded" \  -d "from=27831234567" -d "to=27820000000" -d "text=help"
```

### JSON
```bash
curl -X POST http://127.0.0.1:8000/sms/inbound \  -H "Content-Type: application/json" \  -d '{"from":"27831234567","to":"27820000000","text":"write a short poem about rain"}'
```

You should see **mock sends** appended to `outbox.log`.

## 4) What the app does (simple words)

- **/sms/inbound**: gets the SMS. If user says:
  - `HELP` → sends help text (pricing + support)
  - `STOP` → unsubscribes them; no more replies
  - anything else → sends a one-time **WELCOME**, asks AI for an answer, and sends the answer
- **ai_reply()**: returns a pretend answer (mock), or a real one if OpenAI is enabled
- **send_sms()**: writes to `outbox.log` (mock) or calls your SMS provider to send
- **split_for_sms()**: breaks long text into 160-char chunks (SMS-sized)
- **store.json**: remembers who got WELCOME and who opted out

## 5) Switch to real SMS later

1. Get a **two-way long number** from your provider (e.g., SMSPortal).
2. In their console, set inbound webhook to your URL: `https://YOURHOST/sms/inbound`.
3. Update `.env`:
   - `USE_MOCK_SEND=false`
   - `SMS_API_BASE=https://<provider-rest-base>`
   - `SMS_API_KEY=<your-api-key>`
   - `SENDER_ID=<your-long-code>`
4. Restart the app.
5. SMS your long code from your phone → you should get WELCOME + an answer.

## 6) Common tweaks

- Keep answers short. If you see long replies, trim in code or reduce `max_tokens`.
- If weird characters appear, keep AI answers **plain text** (no emoji).

## 7) Deploy

Render / Railway / Fly.io – run a single web process:

```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Set the same `.env` values in the host dashboard. Paste the host URL into your SMS provider's webhook.

---

Made for SA SMS rails. Brand: **BongaAI**.
