from app import create_app, db
from app.models import User, Candidate, Vote

app = create_app()

def init_database():
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Create admin user
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@voting.com', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
        
        # Create sample voter
        if not User.query.filter_by(username='voter1').first():
            voter1 = User(username='voter1', email='voter1@email.com', is_admin=False)
            voter1.set_password('password123')
            db.session.add(voter1)
        
        # Create sample candidates
        if Candidate.query.count() == 0:
            candidates = [
                Candidate(name='John Smith', party='Labor Party', position='House of Representatives', constituency='Sydney'),
                Candidate(name='Sarah Johnson', party='Liberal Party', position='House of Representatives', constituency='Sydney'),
                Candidate(name='Mike Brown', party='Greens', position='House of Representatives', constituency='Sydney'),
            ]
            db.session.add_all(candidates)
        
        db.session.commit()
        print("Database initialized successfully!")
        print("Admin credentials: username='admin', password='admin123'")
        print("Voter credentials: username='voter1', password='password123'")

if __name__ == '__main__':
    init_database()
