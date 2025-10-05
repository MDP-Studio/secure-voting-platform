# Secure Software Systems - Assignment 3

## Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the application:**
   ```bash
   python run_demo.py
   ```

3. **Access:** `http://localhost:5000`

**Credentials:**
- Admin: `admin` / `admin123`
- Voter: `voter1` / `password123`

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