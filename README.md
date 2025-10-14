# notAEC - Secure Voting System

A secure online voting platform inspired by Australian electoral systems, featuring multi-factor authentication, geo-filtering, and comprehensive security measures.

## Quick Links 🔗

- **Basic Flask App Demo:** [http://localhost:5000](http://localhost:5000) (no WAF protection)
- **WAF Protected:** [http://localhost](http://localhost) (with nginx + ModSecurity)
- **Test Documentation:** [tests/README.md](tests/README.md)
- **WAF Demo Tool:** `/tests/test_waf_demo.py`
- **Testing Section:** [Jump to Testing](#testing)

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

3. **Validate WAF Security:** 🛡️
   ```bash
   python ./tests/test_waf_demo.py

   python ./tests/test_vote_rate_limiting.py
   ```

📖 **Detailed testing guide:** See [`tests/README.md`](tests/README.md) for comprehensive testing documentation, including security test validation and debugging examples.

## Security Features

### 🛡️ Web Application Firewall (WAF) Validation

Test the effectiveness of the OWASP ModSecurity Core Rule Set by comparing direct application access vs WAF-protected access:

```bash
python test_waf_demo.py
```

This demonstration script shows how the WAF provides additional security layers:

- **Direct Access (port 8000):** Flask application without WAF protection
- **WAF Protected (port 80):** Traffic filtered through nginx + ModSecurity

**Example Output:**
```
================================================================================
🛡️  WAF FUNCTIONALITY DEMONSTRATION
================================================================================

🎯 XSS Script Tag:
  Payload: <script>alert('xss')</script>
  Direct (port 8000): Status 200 - ⚠️ ALLOWED
  Through WAF (port 80): Status 403 - 🛡️ BLOCKED

✅ SUCCESS: WAF provides additional security by blocking malicious requests!
   🛡️  WAF blocked 5 more malicious payloads than direct access.
```

The WAF automatically blocks common attack vectors including XSS, SQL injection, and other malicious payloads while allowing legitimate traffic.

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

## HashiCorp Vault (optional, recommended)

This app can use Vault for two purposes:
- Transit engine for signing/verifying election results (private keys never leave Vault)
- KV v2 for storing the JWT secret

Environment variables:
- `VAULT_ADDR`, `VAULT_TOKEN`
- `VAULT_MOUNT` (default: `transit`), `VAULT_TRANSIT_KEY` (default: `results-signing`)
- `VAULT_KV_MOUNT` (default: `kv`), `VAULT_JWT_PATH` (default: `app/jwt`), `VAULT_JWT_KEY` (default: `secret`)

Provisioning helper:

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=xxxx
export JWT_SECRET_VALUE=$(openssl rand -hex 32)
bash scripts/provision_vault.sh
```

Suggested policy (attach to the app token):

```hcl
path "transit/sign/results-signing" {
  capabilities = ["update"]
}
path "transit/verify/results-signing" {
  capabilities = ["update"]
}
path "kv/data/app/jwt" {
  capabilities = ["read"]
}
```

If Vault is not configured, the app falls back to local RSA keys under the Flask instance folder for result signing and to `SECRET_KEY` env var for JWT.

This will delete all existing data and start with a fresh database.
