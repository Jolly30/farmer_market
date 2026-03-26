import re
import time
import random
from urllib.parse import urlparse

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from werkzeug.security import generate_password_hash

from models.user import get_user_by_email, verify_password
from db import get_db_connection
from extensions import mail

auth_bp = Blueprint("auth", __name__)


# ============================================================
# HELPERS
# ============================================================
def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))


def gen_otp() -> str:
    return f"{random.randint(100000, 999999)}"


def mail_sender() -> str:
    # fixes: "sender not configured"
    return (
        current_app.config.get("MAIL_DEFAULT_SENDER")
        or current_app.config.get("MAIL_USERNAME")
        or "no-reply@example.com"
    )


# ============================================================
# SIGNUP OTP SESSION HELPERS
# ============================================================
def clear_signup_session():
    session.pop("signup_username", None)
    session.pop("signup_email", None)
    session.pop("signup_password_hash", None)
    session.pop("signup_otp", None)
    session.pop("signup_otp_expires", None)


def send_signup_otp_email(to_email: str, username: str, otp: str, is_resend: bool = False):
    subject = "Farmer Market - Verify your email" if not is_resend else "Farmer Market - OTP (Resent)"

    msg = Message(
        subject=subject,
        sender=mail_sender(),
        recipients=[to_email],
    )

    msg.body = f"""Hello {username},

Your OTP code is: {otp}

This code expires in 10 minutes.

If you did not request this, please ignore this email.
"""
    mail.send(msg)


# ============================================================
# REGISTER UI (GET)
# ============================================================
@auth_bp.route("/register", methods=["GET"])
def register():
    # block admin from normal register page
    if current_user.is_authenticated and getattr(current_user, "is_admin", 0) == 1:
        return redirect(url_for("admin.dashboard"))

    return render_template("auth/register.html")


# ============================================================
# REGISTER: SEND OTP (AJAX)  /register/send-otp
# ============================================================
@auth_bp.route("/register/send-otp", methods=["POST"])
def register_send_otp():
    if current_user.is_authenticated and getattr(current_user, "is_admin", 0) == 1:
        return jsonify({"ok": False, "message": "Admins cannot register here."}), 403

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    if not username or not email or not password:
        return jsonify({"ok": False, "message": "Fill username, email, password first."}), 400

    if len(username) < 3:
        return jsonify({"ok": False, "message": "Username must be at least 3 characters."}), 400

    if not is_valid_email(email):
        return jsonify({"ok": False, "message": "Invalid email format."}), 400

    if len(password) < 6:
        return jsonify({"ok": False, "message": "Password must be at least 6 characters."}), 400

    # unique check
    conn = get_db_connection()
    u1 = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
    u2 = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if u1:
        return jsonify({"ok": False, "message": "Username already taken."}), 409
    if u2:
        return jsonify({"ok": False, "message": "Email already exists. Please login."}), 409

    otp = gen_otp()

    # store pending signup
    session["signup_username"] = username
    session["signup_email"] = email
    session["signup_password_hash"] = generate_password_hash(password, method="pbkdf2:sha256")
    session["signup_otp"] = otp
    session["signup_otp_expires"] = int(time.time()) + 600

    try:
        send_signup_otp_email(email, username, otp)
        return jsonify({"ok": True, "message": f"OTP sent to {email}."})
    except Exception as e:
        print("MAIL ERROR:", e)
        clear_signup_session()
        return jsonify({"ok": False, "message": "Failed to send OTP. Check mail settings."}), 500


# ============================================================
# REGISTER: SUBMIT (VERIFY OTP + CREATE USER + AUTO LOGIN)
# ============================================================
@auth_bp.route("/register/submit", methods=["POST"])
def register_submit():
    if current_user.is_authenticated and getattr(current_user, "is_admin", 0) == 1:
        return redirect(url_for("admin.dashboard"))

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    user_otp = (request.form.get("otp") or "").strip()

    if not username or not email or not password or not user_otp:
        flash("Please fill all fields (including OTP).", "danger")
        return redirect(url_for("auth.register"))

    # must have OTP session
    real_otp = session.get("signup_otp")
    expires = session.get("signup_otp_expires", 0)
    s_username = session.get("signup_username")
    s_email = session.get("signup_email")
    password_hash = session.get("signup_password_hash")

    if not (real_otp and s_username and s_email and password_hash):
        flash("Please click Send OTP first.", "warning")
        return redirect(url_for("auth.register"))

    # if changed username/email after sending otp
    if username != s_username or email != s_email:
        flash("You changed username/email after OTP. Please Send OTP again.", "warning")
        return redirect(url_for("auth.register"))

    if int(time.time()) > int(expires):
        clear_signup_session()
        flash("OTP expired. Please Send OTP again.", "danger")
        return redirect(url_for("auth.register"))

    if user_otp != str(real_otp):
        flash("Invalid OTP.", "danger")
        return redirect(url_for("auth.register"))

    # final unique check then insert
    conn = get_db_connection()
    u1 = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
    u2 = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()

    if u1 or u2:
        conn.close()
        clear_signup_session()
        flash("Username or email already used. Please register again.", "danger")
        return redirect(url_for("auth.register"))

    # ✅ create user as verified
    conn.execute(
        """
        INSERT INTO users (username, email, password_hash, email_verified, active_mode)
        VALUES (?, ?, ?, 1, 'buyer')
        """,
        (username, email, password_hash),
    )
    conn.commit()
    conn.close()

    # ✅ AUTO LOGIN after OTP success
    new_user = get_user_by_email(email)
    if new_user:
        login_user(new_user)

    clear_signup_session()
    flash("Account created ✅", "success")
    return redirect(url_for("public.categories"))


