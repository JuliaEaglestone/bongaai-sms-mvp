#!/usr/bin/env bash
curl -X POST http://127.0.0.1:8000/sms/inbound \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "from=27831234567" \
  -d "to=27820000000" \
  -d "text=help"
