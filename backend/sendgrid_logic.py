import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

def send_price_drop_email(to_email, flight_info, old_price, new_price):
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject="✈️ Flight Price Drop Alert!",
        html_content=f"""
        <h2>Flight Price Dropped!</h2>
        <p><strong>{flight_info}</strong></p>
        <p>Old Price: ${old_price}</p>
        <p>New Price: <strong>${new_price}</strong></p>
        """
    )

    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)
