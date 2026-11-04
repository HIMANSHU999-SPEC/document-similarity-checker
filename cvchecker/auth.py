import streamlit as st


def _secrets_section(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def login_configured() -> bool:
    return bool(_secrets_section("auth"))


def email_allowed(email: str, allowed_domains, allowed_emails=None) -> bool:
    """True if the email passes the domain check and, when a list is set, is on allowed_emails."""
    email = (email or "").strip().lower()
    if allowed_emails:
        if email not in {e.strip().lower() for e in allowed_emails}:
            return False
    if not allowed_domains:
        return True
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return domain in {d.lower().lstrip("@") for d in allowed_domains}


def require_login():
    """Stops the page until a permitted Microsoft user is signed in. Returns (name, email), or None if login is off."""
    if not login_configured():
        return None
    if not st.user.get("is_logged_in"):
        st.title("📄 Document Similarity Checker")
        st.write("London Academy for Applied Technology staff only. Sign in with your LAAT Microsoft account.")
        st.button("Sign in with Microsoft", type="primary", on_click=st.login)
        st.stop()
    email = str(st.user.get("email") or st.user.get("preferred_username") or "")
    name = str(st.user.get("name") or email)
    access = _secrets_section("access") or {}
    if not email_allowed(email, access.get("allowed_domains", []), access.get("allowed_emails", [])):
        st.error(f"{email or 'This account'} is not allowed to use this app.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    return name, email
