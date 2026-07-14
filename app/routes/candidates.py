import logging
from flask import Blueprint, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.logging_service import record_audit_event
from app.models import Candidate, Election, Region
from app.utils.auth_decorators import roles_required

candidates = Blueprint('candidates', __name__)

# candidate management for delegates and managers
@candidates.route("/candidates/new", methods=["POST"])
@roles_required("delegate", "manager")
def create_candidate():
    name = (request.form.get("name") or "").strip()
    party = (request.form.get("party") or "").strip()
    position = (request.form.get("position") or "").strip()
    region_id_raw = request.form.get("region_id")
    election_id_raw = request.form.get("election_id")

    if not name or not position or not region_id_raw or not election_id_raw:
        flash("Name, position, region, and draft election are required.")
        return redirect(url_for("main.delegate_dashboard"))

    try:
        region_id = int(region_id_raw)
        election_id = int(election_id_raw)
    except ValueError:
        logging.getLogger(__name__).debug("Handled exception in app/routes/candidates.py", exc_info=True)
        flash("Invalid region.")
        return redirect(url_for("main.delegate_dashboard"))

    election = (
        db.session.query(Election)
        .filter(Election.id == election_id)
        .with_for_update()
        .first()
    )
    region = db.session.get(Region, region_id)
    if not election or election.status != "draft":
        flash("Candidates can only be added to a draft election.")
        return redirect(url_for("main.delegate_dashboard"))
    if not region:
        flash("Invalid region.")
        return redirect(url_for("main.delegate_dashboard"))
    enrolment = getattr(current_user, "enrolment", None)
    if (
        current_user.has_role("delegate")
        and not current_user.has_role("manager")
        and (not enrolment or enrolment.region_id != region_id)
    ):
        flash("Delegates can only add candidates in their region.")
        return redirect(url_for("main.delegate_dashboard"))

    c = Candidate(
        name=name,
        party=party or None,
        position=position,
        region_id=region_id,
        election_id=election.id,
    )
    db.session.add(c)
    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='candidate.create',
        target_type='candidate',
        target_id=c.id,
    )
    flash("Candidate created.")
    return redirect(url_for("main.delegate_dashboard"))

@candidates.route("/candidates/<int:candidate_id>/update", methods=["POST"])
@roles_required("delegate", "manager")
@login_required
def update_candidate(candidate_id):
    c = (
        db.session.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if c is None:
        abort(404)
    election = (
        db.session.query(Election)
        .filter(Election.id == c.election_id)
        .with_for_update()
        .first()
    )
    if election is None or election.status != "draft":
        flash("An election roster cannot be changed after voting opens.")
        return redirect(url_for("main.delegate_dashboard"))

    # Region guard: delegates can only edit candidates in their region
    if current_user.has_role("delegate") and not current_user.has_role("manager"):
        enrol = getattr(current_user, "enrolment", None)
        if not enrol or enrol.region_id != c.region_id:
            flash("Delegates can only edit candidates in their region.")
            return redirect(url_for("main.delegate_dashboard"))

    # simple update (you can replace with a proper edit form later)
    name = request.form.get("name")
    if name is not None:
        if not name.strip():
            flash("Candidate name is required.")
            return redirect(url_for("main.delegate_dashboard"))
        c.name = name.strip()
    party = request.form.get("party")
    if party is not None:
        c.party = party.strip() or None
    position = request.form.get("position")
    if position is not None:
        if not position.strip():
            flash("Candidate position is required.")
            return redirect(url_for("main.delegate_dashboard"))
        c.position = position.strip()
    region_id_str = request.form.get("region_id")
    if region_id_str is not None:
        try:
            new_region_id = int(region_id_str)
            enrolment = getattr(current_user, "enrolment", None)
            if (
                current_user.has_role("delegate")
                and not current_user.has_role("manager")
                and (not enrolment or enrolment.region_id != new_region_id)
            ):
                flash("Delegates can only move candidates within their region.")
                return redirect(url_for("main.delegate_dashboard"))
            if db.session.get(Region, new_region_id) is None:
                flash("Invalid region.")
                return redirect(url_for("main.delegate_dashboard"))
            c.region_id = new_region_id
        except ValueError:
            logging.getLogger(__name__).debug("Handled exception in app/routes/candidates.py", exc_info=True)
            flash("Invalid region.")
            return redirect(url_for("main.delegate_dashboard"))

    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='candidate.update',
        target_type='candidate',
        target_id=c.id,
    )
    flash("Candidate updated.")
    return redirect(url_for("main.delegate_dashboard"))

@candidates.route("/candidates/<int:candidate_id>/delete", methods=["POST"])
@roles_required("delegate", "manager")
@login_required
def delete_candidate(candidate_id):
    c = (
        db.session.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if c is None:
        abort(404)
    election = (
        db.session.query(Election)
        .filter(Election.id == c.election_id)
        .with_for_update()
        .first()
    )
    if election is None or election.status != "draft":
        flash("An election roster cannot be changed after voting opens.")
        return redirect(url_for("main.delegate_dashboard"))

    # Region guard: delegates can only delete candidates in their region
    if current_user.has_role("delegate") and not current_user.has_role("manager"):
        enrol = getattr(current_user, "enrolment", None)
        if not enrol or enrol.region_id != c.region_id:
            flash("Delegates can only delete candidates in their region.")
            return redirect(url_for("main.delegate_dashboard"))

    deleted_candidate_id = c.id
    db.session.delete(c)
    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='candidate.delete',
        target_type='candidate',
        target_id=deleted_candidate_id,
    )
    flash("Candidate deleted.")
    return redirect(url_for("main.delegate_dashboard"))
