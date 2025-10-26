def test_one_vote_per_user(client, runner, app):
    # login as voter1
    rv = client.post('/login', data={'username': 'voter1', 'password': 'VoterSecurePass123!'}, follow_redirects=True)
    assert b'Welcome, voter1' in rv.data

    # cast a vote
    candidate = None
    from app.models import Candidate
    # Query requires application context
    with app.app_context():
        candidate = Candidate.query.first()
    assert candidate is not None

    rv = client.post('/vote', data={'candidate_id': candidate.id}, follow_redirects=True)
    assert b'Vote cast successfully!' in rv.data

    # try voting again
    rv2 = client.post('/vote', data={'candidate_id': candidate.id}, follow_redirects=True)
    assert b'You have already voted' in rv2.data or b'Duplicate vote detected' in rv2.data
