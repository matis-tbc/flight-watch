import base64
import hashlib
import hmac
import os


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def get_unsubscribe_secret() -> str:
    secret = (
        os.getenv("UNSUBSCRIBE_SECRET", "").strip()
        or os.getenv("SCHEDULER_TOKEN", "").strip()
    )
    if not secret:
        raise EnvironmentError(
            "Missing unsubscribe signing secret. Set UNSUBSCRIBE_SECRET or SCHEDULER_TOKEN."
        )
    return secret


def build_unsubscribe_token(email: str) -> str:
    normalized_email = _normalize_email(email)
    digest = hmac.new(
        get_unsubscribe_secret().encode("utf-8"),
        normalized_email.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def is_valid_unsubscribe_token(email: str, token: str) -> bool:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return False
    expected = build_unsubscribe_token(email)
    return hmac.compare_digest(normalized_token, expected)
