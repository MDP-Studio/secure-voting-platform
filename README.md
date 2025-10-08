# notAEC - Secure Voting System

A secure online voting platform inspired by Australian electoral systems, featuring multi-factor authentication, geo-filtering, and comprehensive security measures.

## Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt

   # or (recommended)
   python -m pip install -r requirements.txt
   ```

2. **Run the application:**
   ```bash
   python run_demo.py
   ```

3. **Access:** `http://localhost:5000`

**Credentials:**
 - Manager: admin / admin123
 - Delegate: delegate1 / delegate123
 - Voter: voter1 / password123

## Scripts

Utility scripts are located in the `scripts/` directory:

- **Generate favicon:** Regenerate the ICO favicon with multiple sizes
  ```bash
  python scripts/generate_favicon.py
  ```

## Environment Variables

The application uses environment variables for configuration. Copy `.env.example` to `.env` and adjust as needed.

Key variables:
- `GEO_FILTER_ENABLED`: Enable/disable geo-filtering based on IP country (default: True)
- `ENABLE_MFA`: Enable/disable multi-factor authentication with OTP emails (default: False)
- `MAIL_USERNAME`: Email account username for sending OTP emails
- `MAIL_PASSWORD`: Email account password/app password for sending OTP emails

- `SECRET_KEY`: Flask secret key for sessions (use a secure random key in production)
- `DATABASE_URL`: Database connection string (leave unset for SQLite in development, set for MySQL in Docker)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

For geo-filtering to work, download the GeoLite2-Country.mmdb database from MaxMind and place it in the `data/` directory.

### OTP/MFA Setup

To enable multi-factor authentication with email-based OTP:

1. Set `ENABLE_MFA=True` in your `.env` file
2. Configure email settings:
   - `MAIL_USERNAME`: see the project chat
   - `MAIL_PASSWORD`: see the project chat

**Gmail example:**
```bash
# Windows
setx MAIL_USERNAME "youraccount@gmail.com"
setx MAIL_PASSWORD "your-app-password"
setx ENABLE_MFA "True"

# Linux/macOS
export MAIL_USERNAME="youraccount@gmail.com"
export MAIL_PASSWORD="your-app-password"
export ENABLE_MFA="True"
```

**Note:** For Gmail, use an "App Password" instead of your regular password. Enable 2FA first, then generate an app password in your Google Account settings.
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

   # or (recommended)
   python -m pip install -r requirements-dev.txt
   ```

2. **Run tests:**
   ```bash
   python run_tests.py
   ```

📖 **Detailed testing guide:** See [`tests/README.md`](tests/README.md) for comprehensive testing documentation, including security test validation and debugging examples.

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

## DB

### Refreshing the DB

To reset the database, run:

```bash
docker-compose down
docker volume rm sec-soft-sys-a3_db_data
docker-compose up -d
```

This will delete all existing data and start with a fresh database.
