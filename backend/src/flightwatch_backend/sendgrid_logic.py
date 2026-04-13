#!/usr/bin/env python3
"""Email delivery via SendGrid."""
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
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("FROM_EMAIL", "")

    if not sendgrid_api_key:
        raise EnvironmentError("SENDGRID_API_KEY is not set. Add it to backend/.env")
    if not from_email:
        raise EnvironmentError("FROM_EMAIL is not set. Add it to backend/.env")

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError as exc:
        raise ImportError('sendgrid not installed. Run: python -m pip install -e ".[backend]"') from exc

    savings = old_price - new_price
    savings_pct = (savings / old_price * 100) if old_price else 0

    html_content = f"""
    <div style="font-family: -apple-system, Arial, sans-serif;
                max-width: 560px; margin: auto; padding: 24px; color: #111;">
      <h2 style="color: #1d4ed8; margin-bottom: 4px;">Flight Price Dropped!</h2>
      <p style="color: #6b7280; margin-top: 0;">{flight_info}</p>
      <div style="background: #eff6ff; border: 1px solid #bfdbfe;
                  border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
        <div style="font-size: 2.4rem; font-weight: 800; color: #1e40af;">
          ${new_price:.2f}
        </div>
        <div style="color: #16a34a; font-size: 0.95rem; margin-top: 6px;">
          Save ${savings:.2f} ({savings_pct:.1f}% off)
          vs previous <span style="text-decoration: line-through; color: #9ca3af;">${old_price:.2f}</span>
        </div>
      </div>
      <a href="https://www.google.com/flights"
         style="display: inline-block; background: #1d4ed8; color: #fff;
                text-decoration: none; padding: 12px 32px;
                border-radius: 8px; font-weight: 600; font-size: 1rem;">
        Book Now
      </a>
      <hr style="margin: 28px 0; border: none; border-top: 1px solid #e5e7eb;">
      <p style="font-size: 0.72rem; color: #9ca3af;">
        You're receiving this because you're tracking this route on FlightWatch.<br>
        <a href="{APP_BASE_URL}/unsubscribe" style="color: #9ca3af;">Unsubscribe</a>
      </p>
    </div>
    """

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=f"Price Drop Alert: {flight_info} - now ${new_price:.2f}",
        html_content=html_content,
    )

    try:
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        success = response.status_code in (200, 202)
    except Exception as error:
        logger.error(
            "SendGrid error - status: %s | body: %s",
            error.status_code if hasattr(error, "status_code") else "N/A",
            error.body if hasattr(error, "body") else str(error),
        )
        raise

    if success:
        logger.info("Email sent to %s for %s", to_email, flight_info)
    else:
        logger.error("SendGrid returned status %d for %s", response.status_code, to_email)

    return success
