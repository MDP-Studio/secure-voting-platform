"""
Test Voter Data Generator

This module provides realistic test data for generating 100 test voters
for testing the secure voting system. It includes diverse names, addresses,
and other voter information to simulate a real electoral environment.

Usage:
    from app.generate_test_voters import TEST_VOTERS
    
    # TEST_VOTERS contains a list of dictionaries with voter data
"""

from datetime import datetime, date
import random

# Pool of realistic first names (diverse backgrounds)
FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Nancy", "Daniel", "Lisa",
    "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra", "Donald", "Donna",
    "Steven", "Carol", "Paul", "Ruth", "Andrew", "Sharon", "Joshua", "Michelle",
    "Kenneth", "Laura", "Kevin", "Sarah", "Brian", "Kimberly", "George", "Deborah",
    "Edward", "Dorothy", "Ronald", "Lisa", "Timothy", "Nancy", "Jason", "Karen",
    "Jeffrey", "Betty", "Ryan", "Helen", "Jacob", "Sandra", "Gary", "Donna",
    "Nicholas", "Carol", "Eric", "Ruth", "Jonathan", "Sharon", "Stephen", "Michelle",
    "Larry", "Laura", "Justin", "Sarah", "Scott", "Kimberly", "Brandon", "Deborah",
    "Benjamin", "Dorothy", "Samuel", "Amy", "Gregory", "Angela", "Alexander", "Ashley",
    "Patrick", "Brenda", "Jack", "Emma", "Dennis", "Olivia", "Jerry", "Cynthia",
    "Tyler", "Marie", "Aaron", "Janet", "Jose", "Catherine", "Henry", "Frances",
    "Adam", "Christine", "Douglas", "Samantha", "Nathan", "Debra", "Peter", "Rachel",
    "Zachary", "Carolyn", "Kyle", "Janet", "Walter", "Virginia", "Harold", "Maria",
    "Carl", "Heather", "Arthur", "Diane", "Ryan", "Julie", "Roger", "Joyce",
    "Joe", "Victoria", "Juan", "Kelly", "Jack", "Christina", "Albert", "Joan",
    "Wayne", "Evelyn", "Ralph", "Lauren", "Mason", "Judith", "Roy", "Megan",
    "Eugene", "Cheryl", "Louis", "Andrea", "Philip", "Hannah", "Bobby", "Jacqueline",
    "Johnny", "Martha", "Terry", "Gloria", "Sean", "Teresa", "Billy", "Sara"
]

# Pool of realistic last names (diverse backgrounds)
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker",
    "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales", "Murphy",
    "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey",
    "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson",
    "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza",
    "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers",
    "Long", "Ross", "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell",
    "Sullivan", "Bell", "Coleman", "Butler", "Henderson", "Barnes", "Gonzales", "Fisher",
    "Vasquez", "Simmons", "Romero", "Jordan", "Patterson", "Alexander", "Hamilton", "Graham",
    "Reynolds", "Griffin", "Wallace", "Moreno", "West", "Cole", "Hayes", "Bryant",
    "Herrera", "Gibson", "Ellis", "Tran", "Medina", "Aguilar", "Stevens", "Murray",
    "Ford", "Castro", "Marshall", "Owens", "Harrison", "Fernandez", "McDonald", "Woods",
    "Washington", "Kennedy", "Wells", "Vargas", "Henry", "Chen", "Freeman", "Webb",
    "Tucker", "Guzman", "Burns", "Crawford", "Olson", "Simpson", "Porter", "Hunter"
]

