# Secure Software Systems - Assignment 3

## How to Start

### Development Setup (Flask)

The Flask application is now ready to run locally:

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the demo application:**
   ```bash
   python run_demo.py
   ```

3. **Access the application:**
   Open your browser and go to `http://localhost:5000`
   
   **Demo credentials:**
   - Username: `demo`
   - Password: `password`

**Note:** The `run_demo.py` script will automatically create a demo user and seed candidate data for testing.

#### Database Information

- **Database Type:** SQLite
- **Location:** `instance/app.db` (created automatically)
- **Auto-initialization:** Tables are created automatically when the app starts
- **Demo Data:** `run_demo.py` creates:
  - 1 demo user (username: `demo`, password: `password`)
  - 2 sample candidates (Alice Johnson and Bob Smith for Mayor)

#### Alternative Database Setup

For additional sample data including an admin user, run:

```bash
python init_db.py
```

**Admin credentials (from init_db.py):**
- Username: `admin`
- Password: `admin123`
- Additional voter: `voter1` / `password123`

This creates more comprehensive sample data including multiple candidates for different positions.

### Docker Setup (Coming Soon)

Once Docker setup is complete, you'll be able to run:
```bash
docker-compose up --build
```