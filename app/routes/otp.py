from flask import Blueprint, request, jsonify, session, current_app
from flask_mail import Message
from app import mail
from app.models import User
import random
import time
import re

otp_bp = Blueprint("otp", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@otp_bp.route("/send-otp", methods=["POST"])
def send_otp():
    """
    Generate a 6-digit OTP, save to session, and send via the user's email.
    - The frontend POSTs { username }.
    - The backend queries the database for that username → retrieves email → sends OTP.
    """
    username = request.form.get("username", "").strip()
    if not username:
        return jsonify({"success": False, "msg": "Missing username"}), 400

    # Look up user in DB
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "msg": "User not found"}), 404
    if not user.email or not EMAIL_RE.match(user.email):
        return jsonify({"success": False, "msg": "User email invalid or not set"}), 400

    # Generate OTP (6-digit, always zero-padded)
    code = f"{random.randint(0, 999999):06d}"
    session["otp_code"] = code
    session["otp_user"] = user.id
    session["otp_expires_at"] = time.time() + 300   # 5 minutes
    session["otp_attempts"] = 0

    # Prepare email message
    msg = Message(
        subject="CivicVote OTP Verification",
        recipients=[user.email],  # recipients must be a list
    )
    msg.body = (
        f"Dear {user.username},\n\n"
        f"Your One-Time Password (OTP) is: {code}\n\n"
        "Please enter this code on the CivicVote login page to continue.\n"
        "⚠️ This code will expire in 5 minutes. Do not share it with anyone.\n\n"
        "Best regards,\nCivicVote Security Team"
    )

    # Send email
    mail.send(msg)
    current_app.logger.info("OTP sent to %s for user=%s", user.email, user.username)

    # Mask the email in API response for privacy
    def mask(e):
        try:
            name, dom = e.split("@", 1)
            return (name[:2] + "****@" + dom) if len(name) >= 2 else ("*@" + dom)
        except Exception:
            return "***"

    return jsonify({"success": True, "msg": f"OTP sent to {mask(user.email)}"})


@otp_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    """
    Verify the OTP entered by the user.
    - The frontend POSTs { username, otp }.
    - Backend checks if OTP belongs to that user and matches the session.
    """
    username = request.form.get("username", "").strip()
    code = request.form.get("otp", "").strip()

    if not username or not code:
        return jsonify({"success": False, "msg": "Missing username or otp"}), 400

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "msg": "User not found"}), 404

    # Ensure OTP is linked to this user
    if session.get("otp_user") != user.id:
        return jsonify({"success": False, "msg": "OTP does not belong to this user"}), 400

    # Check OTP
    if code == session.get("otp_code"):
        # Clear OTP after successful verification
        session.pop("otp_code", None)
        session.pop("otp_user", None)
        return jsonify({"success": True, "msg": "OTP verified"})
    return jsonify({"success": False, "msg": "Invalid OTP"})
