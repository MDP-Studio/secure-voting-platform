"""
Password validation utilities for secure password requirements.

This module provides password strength validation to ensure all user passwords
meet security requirements:
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 special character
"""

import re


class PasswordValidationError(Exception):
    """Raised when a password does not meet security requirements."""
    pass


def validate_password_strength(password):
    """
    Validate that a password meets strong password requirements.
    
    Requirements:
    - Minimum 12 characters
    - At least 1 uppercase letter (A-Z)
    - At least 1 lowercase letter (a-z)
    - At least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    
    Args:
        password (str): The password to validate
        
    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if password meets all requirements, False otherwise
            - error_message: Description of what's wrong, or None if valid
            
    Raises:
        PasswordValidationError: If password does not meet requirements
    """
    if not password:
        return False, "Password cannot be empty"
    
    errors = []
    
    # Check minimum length
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long")
    
    # Check for uppercase letter
    if not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least 1 uppercase letter")
    
    # Check for lowercase letter
    if not re.search(r'[a-z]', password):
        errors.append("Password must contain at least 1 lowercase letter")
    
    # Check for special character
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', password):
        errors.append("Password must contain at least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)")
    
    if errors:
        error_message = "; ".join(errors)
        return False, error_message
    
    return True, None


def validate_password_strength_strict(password):
    """
    Validate password strength and raise exception if invalid.
    
    This is a strict version that raises an exception instead of returning a tuple.
    Use this when you want to enforce validation with exception handling.
    
    Args:
        password (str): The password to validate
        
    Raises:
        PasswordValidationError: If password does not meet requirements
    """
    is_valid, error_message = validate_password_strength(password)
    if not is_valid:
        raise PasswordValidationError(error_message)
    return True


def get_password_requirements():
    """
    Get a user-friendly description of password requirements.
    
    Returns:
        str: Description of password requirements
    """
    return (
        "Password must meet the following requirements:\n"
        "• At least 12 characters long\n"
        "• At least 1 uppercase letter (A-Z)\n"
        "• At least 1 lowercase letter (a-z)\n"
        "• At least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)"
    )


def get_password_requirements_html():
    """
    Get an HTML-formatted description of password requirements.
    
    Returns:
        str: HTML description of password requirements
    """
    return """
    <div class="password-requirements">
        <p><strong>Password Requirements:</strong></p>
        <ul>
            <li>At least 12 characters long</li>
            <li>At least 1 uppercase letter (A-Z)</li>
            <li>At least 1 lowercase letter (a-z)</li>
            <li>At least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)</li>
        </ul>
    </div>
    """


def check_password_strength_score(password):
    """
    Calculate a password strength score (0-4).
    
    Args:
        password (str): The password to evaluate
        
    Returns:
        dict: Dictionary containing:
            - score: int (0-4)
            - strength: str ('Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong')
            - meets_requirements: bool
            - feedback: list of strings with improvement suggestions
    """
    score = 0
    feedback = []
    
    # Length check
    if len(password) >= 12:
        score += 1
    else:
        feedback.append(f"Increase length to at least 12 characters (current: {len(password)})")
    
    # Uppercase check
    if re.search(r'[A-Z]', password):
        score += 1
    else:
        feedback.append("Add at least 1 uppercase letter")
    
    # Lowercase check
    if re.search(r'[a-z]', password):
        score += 1
    else:
        feedback.append("Add at least 1 lowercase letter")
    
    # Special character check
    if re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', password):
        score += 1
    else:
        feedback.append("Add at least 1 special character")
    
    # Additional length bonus
    if len(password) >= 16:
        score = min(score + 0.5, 4)
    
    strength_labels = {
        0: 'Very Weak',
        1: 'Weak',
        2: 'Fair',
        3: 'Strong',
        4: 'Very Strong'
    }
    
    meets_requirements = score >= 4
    strength = strength_labels.get(int(score), 'Very Weak')
    
    return {
        'score': score,
        'strength': strength,
        'meets_requirements': meets_requirements,
        'feedback': feedback
    }


# Example usage
if __name__ == '__main__':
    # Test various passwords
    test_passwords = [
        'weak',
        'StrongPassword1!',
        'MyP@ssw0rd123',
        'VerySecure123!@#',
        'short!1A',
    ]
    
    print("Password Strength Validation Tests\n")
    print("=" * 60)
    
    for pwd in test_passwords:
        is_valid, error = validate_password_strength(pwd)
        print(f"\nPassword: {pwd}")
        print(f"Valid: {is_valid}")
        if error:
            print(f"Error: {error}")
        
        score_info = check_password_strength_score(pwd)
        print(f"Strength: {score_info['strength']} (Score: {score_info['score']}/4)")
        if score_info['feedback']:
            print(f"Feedback: {', '.join(score_info['feedback'])}")