# Australian suburbs and states for realistic addresses
AUSTRALIAN_LOCATIONS = [
    {"suburb": "Sydney", "state": "NSW", "postcode": "2000"},
    {"suburb": "Melbourne", "state": "VIC", "postcode": "3000"},
    {"suburb": "Brisbane", "state": "QLD", "postcode": "4000"},
    {"suburb": "Perth", "state": "WA", "postcode": "6000"},
    {"suburb": "Adelaide", "state": "SA", "postcode": "5000"},
    {"suburb": "Canberra", "state": "ACT", "postcode": "2600"},
    {"suburb": "Darwin", "state": "NT", "postcode": "0800"},
    {"suburb": "Hobart", "state": "TAS", "postcode": "7000"},
    {"suburb": "Parramatta", "state": "NSW", "postcode": "2150"},
    {"suburb": "Blacktown", "state": "NSW", "postcode": "2148"},
    {"suburb": "Newcastle", "state": "NSW", "postcode": "2300"},
    {"suburb": "Wollongong", "state": "NSW", "postcode": "2500"},
    {"suburb": "Geelong", "state": "VIC", "postcode": "3220"},
    {"suburb": "Ballarat", "state": "VIC", "postcode": "3350"},
    {"suburb": "Bendigo", "state": "VIC", "postcode": "3550"},
    {"suburb": "Gold Coast", "state": "QLD", "postcode": "4217"},
    {"suburb": "Townsville", "state": "QLD", "postcode": "4810"},
    {"suburb": "Cairns", "state": "QLD", "postcode": "4870"},
    {"suburb": "Toowoomba", "state": "QLD", "postcode": "4350"},
    {"suburb": "Rockingham", "state": "WA", "postcode": "6168"},
    {"suburb": "Mandurah", "state": "WA", "postcode": "6210"},
    {"suburb": "Bunbury", "state": "WA", "postcode": "6230"},
    {"suburb": "Mount Gambier", "state": "SA", "postcode": "5290"},
    {"suburb": "Whyalla", "state": "SA", "postcode": "5600"},
    {"suburb": "Port Augusta", "state": "SA", "postcode": "5700"}
]

# Street names for addresses
STREET_NAMES = [
    "King Street", "Queen Street", "George Street", "Elizabeth Street", "Collins Street",
    "Bourke Street", "Flinders Street", "Spencer Street", "Swanston Street", "Russell Street",
    "William Street", "High Street", "Main Street", "Church Street", "Park Street",
    "Victoria Street", "Albert Street", "James Street", "Smith Street", "Brown Street",
    "Jones Street", "Miller Street", "Davis Street", "Wilson Street", "Moore Street",
    "Taylor Street", "Anderson Street", "Thomas Street", "Jackson Street", "White Street",
    "Harris Street", "Martin Street", "Thompson Street", "Garcia Street", "Martinez Street",
    "Robinson Street", "Clark Street", "Rodriguez Street", "Lewis Street", "Lee Street",
    "Walker Street", "Hall Street", "Allen Street", "Young Street", "Hernandez Street",
    "King Avenue", "Queen Avenue", "George Avenue", "Elizabeth Avenue", "Collins Avenue"
]

def generate_random_voter_data(index):
    """Generate a single voter's data with realistic information."""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    location = random.choice(AUSTRALIAN_LOCATIONS)
    street_address = f"{random.randint(1, 999)} {random.choice(STREET_NAMES)}"
    
    # Generate birth date (ages 18-80)
    birth_year = random.randint(1944, 2006)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)  # Safe day for all months
    
    # Generate driver's license number (format: 2 letters + 6 digits)
    dl_letters = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))
    dl_numbers = ''.join(random.choices('0123456789', k=6))
    driver_license = f"{dl_letters}{dl_numbers}"
    
    return {
        "username": f"testvoter{index:03d}",  # testvoter001, testvoter002, etc.
        "email": f"{first_name.lower()}.{last_name.lower()}{index}@testvoters.com",
        "password": "TestPass@123!",  # Strong password for all test users (12+ chars, upper, lower, special)
        "full_name": f"{first_name} {last_name}",
        "date_of_birth": date(birth_year, birth_month, birth_day),
        "address_line1": street_address,
        "suburb": location["suburb"],
        "state": location["state"],
        "postcode": location["postcode"],
        "driver_license_number": driver_license,
        "roll_number": f"ER-{1000 + index:04d}",  # ER-1001, ER-1002, etc.
    }

# Generate 110 test voters for development seeding
TEST_VOTERS = [generate_random_voter_data(i + 1) for i in range(110)]

def get_test_voters():
    """Return the list of test voter data."""
    return TEST_VOTERS

def get_test_voter_count():
    """Return the number of test voters available."""
    return len(TEST_VOTERS)

if __name__ == "__main__":
    # Print sample data when run as a script
    print(f"Generated {len(TEST_VOTERS)} test voters")
    print("\nSample voter data:")
    for i, voter in enumerate(TEST_VOTERS[:5]):  # Show first 5
        print(f"{i+1}. {voter['full_name']} ({voter['username']}) - {voter['email']}")
        print(f"   Address: {voter['address_line1']}, {voter['suburb']}, {voter['state']} {voter['postcode']}")
        print(f"   DOB: {voter['date_of_birth']}, DL: {voter['driver_license_number']}")
        print()