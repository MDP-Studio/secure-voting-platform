"""Canonical public URL generation for security-sensitive email links."""

from flask import current_app


def public_url_for(endpoint, **values):
    """Build a URL from the configured public origin, never the request Host."""
    current_app.inject_url_defaults(endpoint, values)
    adapter = current_app.url_map.bind("")
    relative_url = adapter.build(endpoint, values, force_external=False)
    return f"{current_app.config['PUBLIC_BASE_URL']}{relative_url}"
