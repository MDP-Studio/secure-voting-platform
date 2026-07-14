
from flask import request, abort, current_app, g
from .geo_service import geoip_service
import os
import logging

# read .env file for environment variables
from dotenv import load_dotenv
load_dotenv()

# --- FEATURE FLAG ---
GEO_FILTER_ENABLED = os.getenv('GEO_FILTER_ENABLED') == 'True'

if GEO_FILTER_ENABLED:
    logging.info(" 🌏🟢 Geo-filtering is enabled")
else:
    logging.info(" 🌏🔴 Geo-filtering is disabled")

def check_geo_ip():
    """
    This function runs before every request to perform geo-filtering.
    """
    # 1. Only run if the feature flag is enabled.
    if not GEO_FILTER_ENABLED:
        return

    # 2. Don't block requests for static files (like CSS, JS) or internal assets.
    if request.path.startswith('/static'):
        return

    # 3. Get the user's real IP address.
    # ProxyFix consumes exactly one trusted proxy hop and exposes the selected
    # address as remote_addr. Client-prepended XFF values are not authoritative.
    user_ip = request.remote_addr
    
    # 4. Use the service to check the IP.
    if not geoip_service.is_ip_allowed(user_ip):
        # If not allowed, stop the request and show a "Forbidden" error.
        abort(403)

    # 5. Best-effort: attach detected AU state code to request context for downstream use (e.g., registration warning)
    try:
        g.geo_state = geoip_service.get_state_code(user_ip)
    except Exception:
        # Never break request if geo lookup fails
        logging.getLogger(__name__).debug("Handled exception in app/middleware.py", exc_info=True)
        g.geo_state = None
