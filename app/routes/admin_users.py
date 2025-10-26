# app/routes/admin_users.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import User, ElectoralRoll
from app import db
from functools import wraps

admin_bp = Blueprint('admin_users', __name__, url_prefix="/admin")

def admin_only(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("Access denied: Admin only.")
            return redirect(url_for("main.dashboard"))
        return fn(*args, **kwargs)
    return wrapped

def get_safe_page_limit(request_limit, max_limit=40):
    """
    Safely parse and validate page limit from request with multiple security layers.
    
    CRITICAL SECURITY FUNCTION: Prevents DoS attacks via excessive page sizes.
    
    Security measures:
    - Hard maximum limit (ABSOLUTE - cannot be bypassed by any client manipulation)
    - Multiple validation layers
    - Logging of potential attacks
    - Safe fallback values for all edge cases
    """
    # Absolute maximum - this is the hard security boundary
    ABSOLUTE_MAX_LIMIT = 40
    
    try:
        # Parse the request limit
        if request_limit is None or request_limit == '':
            return 20  # Default safe value
        
        # Convert to integer with validation
        try:
            requested_limit = int(request_limit)
        except (ValueError, TypeError):
            # Invalid input - potential attack or error
            from flask import current_app
            current_app.logger.warning(
                f"Invalid pagination limit received: {repr(request_limit)} - using default"
            )
            return 20
        
        # Apply multiple security checks
        if requested_limit < 1:
            # Negative or zero values - invalid
            return 10  # Minimum safe value
        
        if requested_limit > ABSOLUTE_MAX_LIMIT:
            # Attempted to exceed absolute maximum - log security event
            from flask import current_app, request as flask_request
            client_ip = flask_request.environ.get('HTTP_X_FORWARDED_FOR', flask_request.remote_addr)
            current_app.logger.warning(
                f"SECURITY: Client {client_ip} attempted to request {requested_limit} records "
                f"(exceeds maximum {ABSOLUTE_MAX_LIMIT}). Request blocked."
            )
            return ABSOLUTE_MAX_LIMIT  # Force to maximum
        
        # Also enforce the passed max_limit parameter (should not exceed absolute max)
        effective_max = min(max_limit, ABSOLUTE_MAX_LIMIT)
        
        # Return the safe, validated limit
        return min(requested_limit, effective_max)
        
    except Exception as e:
        # Catch-all for any unexpected errors
        from flask import current_app
        current_app.logger.error(f"Error in pagination limit validation: {e}")
        return 20  # Safe default

@admin_bp.route("/users")
@login_required
@admin_only
def manage_users():
    """
    Display paginated list of all users with server-enforced pagination limits.
    Maximum 40 records per page to prevent service overload.
    """
    # Get pagination parameters with strict server-side validation
    page = request.args.get('page', 1, type=int)
    per_page = get_safe_page_limit(request.args.get('per_page'), max_limit=40)
    
    # Get category filter (default to 'all')
    category = request.args.get('category', 'all')
    
    # Base query for all users (not just specific statuses)
    query = User.query
    
    # Apply category filter
    if category == 'pending':
        query = query.filter_by(account_status="pending")
    elif category == 'approved':
        query = query.filter_by(account_status="approved") 
    elif category == 'rejected':
        query = query.filter_by(account_status="rejected")
    # 'all' shows all users
    
    # Order by creation date (newest first)
    query = query.order_by(User.created_at.desc())
    
    # Apply pagination with hard server-side limits
    users = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False,
        max_per_page=40  # Absolute maximum - cannot be bypassed
    )
    
    # Get counts for each category (for display)
    pending_count = User.query.filter_by(account_status="pending").count()
    approved_count = User.query.filter_by(account_status="approved").count()
    rejected_count = User.query.filter_by(account_status="rejected").count()
    
    return render_template("admin_users.html",
                           users=users,
                           per_page=per_page,
                           category=category,
                           pending_count=pending_count,
                           approved_count=approved_count,
                           rejected_count=rejected_count)

