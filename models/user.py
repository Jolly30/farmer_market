# models/user.py
from dataclasses import dataclass
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db_connection

@dataclass
class User:
    id: int
    username: str
    email: str
    password_hash: str
    role: str
    seller_status: str
    active_mode: str
    is_admin: int  # ✅ ADD THIS

    # Flask-Login required properties/methods:
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


def row_to_user(row) -> Optional[User]:
    if not row:
        return None
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        seller_status=row["seller_status"],
        active_mode=row["active_mode"],
        is_admin=row["is_admin"] if "is_admin" in row.keys() else 0,  # ✅ SAFE
    )


def get_user_by_id(user_id: int) -> Optional[User]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row_to_user(row)


def get_user_by_email(email: str) -> Optional[User]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row_to_user(row)


def create_user(username: str, email: str, password: str) -> int:
    password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    conn = get_db_connection()
    cur = conn.execute(
        """
        INSERT INTO users (username, email, password_hash, role, seller_status, active_mode, is_admin)
        VALUES (?, ?, ?, 'user', 'none', 'buyer', 0)
        """,
        (username, email, password_hash),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)