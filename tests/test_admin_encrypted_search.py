"""Ensure randomized encrypted PII is never used as a SQL search key."""


def test_voter_search_uses_plaintext_identifiers_not_encrypted_name(client):
    assert client.post(
        '/login',
        data={'username': 'admin', 'password': 'Admin@123456!'},
    ).status_code == 302

    by_username = client.get('/admin/voters?search=voter1')
    assert by_username.status_code == 200
    assert b'voter1' in by_username.data

    by_encrypted_full_name = client.get('/admin/voters?search=Test+Voter')
    assert by_encrypted_full_name.status_code == 200
    assert b'No voters match your current search criteria.' in by_encrypted_full_name.data
    assert b'Search by username, email, or roll number' in by_encrypted_full_name.data
