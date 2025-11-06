#!/usr/bin/env bash
curl -X POST http://127.0.0.1:8000/sms/inbound \
  -H "Content-Type: application/json" \
  -d '{"from":"27831234567","to":"27820000000","text":"write a 3-line poem about rain"}'
