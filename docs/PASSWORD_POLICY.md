# Password Policy Enforcement

This document describes the comprehensive password policy implemented in the notAEC voting system to ensure secure authentication and protect user accounts.

## Overview

The password policy enforcement system implements multiple security layers:
1. **Password Strength Requirements** - Enforce strong password composition
2. **Account Lockout** - Prevent brute-force attacks
3. **Password Expiration** - Require periodic password updates
4. **Password Change Functionality** - Secure password update mechanism

---

## 1. Password Strength Requirements

All passwords in the system must meet the following minimum requirements:

### Requirements
- **Minimum Length**: 12 characters
- **Uppercase Letter**: At least 1 uppercase letter (A-Z)
- **Lowercase Letter**: At least 1 lowercase letter (a-z)
- **Special Character**: At least 1 special character from: `!@#$%^&*()_+-=[]{}|;:,.<>?`

### Validation
Password validation occurs at multiple points:
- During user registration
- When changing passwords
- Enforced at both frontend (HTML5) and backend (Python)

### Implementation
- **Module**: `app/security/password_validator.py`
- **Functions**:
  - `validate_password_strength(password)` - Returns (is_valid, error_message)
  - `validate_password_strength_strict(password)` - Raises PasswordValidationError if invalid
  - `check_password_strength_score(password)` - Returns detailed strength analysis

### Example Valid Passwords
```
TestPassword123!
MyP@ssw0rd2024
SecureVote#456
Admin@123456!
```

### Example Invalid Passwords
```
weak            # Too short, no uppercase, no special char
Password123     # No special character
password123!    # No uppercase letter
PASSWORD123!    # No lowercase letter
Short1!A        # Less than 12 characters
```

---

## 2. Account Lockout

The system implements automatic account lockout to prevent brute-force password attacks.

### Configuration
- **Maximum Failed Attempts**: 5 consecutive failed login attempts
- **Lockout Duration**: 30 minutes
- **Scope**: Per user account (not IP-based)

### Behavior

1. **Failed Login Tracking**
   - Each failed login attempt increments the `failed_login_attempts` counter
   - Counter is stored in the database per user
   - Failed attempts are logged with timestamp and IP address

2. **Account Lockout Trigger**
   - After 5 failed attempts, the account is locked
   - `account_locked_until` timestamp is set to current time + 30 minutes
   - User receives a message indicating the account is locked

3. **Lockout Enforcement**
   - Locked accounts cannot login, even with correct credentials
   - Login attempts on locked accounts are denied immediately
   - Warning message displayed: "Account is locked due to multiple failed login attempts"

4. **Lockout Expiration**
   - Account automatically unlocks after 30 minutes
   - User can then attempt to login again
   - Failed attempt counter remains until successful login

5. **Counter Reset**
   - Successful login resets `failed_login_attempts` to 0
   - Password change also resets the counter and unlocks the account
   - `account_locked_until` is cleared

### Database Fields
```python
failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
account_locked_until = db.Column(db.DateTime, nullable=True)
```

### User Model Methods
```python
user.is_account_locked()                          # Check if currently locked
user.record_failed_login(max_attempts=5, 
                        lockout_minutes=30)       # Record failed attempt
user.reset_failed_logins()                        # Clear counter and unlock
```

---

## 3. Password Expiration

Passwords expire after a defined period to encourage regular password updates.

### Configuration
- **Expiration Period**: 90 days (configurable)
- **Grace Period**: None - immediate forced change upon expiration

### Behavior

1. **Expiration Detection**
   - System checks `password_changed_at` timestamp on each login
   - Password is considered expired if older than 90 days
   - Accounts with no timestamp (legacy data) are considered expired

2. **Forced Password Change**
   - Users with expired passwords are redirected to `/change-password`
   - Login is granted temporarily to allow password change
   - User cannot access other parts of the application until password is changed
   - Warning message: "Your password has expired. Please change it to continue."

3. **Password Change Tracking**
   - `password_changed_at` timestamp updated on every password change
   - Timestamp stored in UTC
   - New user passwords start with current timestamp

### Database Field
```python
password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
```

