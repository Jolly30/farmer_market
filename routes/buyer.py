from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from db import get_db_connection

buyer_bp = Blueprint("buyer", __name__, url_prefix="/buyer")


def _block_admin_and_seller_mode():
    if getattr(current_user, "is_admin", 0) == 1:
        flash("Admin cannot make requests. Admin is view-only.", "warning")
        return redirect(url_for("public.categories"))
    if getattr(current_user, "active_mode", "buyer") == "seller":
        flash("Switch to Buyer mode to request products.", "warning")
        return redirect(url_for("public.categories"))
    return None


def _parse_pipe(text):
    if not text:
        return []
    return [x.strip() for x in str(text).split("|") if x.strip()]


def _row_has_key(row, key: str) -> bool:
    try:
        return key in row.keys()
    except Exception:
        return False


# =====================================
# Request Product
# =====================================
@buyer_bp.route("/request/<int:product_id>", methods=["GET", "POST"])
@login_required
def request_product(product_id):
    blocked = _block_admin_and_seller_mode()
    if blocked:
        return blocked

    conn = get_db_connection()

    product = conn.execute(
        """
        SELECT p.*,
               u.username AS seller_name
        FROM products p
        JOIN users u ON u.id = p.seller_id
        WHERE p.id = ?
        """,
        (product_id,),
    ).fetchone()

    if not product:
        conn.close()
        flash("Product not found.", "danger")
        return redirect(url_for("public.categories"))

    if product["seller_id"] == current_user.id:
        conn.close()
        flash("You cannot request your own product.", "warning")
        return redirect(url_for("public.feed", category_id=product["category_id"]))

    min_qty = 1
    if _row_has_key(product, "min_order_qty") and product["min_order_qty"] is not None:
        try:
            min_qty = int(product["min_order_qty"])
        except Exception:
            min_qty = 1
    if min_qty < 1:
        min_qty = 1

    max_qty = int(product["quantity"]) if product["quantity"] is not None else 0

    payment_methods = _parse_pipe(product["payment_methods"]) if _row_has_key(product, "payment_methods") else []
    delivery_methods = _parse_pipe(product["delivery_methods"]) if _row_has_key(product, "delivery_methods") else []

    if request.method == "POST":
        try:
            qty = int(request.form.get("quantity", "0"))
        except ValueError:
            qty = 0

        payment_method = request.form.get("payment_method", "").strip()
        delivery_method = request.form.get("delivery_method", "").strip()
        buyer_note = request.form.get("buyer_note", "").strip()

        if qty < min_qty:
            conn.close()
            flash(f"Minimum order is {min_qty}.", "danger")
            return redirect(url_for("buyer.request_product", product_id=product_id))

        if qty <= 0 or qty > max_qty:
            conn.close()
            flash("Requested quantity exceeds available stock.", "danger")
            return redirect(url_for("buyer.request_product", product_id=product_id))

        if payment_methods and payment_method not in payment_methods:
            conn.close()
            flash("Please choose a payment method offered by the seller.", "danger")
            return redirect(url_for("buyer.request_product", product_id=product_id))

        if delivery_methods and delivery_method not in delivery_methods:
            conn.close()
            flash("Please choose a delivery option offered by the seller.", "danger")
            return redirect(url_for("buyer.request_product", product_id=product_id))

        conn.execute(
            """
            INSERT INTO requests
              (product_id, buyer_id, seller_id, quantity, status, payment_method, delivery_method, buyer_note)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (product_id, current_user.id, product["seller_id"], qty, payment_method, delivery_method, buyer_note),
        )
        conn.commit()
        conn.close()

        flash("Request sent ✅ (Pending seller response)", "success")
        return redirect(url_for("buyer.my_requests"))

    conn.close()
    return render_template(
        "buyer/request_form.html",
        product=product,
        min_qty=min_qty,
        max_qty=max_qty,
        is_edit=False,
        req=None,
        payment_methods=payment_methods,
        delivery_methods=delivery_methods,
    )


# =====================================
# Buyer - My Requests
# =====================================
@buyer_bp.route("/my-requests")
@login_required
def my_requests():
    if getattr(current_user, "is_admin", 0) == 1:
        flash("Admin has no buyer interface.", "warning")
        return redirect(url_for("admin.dashboard"))

    conn = get_db_connection()

    rows = conn.execute(
        """
        SELECT r.*,
               p.title AS product_title,
               p.price AS product_price,
               u.username AS seller_name
        FROM requests r
        JOIN products p ON p.id = r.product_id
        JOIN users u ON u.id = r.seller_id
        WHERE r.buyer_id=?
        ORDER BY r.id DESC
        """,
        (current_user.id,),
    ).fetchall()

    conn.close()

    return render_template("buyer/my_requests.html", requests=rows)


# =====================================
# Edit Request
# =====================================
@buyer_bp.route("/my-requests/<int:req_id>/edit", methods=["GET", "POST"])
@login_required
def edit_request(req_id):
    blocked = _block_admin_and_seller_mode()
    if blocked:
        return blocked

    conn = get_db_connection()

    req = conn.execute(
        "SELECT * FROM requests WHERE id=? AND buyer_id=?",
        (req_id, current_user.id),
    ).fetchone()

    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for("buyer.my_requests"))

    if req["status"] != "pending":
        conn.close()
        flash("Only pending requests can be edited.", "warning")
        return redirect(url_for("buyer.my_requests"))

    product = conn.execute(
        """
        SELECT p.*,
               u.username AS seller_name
        FROM products p
        JOIN users u ON u.id = p.seller_id
        WHERE p.id=?
        """,
        (req["product_id"],),
    ).fetchone()

    min_qty = int(product["min_order_qty"] or 1)
    max_qty = int(product["quantity"] or 0)

    payment_methods = _parse_pipe(product["payment_methods"])
    delivery_methods = _parse_pipe(product["delivery_methods"])

    if request.method == "POST":
        qty = int(request.form.get("quantity", "0"))
        payment_method = request.form.get("payment_method", "").strip()
        delivery_method = request.form.get("delivery_method", "").strip()
        buyer_note = request.form.get("buyer_note", "").strip()

        if qty < min_qty or qty > max_qty:
            flash("Invalid quantity.", "danger")
            return redirect(url_for("buyer.edit_request", req_id=req_id))

        conn.execute(
            """
            UPDATE requests
            SET quantity=?, payment_method=?, delivery_method=?, buyer_note=?
            WHERE id=? AND buyer_id=? AND status='pending'
            """,
            (qty, payment_method, delivery_method, buyer_note, req_id, current_user.id),
        )
        conn.commit()
        conn.close()

        flash("Request updated ✅", "success")
        return redirect(url_for("buyer.my_requests"))

    conn.close()
    return render_template(
        "buyer/request_form.html",
        product=product,
        min_qty=min_qty,
        max_qty=max_qty,
        is_edit=True,
        req=req,
        payment_methods=payment_methods,
        delivery_methods=delivery_methods,
    )


# =====================================
# Delete Request
# =====================================
@buyer_bp.route("/my-requests/<int:req_id>/delete", methods=["POST"])
@login_required
def delete_request(req_id):
    blocked = _block_admin_and_seller_mode()
    if blocked:
        return blocked

    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM requests WHERE id=? AND buyer_id=? AND status='pending'",
        (req_id, current_user.id),
    ).fetchone()

    if not row:
        conn.close()
        flash("Only pending requests can be deleted.", "warning")
        return redirect(url_for("buyer.my_requests"))

    conn.execute("DELETE FROM requests WHERE id=? AND buyer_id=?", (req_id, current_user.id))
    conn.commit()
    conn.close()

    flash("Request deleted.", "info")
    return redirect(url_for("buyer.my_requests"))