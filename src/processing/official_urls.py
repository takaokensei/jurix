"""Conservative URL formatting for user-visible source links."""

from urllib.parse import urlsplit


def safe_official_url(value: str | None) -> str | None:
    """Return only absolute HTTP(S) URLs without credentials or control characters."""
    candidate = str(value or "").strip()
    if not candidate or any(ord(char) < 32 for char in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        _ = parsed.port
    except ValueError:
        return None
    return candidate
