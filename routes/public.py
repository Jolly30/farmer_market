# routes/public.py
from flask import Blueprint, render_template, request
from flask_login import current_user
from db import get_db_connection

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def categories():
    conn = get_db_connection()
    categories = conn.execute(
        "SELECT * FROM categories ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return render_template("public/categories.html", categories=categories)


@public_bp.route("/category/<int:category_id>")
def feed(category_id):
    conn = get_db_connection()

    category = conn.execute(
        "SELECT * FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()

    # ✅ search query from your form: name="q"
    q = request.args.get("q", "").strip()

    if q:
        like = f"%{q}%"
        products = conn.execute(
            """
            SELECT p.*,
                   COALESCE(u.username, 'Unknown') AS seller_name,
                   u.profile_image AS seller_photo
            FROM products p
            LEFT JOIN users u ON u.id = p.seller_id
            WHERE p.category_id = ?
              AND (p.title LIKE ? OR u.username LIKE ?)
            ORDER BY p.id DESC
            """,
            (category_id, like, like),
        ).fetchall()
    else:
        products = conn.execute(
            """
            SELECT p.*,
                   COALESCE(u.username, 'Unknown') AS seller_name,
                   u.profile_image AS seller_photo
            FROM products p
            LEFT JOIN users u ON u.id = p.seller_id
            WHERE p.category_id = ?
            ORDER BY p.id DESC
            """,
            (category_id,),
        ).fetchall()

    # ✅ pending_product_ids used if your feed UI shows "Pending" button
    pending_product_ids = set()

    if current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", 0) == 1
        active_mode = getattr(current_user, "active_mode", "buyer")

        # only for buyer mode (not admin / not seller mode)
        if (not is_admin) and active_mode == "buyer":
            rows = conn.execute(
                """
                SELECT DISTINCT r.product_id
                FROM requests r
                JOIN products p ON p.id = r.product_id
                WHERE r.buyer_id = ?
                  AND r.status = 'pending'
                  AND p.category_id = ?
                """,
                (current_user.id, category_id),
            ).fetchall()

            pending_product_ids = {row["product_id"] for row in rows}

    conn.close()

    return render_template(
        "public/feed.html",
        category=category,
        products=products,
        q=q,  # ✅ required for your search bar value="{{ q or '' }}"
        pending_product_ids=pending_product_ids,
    )


@public_bp.route("/about")
def about():
    return render_template("public/about.html")