### User Model Method
```python
user.is_password_expired(expiration_days=90)     # Check if password expired
```

---

## 4. Password Change Functionality

Secure password change mechanism for authenticated users.

### Access
- **Route**: `/change-password`
- **Authentication**: Required (login_required decorator)
- **Method**: GET (form display) and POST (form submission)

### Change Password Requirements

1. **Current Password Verification**
   - User must provide current password
   - Prevents unauthorized password changes if session is compromised

2. **New Password Requirements**
   - Must meet all password strength requirements
   - Must be different from current password
   - Prevents users from reusing the same password

3. **Password Confirmation**
   - New password must be entered twice
   - Both entries must match exactly

### Process Flow

1. User navigates to `/change-password` or is redirected if password expired
2. Form displays with three fields:
   - Current Password
   - New Password
   - Confirm New Password
3. On submission:
   - Verify user is authenticated
   - Validate current password
   - Check new password is different
   - Validate new password strength
   - Verify new passwords match
   - Update password hash
   - Update `password_changed_at` timestamp
   - Reset failed login attempts
   - Redirect to dashboard

### Security Features
- **No Password Reuse**: New password must differ from current
- **Timestamp Update**: Resets password expiration countdown
- **Lockout Reset**: Clears any failed login attempts
- **Session Validation**: Requires active authentication
- **Secure Hashing**: Uses Werkzeug's secure password hashing

### Error Messages
- "All fields are required"
- "Current password is incorrect"
- "New password must be different from current password"
- "New passwords do not match"
- "Password validation failed: [specific requirements not met]"

### Success Flow
- Flash message: "Password changed successfully!"
- Redirect to user dashboard
- Failed login counter reset to 0
- Account unlocked if previously locked

---

## Implementation Details

### File Structure
```
app/
├── models.py                           # User model with password fields
├── auth.py                             # Login with lockout & expiration checks
├── routes/
│   └── password.py                     # Password change routes
├── security/
│   └── password_validator.py          # Password validation logic
└── templates/
    └── change_password.html            # Password change form

tests/
└── test_password_policy.py             # Comprehensive policy tests
```

### Database Schema Changes

The User model includes these additional fields:

```python
class User(UserMixin, db.Model):
    # ... existing fields ...
    
    # Password policy fields
    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
```

### User Model Enhanced Methods

```python
# Password management
def set_password(self, password: str)
    # Validates strength, hashes password, updates timestamp, resets lockout

def check_password(self, password: str) -> bool
    # Verifies password against hash

# Account lockout
def is_account_locked(self) -> bool
    # Returns True if account is currently locked

def record_failed_login(self, max_attempts: int = 5, lockout_minutes: int = 30)
    # Increments counter, locks account if threshold reached

def reset_failed_logins(self)
    # Resets counter and unlocks account

# Password expiration
def is_password_expired(self, expiration_days: int = 90) -> bool
    # Returns True if password is older than expiration_days
```

---

## Testing

Comprehensive test suite in `tests/test_password_policy.py`:

### Test Coverage
- ✅ Account lockout after 5 failed attempts
- ✅ Account unlock after timeout period
- ✅ Failed attempts reset on successful login
- ✅ Password expiration after 90 days
- ✅ Forced password change when expired
- ✅ Password change with correct current password
- ✅ Password change fails with wrong current password
- ✅ Password change fails when passwords don't match
- ✅ Password change fails with weak password
- ✅ Password change fails with same password
- ✅ Password timestamp updates on change
- ✅ Failed attempts reset on password change

### Running Tests
```bash
# Run all password policy tests
python3 -m pytest tests/test_password_policy.py -v

# Run specific test class
python3 -m pytest tests/test_password_policy.py::TestAccountLockout -v

# Run with coverage
python3 -m pytest tests/test_password_policy.py --cov=app --cov-report=html
```

---

## Configuration

### Environment Variables

Password policy can be customized via configuration:

```python
# In app configuration or environment
PASSWORD_EXPIRATION_DAYS = 90          # Days until password expires
MAX_FAILED_LOGIN_ATTEMPTS = 5          # Attempts before lockout
ACCOUNT_LOCKOUT_MINUTES = 30           # Duration of lockout
```

