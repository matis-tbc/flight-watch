import os
from typing import Optional

from .paths import BACKEND_ROOT


BASE_DIR = str(BACKEND_ROOT)
DEFAULT_CREDENTIAL_FILENAMES = (
    "service-account-key.json",
    "service-account-key copy.json",
)


def _normalize_candidate_path(raw_path: str) -> str:
    normalized_path = raw_path.strip()
    if not os.path.isabs(normalized_path):
        normalized_path = os.path.join(BASE_DIR, normalized_path)
    return os.path.abspath(normalized_path)


def resolve_google_application_credentials() -> Optional[str]:
    candidates = []
    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path and env_path.strip():
        candidates.append(_normalize_candidate_path(env_path))

    for filename in DEFAULT_CREDENTIAL_FILENAMES:
        candidates.append(os.path.abspath(os.path.join(BASE_DIR, filename)))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = candidate
            return candidate

    return None


def google_credentials_help(service_name: str = "Google Cloud") -> str:
    filenames = ", ".join(DEFAULT_CREDENTIAL_FILENAMES)
    return (
        f"{service_name} is not configured. Set GOOGLE_APPLICATION_CREDENTIALS in "
        f"backend/.env to a non-empty service account key file. "
        f"Checked backend/{filenames} and the current environment."
    )

