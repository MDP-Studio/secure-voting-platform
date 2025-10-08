import os
import logging
import geoip2.database

# --- GEO-FILTERING CONFIGURATION ---
GEOIP_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'GeoLite2-Country.mmdb')
ALLOWED_COUNTRIES = os.getenv('ALLOWED_COUNTRIES', 'AU').split(',')

class GeoIPService:
    def __init__(self, db_path=GEOIP_DB_PATH):
        """Initializes the service by loading the GeoIP database."""
        try:
            self.reader = geoip2.database.Reader(db_path)
            logging.info(f" 🌏 GeoIP database loaded from '{db_path}'.")
        except FileNotFoundError:
            self.reader = None
            logging.critical(f"CRITICAL: GeoIP database not found at '{db_path}'. Geo-filtering is disabled.")

    def is_ip_allowed(self, ip_address: str) -> bool:
        """
        Checks if a given IP address originates from an allowed country.
        Returns True if allowed, False otherwise.
        """
        # If the database failed to load, fail open (allow access) but log critically.
        if not self.reader:
            return True

        try:
            response = self.reader.country(ip_address)
            user_country_code = response.country.iso_code
            
            if user_country_code in ALLOWED_COUNTRIES:
                logging.info(f" 🌏✅ Geo-filter pass: Allowed request from IP {ip_address} in country {user_country_code}.")
                return True
            else:
                logging.warning(f" 🌏❌ Geo-filter block: Denied request from IP {ip_address} in country {user_country_code}.")
                return False

        except geoip2.errors.AddressNotFoundError:
            # This occurs for private/local IPs, which we should always allow.
            logging.info(f" 🌏🧑‍💻✅ Request from a local/private IP address: {ip_address}. Allowing.")
            return True

# Create a single instance of the service to be used by the app
geoip_service = GeoIPService()