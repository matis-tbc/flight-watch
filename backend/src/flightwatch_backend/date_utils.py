from datetime import datetime
from typing import Optional


SUPPORTED_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
)


def normalize_date_text(raw_value) -> Optional[str]:
    if raw_value is None:
        return None

    if hasattr(raw_value, "date"):
        return raw_value.date().isoformat()

    date_text = str(raw_value).strip()
    if not date_text:
        return None

    candidate = date_text.split("T", 1)[0].strip()

    for date_format in SUPPORTED_DATE_FORMATS:
        try:
            return datetime.strptime(candidate, date_format).date().isoformat()
        except ValueError:
            continue

    return candidate

