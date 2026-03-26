# routes/test_mail.py

from flask import Blueprint
from flask_mail import Message
from extensions import mail

test_bp = Blueprint("test_mail", __name__, url_prefix="/test-mail")


@test_bp.route("/")
def send_test_mail():
    try:
        msg = Message(
            subject="Test Email from Farmer Market",
            recipients=["your_real_email@gmail.com"],  # change to your email
        )

        msg.body = "This is a test email from your Farmer Market system."

        mail.send(msg)

        return "Email sent successfully ✅"

    except Exception as e:
        return f"Mail error ❌: {e}"