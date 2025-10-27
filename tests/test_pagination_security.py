"""
Test pagination security for admin routes - UNIT TESTS ONLY

These tests verify the pagination limit functionality directly using the get_safe_page_limit function.
"""

import pytest
from app.routes.admin_users import get_safe_page_limit


class TestPaginationSecurity:
    """Test cases for pagination security features."""
    
    def test_get_safe_page_limit_normal_values(self):
        """Test normal valid values."""
        # Convert to string as the function expects string input from query params
        assert get_safe_page_limit('10') == 10
        assert get_safe_page_limit('20') == 20
        assert get_safe_page_limit('40') == 40
    
    def test_get_safe_page_limit_edge_cases(self):
        """Test edge cases."""
        assert get_safe_page_limit('1') == 1  # Minimum valid
        assert get_safe_page_limit('0') == 10  # Invalid zero
        assert get_safe_page_limit('-5') == 10  # Invalid negative


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


if __name__ == '__main__':
    pytest.main([__file__, '-v'])