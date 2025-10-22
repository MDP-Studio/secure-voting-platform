# Test Voter Generator

This module provides functionality to generate 100 realistic test voters for testing the secure voting system at scale. It's particularly useful for load testing, UI testing, and ensuring the system works correctly with a larger voter base.

## Features

- **100 Realistic Test Voters**: Generated with diverse, realistic names from various backgrounds
- **Complete Voter Data**: Each test voter includes:
  - Unique username (testvoter001, testvoter002, etc.)
  - Realistic email addresses
  - Full names with diverse first and last names
  - Australian addresses with real suburbs, states, and postcodes
  - Realistic dates of birth (ages 18-80)
  - Valid driver's license numbers
  - Electoral roll numbers
- **Optional Creation**: Test voters are only created when explicitly enabled
- **Electoral Roll Integration**: Automatically creates electoral roll entries for all test voters

## Files Added

- `app/generate_test_voters.py` - Main test voter data generator
- `create_test_voters.py` - Helper script for managing test voter creation

## Usage

### Method 1: Environment Variable

1. Enable test voter creation in your `.env` file:
   ```bash
   CREATE_TEST_VOTERS=true
   ```

2. Run the application (this will create test voters on database initialization):
   ```bash
   python run_demo.py
   ```

### Method 2: Helper Script

Use the provided helper script for easier management:

```bash
# Enable test voter creation and reset database
python create_test_voters.py --reset

# Just enable test voter creation
python create_test_voters.py --enable

# Disable test voter creation
python create_test_voters.py --disable

# Show current status
python create_test_voters.py --show
```

### Method 3: Manual Database Reset

If you want to start fresh with test voters:

1. Delete the existing database:
   ```bash
   rm instance/app.db
   ```

2. Set the environment variable:
   ```bash
   export CREATE_TEST_VOTERS=true
   ```

3. Run the application:
   ```bash
   python run_demo.py
   ```

## Test Voter Details

- **Usernames**: `testvoter001` through `testvoter100`
- **Password**: All test voters use the password `testpass123`
- **Email Format**: `firstname.lastname###@testvoters.com`
- **Role**: All test voters have the "voter" role
- **Status**: All test voters are verified and active in the electoral roll
- **Regions**: Test voters are randomly distributed across available regions

## Example Test Voters

Here are some examples of the generated test voters:

1. **testvoter001**: James Smith (james.smith1@testvoters.com)
   - Address: 123 King Street, Sydney, NSW 2000
   - DOB: 1985-03-15
   - DL: AB123456

2. **testvoter002**: Mary Johnson (mary.johnson2@testvoters.com)
   - Address: 456 Queen Street, Melbourne, VIC 3000
   - DOB: 1992-07-22
   - DL: CD789012

## Security Considerations

- Test voters are clearly identified with the "testvoter" prefix
- They use a common test password that should never be used in production
- Test emails use the @testvoters.com domain to avoid conflicts
- The feature is disabled by default and must be explicitly enabled

## Development Benefits

1. **Load Testing**: Test system performance with 100+ voters
2. **UI Testing**: Verify the interface works with larger user lists
3. **Role Testing**: Ensure proper role-based access control
4. **Database Testing**: Validate database performance with more data
5. **Authentication Testing**: Test login systems with multiple users

## Production Safety

- Test voter creation is **disabled by default**
- Must be explicitly enabled via environment variable
- Clear naming convention prevents confusion with real users
- Easy to disable and clean up

## Cleanup

To remove test voters from your database:

1. Disable test voter creation:
   ```bash
   python create_test_voters.py --disable
   ```

2. Reset the database:
   ```bash
   rm instance/app.db
   python run_demo.py
   ```

This will recreate the database with only the standard test users (admin, delegate1, voter1, lix).