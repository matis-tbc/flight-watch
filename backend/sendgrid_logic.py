#!/usr/bin/env python3
"""
sendgrid_logic.py  — Email delivery via SendGrid
Called by: scheduler.py /check-prices when a price drop is detected

Flow:
  Cloud Scheduler → POST /check-prices (scheduler.py)
    → get_tracked_flights()        [firestore_logic.py]  pulls user email + route
    → gcs_data_service_simple      [gcs_data_service_simple.py] fetches latest price
    → send_price_drop_email()      [this file] sends alert if price dropped
    → update_price()               [firestore_logic.py]  saves new price to Firestore
"""
import logging
import os

logger = logging.getLogger(__name__)
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://yourapp.com")


def send_price_drop_email(
    to_email: str,
    flight_info: str,
    old_price: float,
    new_price: float,
) -> bool:
    """
    Send a price-drop alert email via SendGrid.

    Args:
        to_email:    comes from Firestore tracked_flights doc["user_email"]
        flight_info: built in scheduler.py  e.g. "JFK -> CDG on 2026-04-01"
        old_price:   comes from Firestore tracked_flights doc["latest_price"]
        new_price:   comes from gcs_data_service_simple.search_flights()[0] price

    Returns True if SendGrid accepted (HTTP 202), False otherwise.
    Raises on unexpected errors so scheduler.py can catch and increment email_errors.
    """
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
    FROM_EMAIL = os.getenv("FROM_EMAIL", "")

    if not SENDGRID_API_KEY:
        raise EnvironmentError("SENDGRID_API_KEY is not set. Add it to backend/.env")
    if not FROM_EMAIL:
        raise EnvironmentError("FROM_EMAIL is not set. Add it to backend/.env")

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError as exc:
        raise ImportError("sendgrid not installed. Run: pip install sendgrid") from exc

    savings = old_price - new_price
    savings_pct = (savings / old_price * 100) if old_price else 0

    html_content = f"""
    <div style="font-family: -apple-system, Arial, sans-serif;
                max-width: 560px; margin: auto; padding: 24px; color: #111;">
      <h2 style="color: #1d4ed8; margin-bottom: 4px;">✈ Flight Price Dropped!</h2>
      <p style="color: #6b7280; margin-top: 0;">{flight_info}</p>
      <div style="background: #eff6ff; border: 1px solid #bfdbfe;
                  border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
        <div style="font-size: 2.4rem; font-weight: 800; color: #1e40af;">
          ${new_price:.2f}
        </div>
        <div style="color: #16a34a; font-size: 0.95rem; margin-top: 6px;">
          🎉 Save ${savings:.2f} ({savings_pct:.1f}% off)
          vs previous <span style="text-decoration: line-through; color: #9ca3af;">${old_price:.2f}</span>
        </div>
      </div>
      <a href="https://www.google.com/flights"
         style="display: inline-block; background: #1d4ed8; color: #fff;
                text-decoration: none; padding: 12px 32px;
                border-radius: 8px; font-weight: 600; font-size: 1rem;">
        Book Now →
      </a>
      <hr style="margin: 28px 0; border: none; border-top: 1px solid #e5e7eb;">
      <p style="font-size: 0.72rem; color: #9ca3af;">
        You're receiving this because you're tracking this route on FlightWatch.<br>
        <a href="{APP_BASE_URL}/unsubscribe" style="color: #9ca3af;">Unsubscribe</a>
      </p>
    </div>
    """

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=f"✈ Price Drop Alert: {flight_info} — now ${new_price:.2f}",
        html_content=html_content,
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        success = response.status_code in (200, 202)
    except Exception as e:
        logger.error(
            "SendGrid error — status: %s | body: %s",
            e.status_code if hasattr(e, "status_code") else "N/A",
            e.body if hasattr(e, "body") else str(e),
        )
        raise

    if success:
        logger.info("Email sent to %s for %s", to_email, flight_info)
    else:
        logger.error("SendGrid returned status %d for %s", response.status_code, to_email)

    return success


if __name__ == "__main__":
    """
    Manual test runner — pulls a real tracked flight from Firestore,
    simulates a price drop, and sends the alert email.

    This mirrors exactly what scheduler.py /check-prices does at runtime:
      1. get_tracked_flights()             → Firestore: user email + route
      2. gcs_data_service_simple           → GCS: latest price
      3. send_price_drop_email()           → SendGrid: alert email
      4. update_price()                    → Firestore: save new price

    To run:
      1. Make sure backend/.env has all credentials set
      2. python sendgrid_logic.py
    """
    import sys
    from dotenv import load_dotenv
    from firestore_logic import get_tracked_flights
    from gcs_data_service_simple import gcs_data_service_simple

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    logging.basicConfig(level=logging.INFO)

    print("API key loaded :", bool(os.getenv("SENDGRID_API_KEY")))
    print("FROM_EMAIL     :", os.getenv("FROM_EMAIL"))

    # Step 1 — pull real tracked flights from Firestore (same as scheduler.py)
    tracked_docs = list(get_tracked_flights())
    if not tracked_docs:
        print("No tracked flights in Firestore. Add a flight to track first.")
        sys.exit(1)

    doc  = tracked_docs[0]
    data = doc.to_dict()

    user_email     = data.get("user_email")
    origin         = str(data.get("origin", "")).strip().upper()
    destination    = str(data.get("destination", "")).strip().upper()
    departure_date = str(data.get("departure_date", "")).split("T")[0]
    old_price      = float(data.get("latest_price") or 0)

    if not user_email:
        print(f"Doc {doc.id} has no user_email — skipping.")
        sys.exit(1)

    # Step 2 — fetch latest price from GCS (same as scheduler.py)
    flights = gcs_data_service_simple.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        limit=1,
    )

    if flights:
        raw = flights[0].get("price")
        if isinstance(raw, dict):
            raw = raw.get("total")
        new_price = float(str(raw).replace(",", "").strip()) if raw else old_price * 0.85
    else:
        # No GCS result — simulate a 15% drop so email can still be tested
        new_price = round(old_price * 0.85, 2)
        print(f"No GCS flights found for {origin} -> {destination}, simulating 15% drop.")

    flight_info = f"{origin} -> {destination} on {departure_date}"

    print(f"\nTracked flight : {flight_info}")
    print(f"User email     : {user_email}")
    print(f"Price drop     : ${old_price:.2f} → ${new_price:.2f}")

    # Step 3 — send the email
    result = send_price_drop_email(
        to_email=user_email,
        flight_info=flight_info,
        old_price=old_price,
        new_price=new_price,
    )
    print("Email sent:", result)
    sys.exit(0 if result else 1)