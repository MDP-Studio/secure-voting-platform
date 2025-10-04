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
   
   **How to login:**
   - The login page will load automatically
   - Leave the "Election" dropdown as-is (it's not functional in the demo)
   - Enter `demo` in the "Voter ID or Email" field
   - Enter `password` in the "Password / One-Time Code" field
   - Leave the "Authenticator Code" field empty (2FA not implemented in demo)
   - Click "Sign In & Access Ballot"
   
   **After login:** You'll see the voting dashboard with 2 demo candidates (Alice Johnson and Bob Smith) running for Mayor. You can vote for one of them, and once voted, you won't be able to vote again.

**Note:** The `run_demo.py` script will automatically create a demo user and seed candidate data for testing.

#### Database Information

- **Database Type:** SQLite
- **Location:** `instance/app.db` (created automatically)
- **Auto-initialization:** Tables are created automatically when the app starts
- **Demo Data:** `run_demo.py` creates:
  - 1 demo user (username: `demo`, password: `password`)
  - 2 sample candidates for Mayor position (Alice Johnson and Bob Smith)

**Note:** This is a simplified setup for the early phase of the university project. The current model only includes basic candidate information (name and position).

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

### Docker Setup (Coming Soon)