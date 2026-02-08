API contract outline (v1)

Base
- Versioned: /api/v1
- JSON in/out
- Timezone: UTC

Search
- POST /search
- Input: origin, destination, depart_date, return_date?
- Output: list of flight options, price, currency, provider_id, segments

Tracking
- POST /tracks
- Input: search params + optional target_price + notify_email
- Output: track_id, status, next_check_at

- GET /tracks
- Output: list of tracked routes for user/session

- GET /tracks/{id}
- Output: track details + latest price + metadata

History
- GET /tracks/{id}/history
- Output: timestamped price list

Notifications
- POST /tracks/{id}/notify-test
- Output: success flag

Errors (standard)
- 400 invalid input
- 404 not found
- 429 rate limited
- 500 provider error / internal

Notes
- Auth optional in v1
- If auth off, use tracking token per browser
