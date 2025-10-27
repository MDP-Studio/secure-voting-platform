from flask import flash, session


def flash_once(message: str, category: str = 'message') -> None:
    """Flash a message only if an identical (category, message) tuple
    is not already present in the session's _flashes list.
    """
    try:
        existing = session.get('_flashes') or []
    except Exception:
        existing = []

    if (category, message) in existing:
        return
    flash(message, category)
