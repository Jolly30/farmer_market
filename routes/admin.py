# routes/admin.py
import os
import time
from functools import wraps
from datetime import datetime, timedelta

from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from db import get_db_connection

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# =========================
# Admin Guard
# =========================
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        if getattr(current_user, "is_admin", 0) != 1:
            flash("Admin only access.", "danger")
            return redirect(url_for("public.categories"))

        return fn(*args, **kwargs)

    return wrapper


# =========================
# /admin -> redirect to dashboard
# =========================
@admin_bp.route("/")
@login_required
@admin_required
def admin_home():
    return redirect(url_for("admin.dashboard"))


# =========================
# Helpers (safe schema checks)
# =========================
def _table_has_column(conn, table_name: str, col_name: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(c["name"] == col_name for c in cols)


def _last_n_days_labels(n=14):
    today = datetime.now().date()
    labels = []
    for i in range(n - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%b %d"))  # e.g. "Feb 21"
    return labels


# =========================
# Dashboard
# =========================
@admin_bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin != 1:
        return redirect(url_for("public.categories"))

    conn = get_db_connection()

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    approved_sellers = conn.execute(
        "SELECT COUNT(*) FROM users WHERE seller_status='approved'"
    ).fetchone()[0]
    pending_seller_apps = conn.execute(
        "SELECT COUNT(*) FROM seller_applications WHERE status='pending'"
    ).fetchone()[0]
    total_products = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]
    accepted_sales = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status='accepted'"
    ).fetchone()[0]
    completed_deals = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status='completed'"
    ).fetchone()[0]

    # ✅ ADD THIS
    total_categories = conn.execute(
        "SELECT COUNT(*) FROM categories"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        approved_sellers=approved_sellers,
        pending_seller_apps=pending_seller_apps,
        total_products=total_products,
        accepted_sales=accepted_sales,
        completed_deals=completed_deals,
        total_categories=total_categories,  # ✅ pass to template
    )
# =========================
# Dashboard JSON for charts
# endpoint used by template: url_for('admin.stats_json')
# =========================
@admin_bp.route("/stats.json", endpoint="stats_json")
@login_required
@admin_required
def stats_json():
    from datetime import datetime, timedelta
    from flask import request, jsonify

    conn = get_db_connection()

    # -------------------------
    # period: days (default 14)
    # -------------------------
    try:
        days = int(request.args.get("days", 14))
    except Exception:
        days = 14
    if days not in (7, 14, 30, 90):
        days = 14

    # Buyer vs Seller (simple definition)
    sellers = conn.execute(
        "SELECT COUNT(*) FROM users WHERE seller_status='approved'"
    ).fetchone()[0]
    buyers = conn.execute(
        "SELECT COUNT(*) FROM users WHERE IFNULL(is_admin,0) != 1 AND seller_status != 'approved'"
    ).fetchone()[0]

    # -------------------------
    # labels for last N days
    # -------------------------
    today = datetime.now().date()
    labels = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%b %d"))

    accepted = [0] * days
    rejected = [0] * days

    # If requests.created_at exists (you have it)
    rows = conn.execute(
        f"""
        SELECT date(created_at) AS d,
               SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted_count,
               SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected_count
        FROM requests
        WHERE date(created_at) >= date('now','-{days-1} day')
        GROUP BY date(created_at)
        ORDER BY date(created_at) ASC
        """
    ).fetchall()

    # map yyyy-mm-dd -> counts
    m = {}
    for r in rows:
        if r["d"]:
            m[r["d"]] = (
                int(r["accepted_count"] or 0),
                int(r["rejected_count"] or 0),
            )

    # fill arrays in same order as labels
    for idx in range(days):
        d = today - timedelta(days=(days - 1 - idx))
        key = d.strftime("%Y-%m-%d")
        a, rj = m.get(key, (0, 0))
        accepted[idx] = a
        rejected[idx] = rj

    conn.close()

    return jsonify(
        sales_last_n_days={
            "days": days,
            "labels": labels,
            "accepted": accepted,
            "rejected": rejected,
        },
        users_buyer_vs_seller={
            "labels": ["Buyers", "Sellers"],
            "data": [buyers, sellers]
        },
    )
