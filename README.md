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

## Updates
