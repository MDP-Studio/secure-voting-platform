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
   - Admin: `admin` / `admin123`
   - Voter: `voter1` / `password123`
   
   **How to login:**
   - The login page will load automatically
   - Leave the "Election" dropdown as-is (it's not functional in the demo)
   - Enter `admin` in the "Voter ID or Email" field (for admin access) or `voter1` (for voter)
   - Enter the corresponding password (`admin123` or `password123`)
   - Leave the "Authenticator Code" field empty (2FA not implemented in demo)
   - Click "Sign In & Access Ballot"
   
   **After login:** You'll see the voting dashboard with 3 demo candidates (John Smith, Sarah Johnson, Mike Brown) running for House of Representatives. You can vote for one of them, and once voted, you won't be able to vote again.

**Note:** The `run_demo.py` script will automatically initialize the database with sample users and candidates for testing.

#### Database Information

- **Database Type:** SQLite (for local development), MySQL (for Docker)
- **Location:** `instance/app.db` (created automatically for local), or MySQL container in Docker
- **Auto-initialization:** Tables are created automatically when the app starts
- **Demo Data:** `run_demo.py` (or `init_db.py`) creates:
  - 1 admin user (username: `admin`, password: `admin123`)
  - 1 voter user (username: `voter1`, password: `password123`)
  - 3 sample candidates for House of Representatives position (John Smith - Labor Party, Sarah Johnson - Liberal Party, Mike Brown - Greens)

**Note:** This is a simplified setup for the early phase of the university project. The current model includes candidate information with name, party, position, and constituency.

#### Alternative Database Setup

The `run_demo.py` script automatically initializes the database with sample data. If you need to manually initialize or reset the database with the same sample data, run:

```bash
python init_db.py
```

This creates the same sample data as `run_demo.py`:
- Admin user: `admin` / `admin123`
- Voter user: `voter1` / `password123`
- 3 candidates for House of Representatives

### Testing

The project includes smoke tests to verify basic functionality:

1. **Install test dependencies:**
   ```bash
   pip install -r requirements-dev.txt
   ```

2. **Run smoke tests:**
   ```bash
   python run_tests.py
   ```
   
   Or run tests directly with pytest:
   ```bash
   pytest tests/test_smoke.py -v
   ```

**What the smoke tests verify:**
- ✅ App creation and database initialization
- ✅ Login/logout functionality  
- ✅ User authentication and authorization
- ✅ Voting process (single vote per user)
- ✅ Admin access to results
- ✅ Basic security (prevent double voting)

**Test Results:** All 13 smoke tests pass! 🎉

### Docker Setup

This setup runs the Flask app, MySQL database, and nginx WAF in containers.

1. Ensure Docker Desktop is installed and running.
2. Build and start the services:
   ```
   docker-compose up --build
   ```
3. Access the app at `http://localhost`.
4. To stop the services:
   ```
   docker-compose down
   ```

**Database:** Uses MySQL database with the same sample data initialized via `init_db.py`.

**Default Credentials:**
- Admin: `admin` / `admin123`
- Voter: `voter1` / `password123`
