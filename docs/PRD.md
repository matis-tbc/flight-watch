PRD v1: FlightWatch

Problem
- Flight prices change fast and unpredictably
- Users must re-check repeatedly
- Manual tracking is stressful and time-heavy

Goal
- Track routes
- Detect meaningful drops
- Notify users

Success criteria
- Track at least one route end-to-end
- Store price history
- Notification on drop
- Reliable for multiple users

Scope (v1)
- Route search
- Tracking one or more routes
- Scheduled price checks
- Price history storage
- Email notification on drop
- Optional account creation (defer if needed)

Out of scope (v1)
- Payments
- Mobile app
- Full user profiles

User flow (v1)
- Search route
- View price trend
- Choose to track
- Receive email on drop

Requirements
Route search + tracking
- Inputs: origin, destination, depart date, return optional
- Store tracking request (if user opts in)

Price fetching
- Scheduled checks (6h or 12h)
- Save prices with timestamps

Drop detection
- Compare current price to:
  - previous lowest
  - user target (optional)
  - % drop or window min

Notifications
- Email when:
  - below previous minimum
  - drops by X%

User account (optional)
- Email-based account
- Save searches
- Email notifications

Open items
- Exact drop logic
- Scheduler cadence
- Auth scope for v1
