import hashlib
import hmac

MAX_ATTEMPTS = 5


def settings(secrets) -> dict:
    try:
        return dict(secrets.get("special") or {})
    except Exception:
        return {}


def can_use(email: str, config: dict) -> bool:
    """Special actions need a configured code and the signed-in email on the named list."""
    allowed = {e.strip().lower() for e in config.get("allowed_emails", [])}
    return bool(config.get("code_sha256")) and bool(email) and email.strip().lower() in allowed


def code_matches(code: str, config: dict) -> bool:
    expected = str(config.get("code_sha256", "")).strip().lower()
    given = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    return bool(expected) and hmac.compare_digest(given, expected)
