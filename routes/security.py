# routes/security.py

import re
import time
import random
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Message
from extensions import mail
from db import get_db_connection

security_bp = Blueprint("security", __name__, url_prefix="/security")


# =========================
# Helpers
# =========================
def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))


def generate_otp() -> str:
    return f"{random.randint(100000, 999999)}"


# =========================
# SECURITY HOME
# =========================
@security_bp.route("/", endpoint="security_home")
@login_required
def security_home():
    return render_template("account/security.html")


# =========================
# CHANGE USERNAME
# =========================
@security_bp.route("/username", methods=["GET", "POST"], endpoint="change_username")
@login_required
def change_username():

    if request.method == "POST":
        new_username = (request.form.get("username") or "").strip()

        if not new_username:
            flash("Username required.", "danger")
            return redirect(url_for("security.change_username"))

        if len(new_username) < 3:
            flash("Username must be at least 3 characters.", "danger")
            return redirect(url_for("security.change_username"))

        conn = get_db_connection()

        exists = conn.execute(
            "SELECT 1 FROM users WHERE username=? AND id!=?",
            (new_username, current_user.id),
        ).fetchone()

        if exists:
            conn.close()
            flash("Username already taken.", "danger")
            return redirect(url_for("security.change_username"))

        conn.execute(
            "UPDATE users SET username=? WHERE id=?",
            (new_username, current_user.id),
        )
        conn.commit()
        conn.close()

        flash("Username updated ✅", "success")
        return redirect(url_for("security.security_home"))

    return render_template("account/change_username.html")


# =========================
# CHANGE PHONE
# =========================
@security_bp.route("/phone", methods=["GET", "POST"], endpoint="change_phone")
@login_required
def change_phone():

    if request.method == "POST":
        phone = (request.form.get("phone") or "").strip()

        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET phone=? WHERE id=?",
            (phone, current_user.id),
        )
        conn.commit()
        conn.close()

        flash("Phone updated ✅", "success")
        return redirect(url_for("security.security_home"))

    return render_template("account/change_phone.html")


# =========================
# CHANGE PASSWORD
# =========================
@security_bp.route("/password", methods=["GET", "POST"], endpoint="change_password")
@login_required
def change_password():

    if request.method == "POST":

        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm_pw = request.form.get("confirm_password") or ""

        if not current_pw or not new_pw or not confirm_pw:
            flash("Fill all fields.", "danger")
            return redirect(url_for("security.change_password"))

        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("security.change_password"))

        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("security.change_password"))

        conn = get_db_connection()

        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?",
            (current_user.id,),
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], current_pw):
            conn.close()
            flash("Current password incorrect.", "danger")
            return redirect(url_for("security.change_password"))

        new_hash = generate_password_hash(new_pw, method="pbkdf2:sha256")

        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (new_hash, current_user.id),
        )
        conn.commit()
        conn.close()

        flash("Password updated ✅", "success")
        return redirect(url_for("security.security_home"))

    return render_template("account/change_password.html")


# =========================
# CANCEL EMAIL CHANGE
# =========================
@security_bp.route("/email/cancel")
@login_required
def cancel_email_change():
    session.pop("email_change_step", None)
    session.pop("pending_email", None)
    session.pop("email_otp", None)
    session.pop("email_otp_expires", None)

    flash("Email change cancelled.", "info")
    return redirect(url_for("security.security_home"))


# =========================
# CHANGE EMAIL WITH OTP
# =========================
@security_bp.route("/email", methods=["GET", "POST"], endpoint="change_email")
@login_required
def change_email():

    step = session.get("email_change_step", 1)

    if request.method == "POST":

        action = request.form.get("action")

        # ======================
        # SEND / RESEND OTP
        # ======================
        if action == "send_otp":

            new_email = (request.form.get("email") or "").strip().lower()

            # if resend
            if not new_email:
                new_email = session.get("pending_email")

            if not is_valid_email(new_email):
                flash("Invalid email format.", "danger")
                return redirect(url_for("security.change_email"))

            conn = get_db_connection()

            exists = conn.execute(
                "SELECT 1 FROM users WHERE email=? AND id!=?",
                (new_email, current_user.id),
            ).fetchone()

            conn.close()

            if exists:
                flash("Email already in use.", "danger")
                return redirect(url_for("security.change_email"))

            otp = generate_otp()

            session["email_change_step"] = 2
            session["pending_email"] = new_email
            session["email_otp"] = otp
            session["email_otp_expires"] = int(time.time()) + 600  # 10 min

            msg = Message(
                subject="Farmer Market OTP Verification",
                recipients=[new_email],
            )

            msg.body = f"""
Hello,

Your OTP code is: {otp}

This code expires in 10 minutes.

If you did not request this, please ignore this email.
"""

            try:
                mail.send(msg)
                flash("OTP sent to your new email.", "info")
            except Exception:
                flash("Failed to send OTP email.", "danger")

            return redirect(url_for("security.change_email"))

        # ======================
        # VERIFY OTP
        # ======================
        if action == "verify_otp":

            user_otp = request.form.get("otp", "").strip()
            real_otp = session.get("email_otp")
            expires = session.get("email_otp_expires")
            pending_email = session.get("pending_email")

            if not real_otp or not pending_email:
                flash("No pending email change.", "danger")
                return redirect(url_for("security.change_email"))

            if not expires or int(time.time()) > int(expires):
                session.pop("email_change_step", None)
                session.pop("pending_email", None)
                session.pop("email_otp", None)
                session.pop("email_otp_expires", None)
                flash("OTP expired. Please resend.", "danger")
                return redirect(url_for("security.change_email"))

            if user_otp != real_otp:
                flash("Invalid OTP.", "danger")
                return redirect(url_for("security.change_email"))

            conn = get_db_connection()

            conn.execute(
                "UPDATE users SET email=? WHERE id=?",
                (pending_email, current_user.id),
            )
            conn.commit()
            conn.close()

            session.pop("email_change_step", None)
            session.pop("pending_email", None)
            session.pop("email_otp", None)
            session.pop("email_otp_expires", None)

            flash("Email updated successfully ✅", "success")
            return redirect(url_for("security.security_home"))

    return render_template("account/change_email.html", step=step)