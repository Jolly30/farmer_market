# app.py

import os
from flask import Flask
from flask_login import LoginManager

from db import get_db_connection
from extensions import mail, socketio

# Blueprints
from routes.public import public_bp
from routes.auth import auth_bp
from routes.buyer import buyer_bp
from routes.seller import seller_bp
from routes.admin import admin_bp
from routes.profile import profile_bp
from routes.chat import chat_bp
from routes.security import security_bp
from routes.test_mail import test_bp
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev_secret_key_change_me")

# =========================
# MAIL CONFIG (Gmail App Password)
# =========================
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
# MAIL CONFIG (TEMP HARD CODE)
app.config["MAIL_USERNAME"] = "farmnet.noreply@gmail.com"
app.config["MAIL_PASSWORD"] = "lymcidmtkozlnmro"
app.config["MAIL_DEFAULT_SENDER"] = "farmnet.noreply@gmail.com"
# Init extensions
mail.init_app(app)
socketio.init_app(app)

# =========================
# Login Manager
# =========================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()

    if not row:
        return None

    class SimpleUser:
        def __init__(self, r):
            self.id = r["id"]
            for k in r.keys():
                setattr(self, k, r[k])

        def get_id(self):
            return str(self.id)

        @property
        def is_authenticated(self):
            return True

        @property
        def is_active(self):
            return True

        @property
        def is_anonymous(self):
            return False

    return SimpleUser(row)


# =========================
# Register Blueprints
# =========================
app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(buyer_bp)
app.register_blueprint(seller_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(security_bp)
app.register_blueprint(test_bp)


# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)