# ============================================================
# REGISTER: CANCEL
# ============================================================
@auth_bp.route("/register/cancel", methods=["POST"])
def register_cancel():
    clear_signup_session()
    flash("Registration cleared.", "secondary")
    return redirect(url_for("auth.register"))


# ============================================================
# FORGOT PASSWORD (EMAIL + OTP + NEW PASSWORD)
# URL: /password
# ============================================================
def clear_fp_session():
    session.pop("fp_step", None)
    session.pop("fp_email", None)
    session.pop("fp_otp", None)
    session.pop("fp_otp_expires", None)


def send_fp_otp_email(to_email: str, otp: str):
    msg = Message(
        subject="Farmer Market - Password Reset OTP",
        sender=mail_sender(),
        recipients=[to_email],
    )
    msg.body = f"""Hello,

Your OTP code is: {otp}

This code expires in 10 minutes.

If you did not request this, please ignore this email.
"""
    mail.send(msg)

@auth_bp.route("/password", methods=["GET", "POST"])
def forgot_password():

    # Keep user inputs (so they don't disappear)
    email = (request.form.get("email") or "").strip().lower() if request.method == "POST" else ""
    otp_input = (request.form.get("otp") or "").strip() if request.method == "POST" else ""

    if request.method == "POST":
        action = request.form.get("action")

        # ========================
        # CANCEL (CLEAR EVERYTHING)
        # ========================
        if action == "cancel":
            session.pop("fp_email", None)
            session.pop("fp_otp", None)
            session.pop("fp_expires", None)
            return redirect(url_for("auth.forgot_password"))

        # ========================
        # SEND OTP  (ONLY requires EMAIL)
        # ========================
        if action == "send_otp":

            if not email:
                flash("Please enter your email.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            if not is_valid_email(email):
                flash("Invalid email format.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            conn = get_db_connection()
            user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            conn.close()

            if not user:
                flash("Email not found.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            otp = gen_otp()
            session["fp_email"] = email
            session["fp_otp"] = otp
            session["fp_expires"] = int(time.time()) + 600  # 10 minutes

            try:
                msg = Message(
                    subject="Password Reset OTP",
                    sender=mail_sender(),
                    recipients=[email],
                )
                msg.body = f"Your OTP is: {otp}\n\nThis OTP expires in 10 minutes."
                mail.send(msg)

                flash("OTP sent ✅ Check your inbox/spam.", "info")

            except Exception as e:
                print("MAIL ERROR:", e)
                flash("Failed to send OTP email.", "danger")

            return render_template("auth/forgot_password.html", email=email, otp=otp_input)

        # ========================
        # RESET PASSWORD
        # ========================
        if action == "reset_password":

            new_pw = request.form.get("new_password") or ""
            confirm_pw = request.form.get("confirm_password") or ""

            if not session.get("fp_email") or not session.get("fp_otp"):
                flash("Please click Send OTP first.", "warning")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            if int(time.time()) > int(session.get("fp_expires", 0)):
                session.pop("fp_email", None)
                session.pop("fp_otp", None)
                session.pop("fp_expires", None)
                flash("OTP expired. Please send again.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            if otp_input != str(session.get("fp_otp")):
                flash("Invalid OTP.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            if len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            if new_pw != confirm_pw:
                flash("Passwords do not match.", "danger")
                return render_template("auth/forgot_password.html", email=email, otp=otp_input)

            new_hash = generate_password_hash(new_pw, method="pbkdf2:sha256")

            conn = get_db_connection()
            conn.execute("UPDATE users SET password_hash=? WHERE email=?", (new_hash, session["fp_email"]))
            conn.commit()
            conn.close()

            session.pop("fp_email", None)
            session.pop("fp_otp", None)
            session.pop("fp_expires", None)

            flash("Password reset successful ✅ Please login.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", email=email, otp=otp_input)

# ============================================================
# LOGIN
# ============================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get("next", "")

    if current_user.is_authenticated:
        if getattr(current_user, "is_admin", 0) == 1:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("public.categories"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        user = get_user_by_email(email)

        if not user or not verify_password(user, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login", next=next_page))

        
        # Admin protection (optional)
        if next_page.startswith("/admin"):
            if getattr(user, "is_admin", 0) != 1:
                flash("Invalid email or password.", "danger")
                return redirect(url_for("auth.login", next=next_page))
            login_user(user)
            parsed = urlparse(next_page)
            if parsed.netloc == "":
                return redirect(next_page)
            return redirect(url_for("admin.dashboard"))

        if getattr(user, "is_admin", 0) == 1:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login", next=next_page))

        login_user(user)

        # start as buyer
        conn = get_db_connection()
        conn.execute("UPDATE users SET active_mode='buyer' WHERE id=?", (user.id,))
        conn.commit()
        conn.close()

        flash("Logged in successfully.", "success")

        if next_page:
            parsed = urlparse(next_page)
            if parsed.netloc == "":
                return redirect(next_page)

        return redirect(url_for("public.categories"))

    return render_template("auth/login.html")


# ============================================================
# LOGOUT
# ============================================================
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("public.categories"))