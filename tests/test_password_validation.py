"""
Unit tests for password validation.

This test suite validates the password strength requirements:
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 special character
"""

import pytest
from app.security.password_validator import (
    validate_password_strength,
    validate_password_strength_strict,
    PasswordValidationError,
    check_password_strength_score,
    get_password_requirements,
)
from app.models import User
from app import db


def _generate_valid_driver_license(base: str = "DL12345") -> str:
    """
    Generate a valid driver license with proper checksum.
    
    Args:
        base: Base string (without checksum)
        
    Returns:
        str: Valid driver license with checksum
    """
    def _checksum11(s: str) -> int:
        val = 0
        for i, ch in enumerate(s, start=1):
            if ch.isdigit():
                v = ord(ch) - 48
            else:
                v = 10 + (ord(ch.upper()) - 65)
            val += v * i
        return val % 11
    
    chk = _checksum11(base)
    if chk == 10:
        return base + 'X'
    return base + str(chk)


class TestPasswordValidationFunction:
    """Test the standalone password validation functions."""
    
    def test_valid_strong_password(self):
        """Test that a valid strong password passes validation."""
        password = "MyP@ssw0rd123"
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
        assert error is None
    
    def test_valid_strong_password_minimum_length(self):
        """Test password with exactly 12 characters."""
        password = "Abcdef123!@#"
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
        assert error is None
    
    def test_password_too_short(self):
        """Test that short password fails validation."""
        password = "Short1!Aa"  # Only 9 characters
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "at least 12 characters" in error
    
    def test_password_missing_uppercase(self):
        """Test that password without uppercase fails."""
        password = "nouppercase123!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "uppercase letter" in error
    
    def test_password_missing_lowercase(self):
        """Test that password without lowercase fails."""
        password = "NOLOWERCASE123!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "lowercase letter" in error
    
    def test_password_missing_special_char(self):
        """Test that password without special character fails."""
        password = "NoSpecial123Abc"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "special character" in error
    
    def test_password_empty(self):
        """Test that empty password fails validation."""
        password = ""
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "cannot be empty" in error
    
    def test_password_multiple_failures(self):
        """Test password with multiple validation failures."""
        password = "weak"  # Too short, no uppercase, no special
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        # Should mention multiple issues
        assert "12 characters" in error
        assert "uppercase" in error
        assert "special" in error
    
    def test_password_with_various_special_chars(self):
        """Test that various special characters are accepted."""
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        for char in special_chars:
            password = f"ValidPass123{char}"
            is_valid, error = validate_password_strength(password)
            assert is_valid is True, f"Character '{char}' should be valid"
    
    def test_strict_validation_raises_exception(self):
        """Test that strict validation raises exception for invalid password."""
        password = "weak"
        with pytest.raises(PasswordValidationError) as exc_info:
            validate_password_strength_strict(password)
        assert "12 characters" in str(exc_info.value)
    
    def test_strict_validation_passes_for_valid(self):
        """Test that strict validation returns True for valid password."""
        password = "StrongPass123!"
        result = validate_password_strength_strict(password)
        assert result is True


class TestPasswordStrengthScore:
    """Test the password strength scoring function."""
    
    def test_very_weak_password_score(self):
        """Test scoring for very weak password."""
        result = check_password_strength_score("weak")
        assert result['score'] == 1  # Only has lowercase
        assert result['strength'] == 'Weak'
        assert result['meets_requirements'] is False
        assert len(result['feedback']) > 0
    
    def test_strong_password_score(self):
        """Test scoring for strong password."""
        result = check_password_strength_score("StrongPass123!")
        assert result['score'] >= 4
        assert result['strength'] in ['Strong', 'Very Strong']
        assert result['meets_requirements'] is True
        assert len(result['feedback']) == 0
    
    def test_password_score_feedback(self):
        """Test that feedback is provided for weak passwords."""
        result = check_password_strength_score("onlylowercase")
        assert 'feedback' in result
        assert any('uppercase' in fb for fb in result['feedback'])
        assert any('special' in fb for fb in result['feedback'])


class TestPasswordRequirementsDisplay:
    """Test the password requirements display functions."""
    
    def test_get_requirements_text(self):
        """Test that requirements text is returned."""
        requirements = get_password_requirements()
        assert "12 characters" in requirements
        assert "uppercase" in requirements
        assert "lowercase" in requirements
        assert "special character" in requirements


