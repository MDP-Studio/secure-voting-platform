from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, Candidate, Vote
from datetime import datetime
import hashlib

main = Blueprint('main', __name__)

@main.route('/')
def index():
    return redirect(url_for('auth.login'))

@main.route('/dashboard')
@login_required
def dashboard():
    candidates = Candidate.query.all()
    return render_template('dashboard.html', 
                         candidates=candidates, 
                         user=current_user)

@main.route('/vote', methods=['POST'])
@login_required
def vote():
    if current_user.has_voted:
        flash('You have already voted!')
        return redirect(url_for('main.dashboard'))
    
    candidate_id = request.form.get('candidate_id')
    candidate = Candidate.query.get(candidate_id)
    
    if not candidate:
        flash('Invalid candidate selected')
        return redirect(url_for('main.dashboard'))
    
    # Create vote record
    vote = Vote(
        user_id=current_user.id,
        candidate_id=candidate.id,
        position=candidate.position
    )
    
    # Create vote hash for integrity
    vote_data = f"{current_user.id}{candidate.id}{datetime.utcnow().timestamp()}"
    vote.vote_hash = hashlib.sha256(vote_data.encode()).hexdigest()
    
    # Mark user as voted
    current_user.has_voted = True
    
    db.session.add(vote)
    db.session.commit()
    
    flash('Vote cast successfully!')
    return redirect(url_for('main.dashboard'))

@main.route('/results')
@login_required
def results():
    if not current_user.is_admin:
        flash('Access denied')
        return redirect(url_for('main.dashboard'))
    
    # Basic vote counting
    votes = Vote.query.all()
    results = {}
    
    for vote in votes:
        candidate = Candidate.query.get(vote.candidate_id)
        if candidate.name not in results:
            results[candidate.name] = 0
        results[candidate.name] += 1
    
    return render_template('results.html', results=results)
