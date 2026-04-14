import os


def get_secure_user_id() -> str:
    """
    Returns the authenticated user ID.
    This is the single security boundary — the LLM never sees or controls user_id.
    Replace the env lookup with JWT decoding or session lookup as needed.
    """
    user_id = os.environ.get("CURRENT_USER_ID")
    if not user_id:
        raise RuntimeError("CURRENT_USER_ID environment variable is not set.")
    return user_id
