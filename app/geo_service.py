import os
import logging
import geoip2.database

# --- GEO-FILTERING CONFIGURATION ---
GEOIP_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'GeoLite2-Country.mmdb')
# Optional City database (for subdivision/state detection). If missing, state detection is disabled gracefully.
GEOIP_CITY_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'GeoLite2-City.mmdb')
ALLOWED_COUNTRIES = os.getenv('ALLOWED_COUNTRIES', 'AU').split(',')

class GeoIPService:
    def __init__(self, db_path=GEOIP_DB_PATH, city_db_path=GEOIP_CITY_DB_PATH):
        """Initializes the service by loading the GeoIP databases.

        Country DB is required for country allow/deny. City DB is optional and used for subdivision/state detection.
        """
        try:
            self.reader = geoip2.database.Reader(db_path)
            logging.info(f" 🌏 GeoIP Country DB loaded from '{db_path}'.")
        except FileNotFoundError:
            self.reader = None
            logging.critical(f"CRITICAL: GeoIP Country DB not found at '{db_path}'. Geo-filtering is disabled.")

        try:
            self.city_reader = geoip2.database.Reader(city_db_path)
            logging.info(f" 🗺️ GeoIP City DB loaded from '{city_db_path}'. Subdivision detection enabled.")
        except FileNotFoundError:
            self.city_reader = None
            logging.warning(f"GeoIP City DB not found at '{city_db_path}'. Subdivision detection disabled.")

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

    def get_state_code(self, ip_address: str) -> str | None:
        """Return AU state code (e.g., NSW, VIC) for the given IP, if determinable.

        Requires the City DB. Returns None if unavailable or not in AU.
        """
        if not self.city_reader:
            return None

        try:
            city = self.city_reader.city(ip_address)
            if (city.country and city.country.iso_code == 'AU' and
                city.subdivisions and len(city.subdivisions) > 0):
                name_or_code = (city.subdivisions.most_specific.iso_code or city.subdivisions.most_specific.name or '').upper()
                # Normalize to our expected AU codes
                fullname_map = {
                    'NEW SOUTH WALES': 'NSW', 'NSW': 'NSW',
                    'VICTORIA': 'VIC', 'VIC': 'VIC',
                    'QUEENSLAND': 'QLD', 'QLD': 'QLD',
                    'SOUTH AUSTRALIA': 'SA', 'SA': 'SA',
                    'WESTERN AUSTRALIA': 'WA', 'WA': 'WA',
                    'TASMANIA': 'TAS', 'TAS': 'TAS',
                    'NORTHERN TERRITORY': 'NT', 'NT': 'NT',
                    'AUSTRALIAN CAPITAL TERRITORY': 'ACT', 'ACT': 'ACT',
                }
                return fullname_map.get(name_or_code)
        except geoip2.errors.AddressNotFoundError:
            # Private/local IPs
            return None
        except Exception as e:
            logging.debug(f"GeoIP subdivision lookup failed for {ip_address}: {e}")
            return None

# Create a single instance of the service to be used by the app
geoip_service = GeoIPService()