# =========================
# Seller Applications
# base.html expects: url_for('admin.seller_applications')
# =========================
@admin_bp.route("/seller-applications", endpoint="seller_applications")
@login_required
@admin_required
def seller_applications():
    conn = get_db_connection()
    apps = conn.execute(
        """
        SELECT sa.*, u.username
        FROM seller_applications sa
        JOIN users u ON u.id = sa.user_id
        ORDER BY sa.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("admin/seller_applications.html", apps=apps)


@admin_bp.route("/seller-applications/<int:app_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_seller(app_id):
    conn = get_db_connection()
    app = conn.execute(
        "SELECT * FROM seller_applications WHERE id=?",
        (app_id,),
    ).fetchone()

    if not app:
        conn.close()
        flash("Application not found.", "danger")
        return redirect(url_for("admin.seller_applications"))

    conn.execute("UPDATE seller_applications SET status='approved' WHERE id=?", (app_id,))
    conn.execute("UPDATE users SET seller_status='approved' WHERE id=?", (app["user_id"],))
    conn.commit()
    conn.close()

    flash("Seller approved ✅", "success")
    return redirect(url_for("admin.seller_applications"))


@admin_bp.route("/seller-applications/<int:app_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_seller(app_id):
    conn = get_db_connection()
    app = conn.execute(
        "SELECT * FROM seller_applications WHERE id=?",
        (app_id,),
    ).fetchone()

    if not app:
        conn.close()
        flash("Application not found.", "danger")
        return redirect(url_for("admin.seller_applications"))

    conn.execute("UPDATE seller_applications SET status='rejected' WHERE id=?", (app_id,))
    conn.execute("UPDATE users SET seller_status='rejected' WHERE id=?", (app["user_id"],))
    conn.commit()
    conn.close()

    flash("Seller rejected.", "info")
    return redirect(url_for("admin.seller_applications"))


# =========================
# Category image upload config
# =========================
CAT_UPLOAD_FOLDER = os.path.join("static", "uploads", "category_images")
CAT_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}


def allowed_cat_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in CAT_ALLOWED_EXT


# =========================
# Categories (Add + List)
# =========================
@admin_bp.route("/categories", methods=["GET", "POST"])
@login_required
@admin_required
def categories():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        file = request.files.get("image")

        if not name:
            conn.close()
            flash("Category name is required.", "danger")
            return redirect(url_for("admin.categories"))

        image_path = None
        if file and file.filename:
            if not allowed_cat_image(file.filename):
                conn.close()
                flash("Image must be png/jpg/jpeg/webp.", "danger")
                return redirect(url_for("admin.categories"))

            os.makedirs(CAT_UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            unique_name = f"cat_{int(time.time())}_{filename}"
            save_path = os.path.join(CAT_UPLOAD_FOLDER, unique_name)
            file.save(save_path)
            image_path = f"uploads/category_images/{unique_name}"

        conn.execute(
            "INSERT INTO categories (name, image_path) VALUES (?, ?)",
            (name, image_path),
        )
        conn.commit()
        conn.close()

        flash("Category added ✅", "success")
        return redirect(url_for("admin.categories"))

    cats = conn.execute("SELECT * FROM categories ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/categories.html", categories=cats)


@admin_bp.route("/categories/<int:cat_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_category(cat_id):
    name = request.form.get("name", "").strip()
    file = request.files.get("image")

    conn = get_db_connection()
    cat = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()

    if not cat:
        conn.close()
        flash("Category not found.", "danger")
        return redirect(url_for("admin.categories"))

    if not name:
        conn.close()
        flash("Category name is required.", "danger")
        return redirect(url_for("admin.categories"))

    image_path = cat["image_path"]

    if file and file.filename:
        if not allowed_cat_image(file.filename):
            conn.close()
            flash("Image must be png/jpg/jpeg/webp.", "danger")
            return redirect(url_for("admin.categories"))

        os.makedirs(CAT_UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(file.filename)
        unique_name = f"cat_{int(time.time())}_{filename}"
        save_path = os.path.join(CAT_UPLOAD_FOLDER, unique_name)
        file.save(save_path)
        image_path = f"uploads/category_images/{unique_name}"

    conn.execute(
        "UPDATE categories SET name=?, image_path=? WHERE id=?",
        (name, image_path, cat_id),
    )
    conn.commit()
    conn.close()

    flash("Category updated ✅", "success")
    return redirect(url_for("admin.categories"))


@admin_bp.route("/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_category(cat_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()

    flash("Category deleted.", "info")
    return redirect(url_for("admin.categories"))