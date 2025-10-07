# Secure Software Systems - Assignment 3

## Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt

   # or
   python -m pip install -r requirements.txt
   ```

2. **Run the application:**
   ```bash
   python run_demo.py
   ```

3. **Access:** `http://localhost:5000`

**Credentials:**
- Admin: `admin` / `admin123`
- Voter: `voter1` / `password123`

## Environment Variables

The application uses environment variables for configuration. Copy `.env.example` to `.env` and adjust as needed.

Key variables:
- `SECRET_KEY`: Flask secret key for sessions (use a secure random key in production)
- `DATABASE_URL`: Database connection string (leave unset for SQLite in development, set for MySQL in Docker)
- `GEO_FILTER_ENABLED`: Enable/disable geo-filtering based on IP country (default: True)
- `ALLOWED_COUNTRIES`: Comma-separated list of allowed country codes (default: AU)
- `ALLOWED_IPS`: Comma-separated list of allowed IP addresses/ranges for authentication
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

For geo-filtering to work, download the GeoLite2-Country.mmdb database from MaxMind and place it in the `data/` directory.

4. **OTP mail settings**
to set up OTP mail，please set the environment variable locally by typing the folloing command in terminal:
Windoows:
```
setx MAIL_USERNAME "youraccount@gmail.com"
setx MAIL_PASSWORD "abcd efgh ijkl mnop"
```
Linux:
```
export MAIL_USERNAME="youraccount@gmail.com"
export MAIL_PASSWORD="abcd efgh ijkl mnop"
```
## Docker Setup

1. **Build and run:**
   ```bash
   docker-compose up --build
   ```

2. **Access:** `http://localhost`

3. **Stop:**
   ```bash
   docker-compose down
   ```

**Credentials:** Same as local setup.

## Testing

1. **Install test dependencies:**
   ```bash
   pip install -r requirements-dev.txt
   ```

2. **Run tests:**
   ```bash
   python run_tests.py
   ```

**Note:** All 13 smoke tests should pass.

## Security Features

- **Rate Limiting:** 
   - Limits voting to 1 request per minute per IP.
   - Excess requests receive a `503 Service Unavailable` response.
   
```sh
$ curl -X POST http://localhost/vote -d "candidate_id=2"
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100   204  100   190  100    14  16929   1247 --:--:-- --:--:-- --:--:-- 18545<html>
<head><title>503 Service Temporarily Unavailable</title></head>
<body>
<center><h1>503 Service Temporarily Unavailable</h1></center>
<hr><center>nginx</center>
</body>
</html>
```
