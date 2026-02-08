Database outline (v1)

Entities
- users (optional in v1)
- searches
- tracks
- price_checks
- price_history
- notifications

Tables (draft)
users
- id, email, created_at

searches
- id, origin, destination, depart_date, return_date, created_at

tracks
- id, search_id, user_id?, target_price?, status, created_at, last_checked_at

price_checks
- id, track_id, checked_at, provider, status, error?

price_history
- id, track_id, checked_at, price, currency, raw_provider_id?

notifications
- id, track_id, email, sent_at, reason, price

Relationships
- user has many tracks
- search has many tracks
- track has many price_history
- track has many notifications

Indexes
- tracks.search_id
- price_history.track_id + checked_at
