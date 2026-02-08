Scheduler + notifications (v1)

Jobs
- Price check runner (every 6h or 12h)
- Drop evaluation after each check
- Dedupe for notifications

Drop logic (draft)
- Below previous minimum
- % drop threshold
- Optional user target price

Email
- Trigger on drop
- Include route summary + price
- Rate limit per track (avoid spam)

Dedupe rules
- Do not send same reason twice in 24h
- If price goes back up, reset trigger
