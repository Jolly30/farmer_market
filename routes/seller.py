# routes/seller.py
from functools import wraps
import os, time

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from db import get_db_connection

seller_bp = Blueprint("seller", __name__, url_prefix="/seller")

# =========================
# Upload config (seller docs)
# =========================
DOC_UPLOAD_FOLDER = os.path.join("static", "uploads", "seller_docs")
DOC_ALLOWED_EXT = {"png", "jpg", "jpeg", "pdf"}

def allowed_doc(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in DOC_ALLOWED_EXT


# =========================
# Upload config (product images) ✅ NEW
# =========================
PRODUCT_UPLOAD_FOLDER = os.path.join("static", "uploads", "product_images")
PRODUCT_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

def allowed_product_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in PRODUCT_ALLOWED_EXT


# =========================
# Helpers
# =========================
def is_approved_seller():
    return getattr(current_user, "seller_status", "none") == "approved"


def seller_mode_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_approved_seller():
            flash("You are not an approved seller.", "warning")
            return redirect(url_for("seller.apply_seller"))

        if getattr(current_user, "active_mode", "buyer") != "seller":
            flash("Switch to Seller mode first.", "warning")
            return redirect(url_for("public.categories"))

        return fn(*args, **kwargs)

    return wrapper


def _split_other(text: str):
    """'A, B | C' -> ['A','B','C']"""
    if not text:
        return []
    raw = text.replace("|", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _dedupe_keep_order(items):
    out = []
    seen = set()
    for x in items:
        k = x.strip().lower()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def build_payment_methods_from_form(form):
    """
    Stores as: 'bank:KBZ Bank|pay:KBZPay|cash:Cash'
    """
    bank_selected = form.getlist("bank_options")
    pay_selected = form.getlist("pay_options")
    cash_selected = form.getlist("cash_options")

    bank_other = _split_other(form.get("bank_other", ""))
    pay_other = _split_other(form.get("pay_other", ""))
    cash_other = _split_other(form.get("cash_other", ""))

    banks = _dedupe_keep_order([*bank_selected, *bank_other])
    pays = _dedupe_keep_order([*pay_selected, *pay_other])

    cash_items = []
    if cash_selected:
        cash_items.append("Cash")
    cash_items = _dedupe_keep_order([*cash_items, *cash_other])

    out = []
    for b in banks:
        out.append(f"bank:{b}")
    for p in pays:
        out.append(f"pay:{p}")
    for c in cash_items:
        out.append(f"cash:{c}")

    return "|".join(out)


def build_delivery_methods_from_form(form):
    """delivery_methods (list) + delivery_other (text) -> 'A|B|C'"""
    selected = form.getlist("delivery_methods")
    other = _split_other(form.get("delivery_other", ""))
    merged = _dedupe_keep_order([*selected, *other])
    return "|".join(merged)


# =========================
# Apply Seller
# =========================
@seller_bp.route("/apply", methods=["GET", "POST"])
@login_required
def apply_seller():
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT * FROM seller_applications WHERE user_id=?",
        (current_user.id,),
    ).fetchone()

    if getattr(current_user, "seller_status", "none") == "approved":
        conn.close()
        flash("You are already an approved seller ✅", "info")
        return redirect(url_for("public.categories"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        farm_name = request.form.get("farm_name", "").strip()
        note = request.form.get("note", "").strip()

        if not full_name or not phone or not address or not farm_name:
            conn.close()
            flash("Full name, phone, address, and farm/shop name are required.", "danger")
            return redirect(url_for("seller.apply_seller"))

        document_path = existing["document_path"] if existing else None
        file = request.files.get("document")

        if file and file.filename:
            if not allowed_doc(file.filename):
                conn.close()
                flash("Document must be png/jpg/jpeg/pdf.", "danger")
                return redirect(url_for("seller.apply_seller"))

            os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            unique_name = f"{current_user.id}_{int(time.time())}_{filename}"
            save_path = os.path.join(DOC_UPLOAD_FOLDER, unique_name)
            file.save(save_path)

            document_path = f"uploads/seller_docs/{unique_name}"

        if not document_path:
            conn.close()
            flash("Please upload a document (png/jpg/jpeg/pdf).", "danger")
            return redirect(url_for("seller.apply_seller"))

        if existing:
            conn.execute(
                """
                UPDATE seller_applications
                SET full_name=?, phone=?, address=?, farm_name=?, note=?,
                    document_path=?, status='pending'
                WHERE user_id=?
                """,
                (full_name, phone, address, farm_name, note, document_path, current_user.id),
            )
        else:
            conn.execute(
                """
                INSERT INTO seller_applications
                (user_id, full_name, phone, address, farm_name, note, document_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (current_user.id, full_name, phone, address, farm_name, note, document_path),
            )

        conn.execute("UPDATE users SET seller_status='pending' WHERE id=?", (current_user.id,))
        conn.commit()
        conn.close()

        flash("Application submitted ✅ (Pending admin approval)", "success")
        return redirect(url_for("seller.seller_status"))

    conn.close()
    return render_template("seller/apply.html", existing=existing)


@seller_bp.route("/status", endpoint="seller_status")
@login_required
def seller_status():
    conn = get_db_connection()
    app = conn.execute(
        "SELECT * FROM seller_applications WHERE user_id=?",
        (current_user.id,),
    ).fetchone()
    conn.close()
    return render_template("seller/status.html", app=app)


# =========================
# Switch mode
# =========================
@seller_bp.route("/switch-to-seller", methods=["POST"])
@login_required
def switch_to_seller():
    if not is_approved_seller():
        flash("You are not approved as seller yet.", "warning")
        return redirect(url_for("seller.apply_seller"))

    conn = get_db_connection()
    conn.execute("UPDATE users SET active_mode='seller' WHERE id=?", (current_user.id,))
    conn.commit()
    conn.close()

    flash("Switched to Seller mode ✅", "success")
    return redirect(url_for("public.categories"))


@seller_bp.route("/switch-to-buyer", methods=["POST"])
@login_required
def switch_to_buyer():
    conn = get_db_connection()
    conn.execute("UPDATE users SET active_mode='buyer' WHERE id=?", (current_user.id,))
    conn.commit()
    conn.close()

    flash("Switched to Buyer mode ✅", "success")
    return redirect(url_for("public.categories"))


# =========================
# My Products
# =========================
@seller_bp.route("/my/products")
@login_required
@seller_mode_required
def manage_products():
    conn = get_db_connection()
    products = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.seller_id=?
        ORDER BY p.id DESC
        """,
        (current_user.id,),
    ).fetchall()
    conn.close()
    return render_template("seller/manage_products.html", products=products)


# =========================
# Add Product ✅ includes image upload
# =========================
@seller_bp.route("/my/products/add", methods=["GET", "POST"])
@login_required
@seller_mode_required
def add_product():
    conn = get_db_connection()
    categories = conn.execute("SELECT id, name FROM categories ORDER BY name ASC").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        price = request.form.get("price", "").strip()        # price per kg
        quantity = request.form.get("quantity", "").strip()  # kg available
        category_id = request.form.get("category_id", "").strip()

        min_order_qty = request.form.get("min_order_qty", "").strip()  # kg
        delivery_eta = request.form.get("delivery_eta", "").strip()

        payment_methods = build_payment_methods_from_form(request.form)
        delivery_methods = build_delivery_methods_from_form(request.form)

        if not title or not price or not quantity or not category_id:
            conn.close()
            flash("Title, price, quantity, and category are required.", "danger")
            return redirect(url_for("seller.add_product"))

        try:
            min_order_qty_int = int(min_order_qty) if min_order_qty else 1
        except ValueError:
            min_order_qty_int = 1
        if min_order_qty_int < 1:
            min_order_qty_int = 1

        # ✅ Product image upload
        image_path = None
        file = request.files.get("image")  # must match input name="image" in product_form.html
        if file and file.filename:
            if not allowed_product_image(file.filename):
                conn.close()
                flash("Product image must be png/jpg/jpeg/webp.", "danger")
                return redirect(url_for("seller.add_product"))

            os.makedirs(PRODUCT_UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            unique_name = f"{current_user.id}_{int(time.time())}_{filename}"
            save_path = os.path.join(PRODUCT_UPLOAD_FOLDER, unique_name)
            file.save(save_path)

            image_path = f"uploads/product_images/{unique_name}"

        conn.execute(
            """
            INSERT INTO products
              (title, description, price, quantity, category_id, seller_id, image_path,
               min_order_qty, payment_methods, delivery_methods, delivery_eta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title, description, price, quantity, category_id, current_user.id, image_path,
                min_order_qty_int, payment_methods, delivery_methods, delivery_eta
            ),
        )
        conn.commit()
        conn.close()

        flash("Product added ✅", "success")
        return redirect(url_for("seller.manage_products"))

    conn.close()
    return render_template("seller/product_form.html", categories=categories, product=None, is_edit=False)


# =========================
# Edit Product ✅ includes image upload replace
# =========================
@seller_bp.route("/my/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@seller_mode_required
def edit_product(product_id):
    conn = get_db_connection()

    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND seller_id=?",
        (product_id, current_user.id),
    ).fetchone()

    if not product:
        conn.close()
        flash("Product not found.", "danger")
        return redirect(url_for("seller.manage_products"))

    categories = conn.execute("SELECT id, name FROM categories ORDER BY name ASC").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        price = request.form.get("price", "").strip()
        quantity = request.form.get("quantity", "").strip()
        category_id = request.form.get("category_id", "").strip()

        min_order_qty = request.form.get("min_order_qty", "").strip()
        delivery_eta = request.form.get("delivery_eta", "").strip()

        payment_methods = build_payment_methods_from_form(request.form)
        delivery_methods = build_delivery_methods_from_form(request.form)

        if not title or not price or not quantity or not category_id:
            conn.close()
            flash("Title, price, quantity, and category are required.", "danger")
            return redirect(url_for("seller.edit_product", product_id=product_id))

        try:
            min_order_qty_int = int(min_order_qty) if min_order_qty else 1
        except ValueError:
            min_order_qty_int = 1
        if min_order_qty_int < 1:
            min_order_qty_int = 1

        # ✅ keep old image unless new uploaded
        image_path = product["image_path"]
        file = request.files.get("image")
        if file and file.filename:
            if not allowed_product_image(file.filename):
                conn.close()
                flash("Product image must be png/jpg/jpeg/webp.", "danger")
                return redirect(url_for("seller.edit_product", product_id=product_id))

            os.makedirs(PRODUCT_UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            unique_name = f"{current_user.id}_{int(time.time())}_{filename}"
            save_path = os.path.join(PRODUCT_UPLOAD_FOLDER, unique_name)
            file.save(save_path)

            image_path = f"uploads/product_images/{unique_name}"

        conn.execute(
            """
            UPDATE products
            SET title=?, description=?, price=?, quantity=?, category_id=?, image_path=?,
                min_order_qty=?, payment_methods=?, delivery_methods=?, delivery_eta=?
            WHERE id=? AND seller_id=?
            """,
            (
                title, description, price, quantity, category_id, image_path,
                min_order_qty_int, payment_methods, delivery_methods, delivery_eta,
                product_id, current_user.id
            ),
        )
        conn.commit()
        conn.close()

        flash("Product updated ✅", "success")
        return redirect(url_for("seller.manage_products"))

    conn.close()
    return render_template("seller/product_form.html", categories=categories, product=product, is_edit=True)


# =========================
# Delete Product
# =========================
@seller_bp.route("/my/products/<int:product_id>/delete", methods=["POST"])
@login_required
@seller_mode_required
def delete_product(product_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id=? AND seller_id=?", (product_id, current_user.id))
    conn.commit()
    conn.close()

    flash("Product deleted ✅", "info")
    return redirect(url_for("seller.manage_products"))


# =========================
# My Sales
# =========================
@seller_bp.route("/my-sales")
@login_required
@seller_mode_required
def seller_requests():
    conn = get_db_connection()
    requests_rows = conn.execute(
        """
        SELECT r.*,
               p.title AS product_title,
               u.username AS buyer_name,
               u.email AS buyer_email
        FROM requests r
        JOIN products p ON p.id = r.product_id
        JOIN users u ON u.id = r.buyer_id
        WHERE r.seller_id = ?
        ORDER BY r.id DESC
        """,
        (current_user.id,),
    ).fetchall()
    conn.close()

    return render_template("seller/my_sales.html", requests=requests_rows)


@seller_bp.route("/my-sales/<int:req_id>/accept", methods=["POST"])
@login_required
@seller_mode_required
def accept_request(req_id):
    comment = request.form.get("seller_comment", "").strip()

    conn = get_db_connection()

    req_row = conn.execute(
        "SELECT id, product_id FROM requests WHERE id=? AND seller_id=?",
        (req_id, current_user.id),
    ).fetchone()

    if not req_row:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for("seller.seller_requests"))

    prod = conn.execute(
        """
        SELECT title, price, image_path, min_order_qty, delivery_eta
        FROM products
        WHERE id=?
        """,
        (req_row["product_id"],),
    ).fetchone()

    if prod:
        conn.execute(
            """
            UPDATE requests
            SET status='accepted',
                seller_comment=?,
                snap_title=COALESCE(snap_title, ?),
                snap_price=COALESCE(snap_price, ?),
                snap_unit=COALESCE(snap_unit, 'kg'),
                snap_image_path=COALESCE(snap_image_path, ?),
                snap_min_order_qty=COALESCE(snap_min_order_qty, ?),
                snap_delivery_eta=COALESCE(snap_delivery_eta, ?)
            WHERE id=?
            """,
            (
                comment,
                prod["title"],
                prod["price"],
                prod["image_path"],
                prod["min_order_qty"],
                prod["delivery_eta"],
                req_id,
            ),
        )
    else:
        conn.execute(
            "UPDATE requests SET status='accepted', seller_comment=? WHERE id=?",
            (comment, req_id),
        )

    conn.commit()
    conn.close()

    flash("Request accepted ✅", "success")
    return redirect(url_for("seller.seller_requests"))
@seller_bp.route("/my-sales/<int:req_id>/reject", methods=["POST"])
@login_required
@seller_mode_required
def reject_request(req_id):
    comment = request.form.get("seller_comment", "").strip()

    conn = get_db_connection()
    r = conn.execute(
        "SELECT id FROM requests WHERE id=? AND seller_id=?",
        (req_id, current_user.id),
    ).fetchone()

    if not r:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for("seller.seller_requests"))

    conn.execute(
        "UPDATE requests SET status='rejected', seller_comment=? WHERE id=?",
        (comment, req_id),
    )
    conn.commit()
    conn.close()

    flash("Request rejected.", "info")
    return redirect(url_for("seller.seller_requests"))