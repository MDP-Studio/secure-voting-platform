"""
Unit tests for the test voter generator functionality.
These are simpler tests that can run independently.
"""

import sys
import os
import unittest
from datetime import date

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.generate_test_voters import get_test_voters, get_test_voter_count, TEST_VOTERS


class TestVoterGeneratorUnit(unittest.TestCase):
    """Unit tests for the test voter data generator."""

    def test_generates_correct_number_of_voters(self):
        """Test that exactly 100 test voters are generated."""
        voters = get_test_voters()
        self.assertEqual(len(voters), 100)
        self.assertEqual(get_test_voter_count(), 100)

    def test_voter_data_structure(self):
        """Test that each voter has all required fields."""
        voters = get_test_voters()
        required_fields = [
            'username', 'email', 'password', 'full_name', 'date_of_birth',
            'address_line1', 'suburb', 'state', 'postcode',
            'driver_license_number', 'roll_number'
        ]
        
        for voter in voters:
            for field in required_fields:
                self.assertIn(field, voter, f"Missing field {field} in voter data")
                self.assertIsNotNone(voter[field], f"Field {field} is None")
                self.assertTrue(str(voter[field]).strip(), f"Field {field} is empty")

    def test_unique_usernames(self):
        """Test that all usernames are unique."""
        voters = get_test_voters()
        usernames = [voter['username'] for voter in voters]
        self.assertEqual(len(usernames), len(set(usernames)), "Duplicate usernames found")

    def test_unique_emails(self):
        """Test that all emails are unique."""
        voters = get_test_voters()
        emails = [voter['email'] for voter in voters]
        self.assertEqual(len(emails), len(set(emails)), "Duplicate emails found")

    def test_unique_driver_licenses(self):
        """Test that all driver's license numbers are unique."""
        voters = get_test_voters()
        dl_numbers = [voter['driver_license_number'] for voter in voters]
        self.assertEqual(len(dl_numbers), len(set(dl_numbers)), "Duplicate driver's license numbers found")

    def test_unique_roll_numbers(self):
        """Test that all electoral roll numbers are unique."""
        voters = get_test_voters()
        roll_numbers = [voter['roll_number'] for voter in voters]
        self.assertEqual(len(roll_numbers), len(set(roll_numbers)), "Duplicate roll numbers found")

    def test_username_format(self):
        """Test that usernames follow the expected format."""
        voters = get_test_voters()
        for i, voter in enumerate(voters):
            expected_username = f"testvoter{i+1:03d}"
            self.assertEqual(voter['username'], expected_username, f"Username format incorrect: {voter['username']}")

    def test_email_format(self):
        """Test that emails have the correct domain."""
        voters = get_test_voters()
        for voter in voters:
            self.assertTrue(voter['email'].endswith('@testvoters.com'), f"Email domain incorrect: {voter['email']}")

    def test_password_consistency(self):
        """Test that all test voters have the same password."""
        voters = get_test_voters()
        for voter in voters:
            self.assertEqual(voter['password'], 'testpass123', "Test voter password is not consistent")

    def test_roll_number_format(self):
        """Test that roll numbers follow the expected format."""
        voters = get_test_voters()
        for i, voter in enumerate(voters):
            expected_roll = f"ER-{1000 + i + 1:04d}"
            self.assertEqual(voter['roll_number'], expected_roll, f"Roll number format incorrect: {voter['roll_number']}")

    def test_valid_australian_locations(self):
        """Test that all addresses use valid Australian locations."""
        voters = get_test_voters()
        valid_states = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'ACT', 'NT', 'TAS']
        
        for voter in voters:
            self.assertIn(voter['state'], valid_states, f"Invalid state: {voter['state']}")
            self.assertEqual(len(voter['postcode']), 4, f"Invalid postcode length: {voter['postcode']}")
            self.assertTrue(voter['postcode'].isdigit(), f"Postcode should be numeric: {voter['postcode']}")

    def test_date_of_birth_format(self):
        """Test that date of birth is a valid date object."""
        voters = get_test_voters()
        for voter in voters:
            self.assertIsInstance(voter['date_of_birth'], date, "Date of birth should be a date object")
            
            # Check age range (should be between 18 and 80)
            from datetime import date as today_date
            current_year = today_date.today().year
            birth_year = voter['date_of_birth'].year
            age = current_year - birth_year
            self.assertGreaterEqual(age, 18, f"Voter too young: {age} years old")
            self.assertLessEqual(age, 81, f"Voter age seems unrealistic: {age} years old")

    def test_driver_license_format(self):
        """Test that driver's license numbers follow expected format."""
        voters = get_test_voters()
        for voter in voters:
            dl = voter['driver_license_number']
            self.assertEqual(len(dl), 8, f"Driver's license should be 8 characters: {dl}")
            self.assertTrue(dl[:2].isalpha(), f"First 2 chars should be letters: {dl}")
            self.assertTrue(dl[2:].isdigit(), f"Last 6 chars should be digits: {dl}")

    def test_realistic_names(self):
        """Test that generated names are realistic (not empty, have both first and last name)."""
        voters = get_test_voters()
        for voter in voters:
            full_name = voter['full_name']
            name_parts = full_name.split()
            self.assertGreaterEqual(len(name_parts), 2, f"Name should have at least first and last name: {full_name}")
            
            # Check that name parts are not empty
            for part in name_parts:
                self.assertTrue(part.strip(), f"Name part is empty in: {full_name}")

    def test_address_completeness(self):
        """Test that addresses have all required components."""
        voters = get_test_voters()
        for voter in voters:
            # Address line should have street number and name
            address = voter['address_line1']
            self.assertTrue(address.strip(), "Address line 1 should not be empty")
            
            # Should contain both number and street name
            parts = address.split()
            self.assertGreaterEqual(len(parts), 2, f"Address should have number and street: {address}")
            
            # Suburb should not be empty
            self.assertTrue(voter['suburb'].strip(), "Suburb should not be empty")


class TestVoterGeneratorConsistency(unittest.TestCase):
    """Test that the generator produces consistent results."""

    def test_consistent_generation(self):
        """Test that multiple calls return the same data."""
        voters1 = get_test_voters()
        voters2 = get_test_voters()
        
        self.assertEqual(len(voters1), len(voters2))
        
        for i, (v1, v2) in enumerate(zip(voters1, voters2)):
            self.assertEqual(v1['username'], v2['username'], f"Username mismatch at index {i}")
            self.assertEqual(v1['email'], v2['email'], f"Email mismatch at index {i}")
            self.assertEqual(v1['full_name'], v2['full_name'], f"Name mismatch at index {i}")

    def test_constant_test_voters_list(self):
        """Test that the TEST_VOTERS constant is properly populated."""
        self.assertEqual(len(TEST_VOTERS), 100)
        self.assertEqual(TEST_VOTERS, get_test_voters())


if __name__ == '__main__':
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestVoterGeneratorUnit))
    suite.addTests(loader.loadTestsFromTestCase(TestVoterGeneratorConsistency))
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print(f"\nTests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    # Exit with appropriate code
    exit_code = 0 if result.wasSuccessful() else 1
    print(f"\nTest result: {'PASSED' if result.wasSuccessful() else 'FAILED'}")
    exit(exit_code)