### Customization Points

1. **Password Strength**: Modify `app/security/password_validator.py`
2. **Lockout Settings**: Adjust `max_attempts` and `lockout_minutes` in `record_failed_login()`
3. **Expiration Period**: Change `expiration_days` in `is_password_expired()`

---

## Security Considerations

### Best Practices Implemented
✅ Strong password composition requirements  
✅ Brute-force protection via account lockout  
✅ Regular password rotation via expiration  
✅ Secure password hashing (Werkzeug + bcrypt)  
✅ Password verification required for changes  
✅ Prevention of password reuse  
✅ Failed login attempt logging  
✅ Timestamp tracking for auditing  

### Additional Recommendations
- Monitor failed login patterns for security threats
- Consider implementing password history (prevent last N passwords)
- Add CAPTCHA after 3 failed attempts
- Send email notifications on suspicious activity
- Implement account recovery mechanism
- Add administrative password reset capability

---

## User Experience

### Registration Flow
1. User creates account at `/register`
2. Password strength validation provides immediate feedback
3. Requirements clearly displayed on form
4. Account created with timestamp for expiration tracking

### Login Flow
1. User attempts login
2. If password incorrect:
   - Failed attempt recorded
   - Warning shown if approaching lockout (optional enhancement)
   - Account locked after 5 attempts
3. If account locked:
   - Login denied with clear message
   - Wait 30 minutes or contact support
4. If password expired:
   - Login granted briefly
   - Redirected to password change
   - Cannot access app until password updated

### Password Change Flow
1. Access via `/change-password` or post-login redirect
2. Enter current password
3. Enter new password (twice)
4. Validation feedback in real-time
5. Success message and redirect to dashboard

---

## Compliance & Auditing

### Logging
All password-related security events are logged:
- Failed login attempts (with IP and timestamp)
- Account lockouts
- Password changes
- Expired password access attempts

### Audit Trail
Database fields provide audit trail:
- `created_at` - Account creation
- `password_changed_at` - Last password update
- `failed_login_attempts` - Current failed attempt count
- `account_locked_until` - Lockout expiration time

### Compliance
This implementation helps meet common security requirements:
- **NIST SP 800-63B**: Password composition and memorized secret guidelines
- **PCI DSS**: Account lockout and password complexity requirements
- **HIPAA**: Access control and password management
- **SOC 2**: Security monitoring and password policies

---

## Troubleshooting

### Account Locked
**Problem**: User cannot login, sees "Account is locked" message  
**Solution**: 
- Wait 30 minutes for automatic unlock
- Admin can manually reset via database: `UPDATE user SET failed_login_attempts=0, account_locked_until=NULL WHERE username='user'`
- Or reset via Python shell:
  ```python
  user = User.query.filter_by(username='username').first()
  user.reset_failed_logins()
  db.session.commit()
  ```

### Password Expired
**Problem**: User redirected to change password on login  
**Solution**: 
- Change password using the form
- Password must meet strength requirements
- Password must be different from current

### Forgot Password
**Problem**: User doesn't remember current password  
**Solution**: 
- Contact administrator for password reset
- (Future enhancement: implement self-service password reset via email)

---

## Future Enhancements

Potential improvements to password policy:

1. **Password History**
   - Track last 5-10 passwords
   - Prevent reuse of recent passwords
   - Store hashes in separate PasswordHistory table

2. **Configurable Policies**
   - Admin panel for policy configuration
   - Different policies for different roles
   - Per-organization customization

3. **Enhanced Feedback**
   - Real-time password strength meter
   - Estimated crack time display
   - Suggestions for strong passwords

4. **Self-Service Recovery**
   - Password reset via email
   - Security questions
   - Multi-factor password recovery

5. **Additional Security**
   - CAPTCHA after failed attempts
   - Email notifications on security events
   - IP-based rate limiting
   - Device fingerprinting

---

## References

- [NIST Digital Identity Guidelines](https://pages.nist.gov/800-63-3/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

---

**Last Updated**: October 16, 2025  
**Version**: 1.0  
**Status**: Implemented ✅