class TestUserModelPasswordValidation:
    """Test password validation integration with User model."""
    
    def test_user_set_password_valid(self, app):
        """Test that valid password can be set on User model."""
        with app.app_context():
            user = User(username="testuser", email="test@test.com", driver_lic_no="DL123458", driver_lic_state="NSW")
            user.set_password("ValidPass123!")
            assert user.password_hash is not None
            assert user.check_password("ValidPass123!")
    
    def test_user_set_password_invalid_raises_error(self, app):
        """Test that invalid password raises PasswordValidationError."""
        with app.app_context():
            user = User(username="testuser", email="test@test.com", driver_lic_no="DL123459", driver_lic_state="NSW")
            with pytest.raises(PasswordValidationError):
                user.set_password("weak")
    
    def test_user_set_password_too_short(self, app):
        """Test that short password is rejected."""
        with app.app_context():
            user = User(username="testuser", email="test@test.com", driver_lic_no="DL123460", driver_lic_state="NSW")
            with pytest.raises(PasswordValidationError) as exc_info:
                user.set_password("Short1!")
            assert "12 characters" in str(exc_info.value)
    
    def test_user_set_password_no_uppercase(self, app):
        """Test that password without uppercase is rejected."""
        with app.app_context():
            user = User(username="testuser", email="test@test.com", driver_lic_no="DL123461", driver_lic_state="NSW")
            with pytest.raises(PasswordValidationError) as exc_info:
                user.set_password("nouppercase123!")
            assert "uppercase" in str(exc_info.value)
    
    def test_user_set_password_no_special(self, app):
        """Test that password without special character is rejected."""
        with app.app_context():
            user = User(username="testuser", email="test@test.com", driver_lic_no="DL123462", driver_lic_state="NSW")
            with pytest.raises(PasswordValidationError) as exc_info:
                user.set_password("NoSpecial123Abc")
            assert "special" in str(exc_info.value)


class TestPasswordValidationEdgeCases:
    """Test edge cases for password validation."""
    
    def test_password_exactly_12_chars(self):
        """Test password with exactly 12 characters."""
        password = "Valid123!@#A"
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
    
    def test_password_with_unicode(self):
        """Test password with unicode characters."""
        # Unicode special characters might not be counted
        password = "Password123!αβγ"
        is_valid, error = validate_password_strength(password)
        # Should pass because it has regular special char (!)
        assert is_valid is True
    
    def test_password_all_requirements_edge(self):
        """Test password that barely meets all requirements."""
        password = "Aa1!aaaaaaaa"  # Exactly 12 chars, 1 upper, 1 lower, 1 special, 1 number
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
    
    def test_very_long_password(self):
        """Test that very long passwords are accepted."""
        password = "A" * 50 + "a" * 50 + "1" * 50 + "!" * 50
        is_valid, error = validate_password_strength(password)
        assert is_valid is True


class TestPasswordValidationIntegration:
    """Integration tests for password validation in user registration flow."""
    
    def test_registration_with_weak_password(self, client, app):
        """Test that registration fails with weak password."""
        valid_license = _generate_valid_driver_license("DL12340")
        response = client.post('/register', data={
            'username': 'newuser',
            'email': 'newuser@test.com',
            'password': 'weak',
            'confirm': 'weak',
            'driver_lic_no': valid_license,  # Valid driver license
            'driver_lic_state': 'NSW'
        }, follow_redirects=True)
        
        # Weak password should be rejected - user should not be created
        with app.app_context():
            user = User.query.filter_by(username='newuser').first()
            assert user is None, "User with weak password should not be created"
    
    def test_registration_with_strong_password(self, client, app):
        """Test that registration succeeds with strong password."""
        valid_license = _generate_valid_driver_license("DL12341")
        response = client.post('/register', data={
            'username': 'stronguser',
            'email': 'stronguser@test.com',
            'password': 'StrongPass@123',  # 12+ chars with uppercase, lowercase, special char, digit
            'confirm': 'StrongPass@123',
            'driver_lic_no': valid_license,  # Programmatically generated valid license
            'driver_lic_state': 'NSW'
        }, follow_redirects=True)
        
        # Verify user was created with strong password
        with app.app_context():
            user = User.query.filter_by(username='stronguser').first()
            assert user is not None, "User with strong password should be created"
            assert user.check_password('StrongPass@123'), "Password should match"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