@admin_bp.route("/users/approve/<int:user_id>", methods=["POST"])
@login_required
@admin_only
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.account_status = "approved"
    # Backwards-compatible: some code refers to user.status; set it too.
    user.status = "active"
    # If the user has an electoral roll entry, mark it active and verified so
    # the user becomes eligible to vote after admin approval.
    enrol = getattr(user, 'enrolment', None)
    if enrol:
        enrol.status = 'active'
        enrol.verified = True
    db.session.commit()
    flash(f"✅ User '{user.username}' approved.")
    return redirect(url_for("admin_users.manage_users"))

@admin_bp.route("/users/reject/<int:user_id>", methods=["POST"])
@login_required
@admin_only
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    user.account_status = "rejected"
    user.status = "rejected"
    db.session.commit()
    flash(f"❌ User '{user.username}' rejected.")
    return redirect(url_for("admin_users.manage_users"))

@admin_bp.route("/voters")
@login_required
@admin_only
def manage_voters():
    """
    Display paginated list of all voters with electoral roll information.
    Enforces maximum 40 records per page for security.
    """
    # Get pagination parameters with security limits
    page = request.args.get('page', 1, type=int)
    per_page = get_safe_page_limit(request.args.get('per_page'), max_limit=40)
    
    # Get search/filter parameters
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'all')
    
    # Base query: join User with ElectoralRoll and filter by voter role
    query = db.session.query(User, ElectoralRoll).join(
        ElectoralRoll, User.id == ElectoralRoll.user_id, isouter=True
    ).join(User.role).filter(
        User.role.has(name='voter')
    )
    
    # Apply search filter (secure against SQL injection via SQLAlchemy)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                ElectoralRoll.full_name.ilike(search_pattern),
                ElectoralRoll.roll_number.ilike(search_pattern)
            )
        )
    
    # Apply status filter
    if status_filter != 'all':
        if status_filter == 'active':
            query = query.filter(User.account_status == 'approved')
        elif status_filter == 'pending':
            query = query.filter(User.account_status == 'pending')
        elif status_filter == 'rejected':
            query = query.filter(User.account_status == 'rejected')
    
    # Order by creation date (newest first)
    query = query.order_by(User.created_at.desc())
    
    # Paginate with enforced limits
    voters = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False,
        max_per_page=40  # Hard limit - cannot be overridden
    )
    
    return render_template("admin_voters.html",
                           voters=voters,
                           search=search,
                           status_filter=status_filter,
                           per_page=per_page)

@admin_bp.route("/candidates")
@login_required
@admin_only
def manage_candidates():
    """
    Display paginated list of all candidates with security-enforced pagination.
    Maximum 40 records per page to prevent service overload.
    """
    from app.models import Candidate
    
    # Get pagination parameters with strict server-side validation
    page = request.args.get('page', 1, type=int)
    per_page = get_safe_page_limit(request.args.get('per_page'), max_limit=40)
    
    # Get search/filter parameters
    search = request.args.get('search', '').strip()
    party_filter = request.args.get('party', 'all')
    
    # Base query with joins for region information
    query = Candidate.query.join(Candidate.region)
    
    # Apply search filter (secure against SQL injection via SQLAlchemy)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Candidate.name.ilike(search_pattern),
                Candidate.party.ilike(search_pattern),
                Candidate.position.ilike(search_pattern),
                Candidate.region.has(name=search_pattern)
            )
        )
    
    # Apply party filter
    if party_filter != 'all':
        query = query.filter(Candidate.party == party_filter)
    
    # Order by name
    query = query.order_by(Candidate.name)
    
    # Apply pagination with hard server-side limits
    candidates = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False,
        max_per_page=40  # Absolute maximum - cannot be bypassed
    )
    
    # Get unique parties for filter dropdown
    parties = db.session.query(Candidate.party).distinct().filter(
        Candidate.party.isnot(None)
    ).order_by(Candidate.party).all()
    parties = [p[0] for p in parties if p[0]]  # Extract party names
    
    return render_template("admin_candidates.html",
                           candidates=candidates,
                           search=search,
                           party_filter=party_filter,
                           parties=parties,
                           per_page=per_page)
