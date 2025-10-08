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
 - Manager: admin / admin123
 - Delegate: delegate1 / delegate123
 - Voter: voter1 / password123

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


## DB

### Refreshing the DB

To reset the database, run:

```bash
docker-compose down
docker volume rm sec-soft-sys-a3_db_data
docker-compose up -d
```

This will delete all existing data and start with a fresh database.
