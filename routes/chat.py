# routes/chat.py (FULL FILE)
import os
import time
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from db import get_db_connection

chat_bp = Blueprint("chat", __name__, url_prefix="/chat")

# =========================
# Upload config (chat images)
# =========================
CHAT_UPLOAD_FOLDER = os.path.join("static", "uploads", "chat_images")
CHAT_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}


def allowed_chat_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in CHAT_ALLOWED_EXT


def _row_has_key(row, key: str) -> bool:
    try:
        return key in row.keys()
    except Exception:
        return False


def _ensure_seen_columns_exist(conn):
    """
    Safety for older DBs. Your DB already has these columns based on PRAGMA output.
    Keeping this here won't change anything if columns exist.
    """
    # no-op (kept intentionally)
    return


# =====================================
# My Chats (separate buyer vs seller)
# =====================================
@chat_bp.route("/", methods=["GET"])
@login_required
def my_chats():
    conn = get_db_connection()
    _ensure_seen_columns_exist(conn)

    mode = getattr(current_user, "active_mode", "buyer")  # buyer or seller
    my_id = current_user.id

    # ✅ Separate chat list by mode
    if mode == "seller":
        where_role = "AND r.seller_id = ?"
    else:
        where_role = "AND r.buyer_id = ?"

    # ✅ chats appear only after accepted/completed
    # ✅ keep chat even if product deleted (LEFT JOIN + snapshot title fallback)
    # ✅ profile image uses users.profile_image
    # ✅ unread_count uses buyer_last_seen_msg_id / seller_last_seen_msg_id
    sql = f"""
    SELECT
      r.id AS request_id,
      r.buyer_id,
      r.seller_id,

      -- Product title: snapshot first, then live product, then Deleted
      COALESCE(r.snap_title, p.title, 'Deleted product') AS product_title,

      buyer.username AS buyer_name,
      buyer.profile_image AS buyer_photo,

      seller.username AS seller_name,
      seller.profile_image AS seller_photo,

      r.status AS req_status,
      r.buyer_completed,
      r.seller_completed,

      -- Message stats
      COALESCE(ms.message_count, 0) AS message_count,
      COALESCE(ms.last_msg_id, 0) AS last_msg_id,

      lm.sender_id AS last_sender_id,
      COALESCE(lm.message, '') AS last_message,
      lm.timestamp AS last_ts,

      -- ✅ Unread COUNT for current user
      CASE
        WHEN ? = r.buyer_id THEN (
          SELECT COUNT(*)
          FROM chat_messages cm
          WHERE cm.request_id = r.id
            AND cm.sender_id != ?
            AND cm.id > COALESCE(r.buyer_last_seen_msg_id, 0)
        )
        ELSE (
          SELECT COUNT(*)
          FROM chat_messages cm
          WHERE cm.request_id = r.id
            AND cm.sender_id != ?
            AND cm.id > COALESCE(r.seller_last_seen_msg_id, 0)
        )
      END AS unread_count

    FROM requests r
    LEFT JOIN products p ON p.id = r.product_id
    JOIN users buyer  ON buyer.id  = r.buyer_id
    JOIN users seller ON seller.id = r.seller_id

    LEFT JOIN (
      SELECT request_id,
             COUNT(*) AS message_count,
             MAX(id) AS last_msg_id
      FROM chat_messages
      GROUP BY request_id
    ) ms ON ms.request_id = r.id

    LEFT JOIN chat_messages lm ON lm.id = ms.last_msg_id

    WHERE (r.status = 'accepted' OR r.status = 'completed')
      {where_role}
    ORDER BY r.id DESC
    """

    rows = conn.execute(sql, (my_id, my_id, my_id, my_id)).fetchall()

    chats = []
    for r in rows:
        # NEW chat = accepted/completed but no messages yet
        is_new_chat = int(r["message_count"] or 0) == 0

        # Completed icon = both completed OR status completed
        is_completed = (r["req_status"] == "completed") or (
            int(r["buyer_completed"] or 0) == 1 and int(r["seller_completed"] or 0) == 1
        )

        chats.append(
            {
                "request_id": r["request_id"],
                "product_title": r["product_title"],
                "buyer_id": r["buyer_id"],
                "seller_id": r["seller_id"],
                "buyer_name": r["buyer_name"],
                "seller_name": r["seller_name"],
                "buyer_photo": r["buyer_photo"],
                "seller_photo": r["seller_photo"],
                "req_status": r["req_status"],
                "last_message": r["last_message"],
                "last_ts": r["last_ts"],
                "unread_count": int(r["unread_count"] or 0),
                "is_new_chat": is_new_chat,
                "is_completed": is_completed,
            }
        )

    conn.close()
    return render_template("chat/my_chats.html", chats=chats, mode=mode)


# =====================================
# Chat Room
# =====================================
@chat_bp.route("/<int:req_id>", methods=["GET", "POST"])
@login_required
def chat_room(req_id):
    conn = get_db_connection()
    _ensure_seen_columns_exist(conn)

    # Load request + people + snapshot data
    req = conn.execute(
        """
        SELECT
          r.*,
          buyer.username AS buyer_name,
          buyer.profile_image AS buyer_photo,
          seller.username AS seller_name,
          seller.profile_image AS seller_photo,
          COALESCE(r.snap_title, p.title, 'Deleted product') AS product_title
        FROM requests r
        LEFT JOIN products p ON p.id = r.product_id
        JOIN users buyer  ON buyer.id  = r.buyer_id
        JOIN users seller ON seller.id = r.seller_id
        WHERE r.id = ?
        """,
        (req_id,),
    ).fetchone()

    if not req:
        conn.close()
        flash("Chat not found.", "danger")
        return redirect(url_for("chat.my_chats"))

    # Only buyer or seller can access
    if current_user.id not in (req["buyer_id"], req["seller_id"]):
        conn.close()
        flash("You are not allowed to access this chat.", "danger")
        return redirect(url_for("chat.my_chats"))

    # Read-only if both completed OR status completed
    is_readonly = (req["status"] == "completed") or (
        int(req["buyer_completed"] or 0) == 1 and int(req["seller_completed"] or 0) == 1
    )

    # POST: send message/image
    if request.method == "POST":
        if is_readonly:
            conn.close()
            flash("Chat is closed (read-only).", "warning")
            return redirect(url_for("chat.chat_room", req_id=req_id))

        msg = (request.form.get("message") or "").strip()
        image = request.files.get("image")

        image_path = None
        if image and image.filename:
            if not allowed_chat_image(image.filename):
                conn.close()
                flash("Image must be png/jpg/jpeg/webp.", "danger")
                return redirect(url_for("chat.chat_room", req_id=req_id))

            os.makedirs(CHAT_UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(image.filename)
            unique_name = f"chat_{req_id}_{current_user.id}_{int(time.time())}_{filename}"
            save_path = os.path.join(CHAT_UPLOAD_FOLDER, unique_name)
            image.save(save_path)
            image_path = f"uploads/chat_images/{unique_name}"

        if not msg and not image_path:
            conn.close()
            flash("Type a message or upload an image.", "warning")
            return redirect(url_for("chat.chat_room", req_id=req_id))

        conn.execute(
            """
            INSERT INTO chat_messages (request_id, sender_id, message, image_path)
            VALUES (?, ?, ?, ?)
            """,
            (req_id, current_user.id, msg, image_path),
        )

        # ✅ when new message is sent, mark "seen" flags as 0 for the OTHER side (simple)
        if current_user.id == req["buyer_id"]:
            conn.execute("UPDATE requests SET seller_seen = 0 WHERE id = ?", (req_id,))
        else:
            conn.execute("UPDATE requests SET buyer_seen = 0 WHERE id = ?", (req_id,))

        conn.commit()
        conn.close()
        return redirect(url_for("chat.chat_room", req_id=req_id))

    # Load messages (JOIN users for sender_name) ✅ fixes your "no such column: sender_name"
    messages = conn.execute(
        """
        SELECT
          cm.*,
          u.username AS sender_name
        FROM chat_messages cm
        JOIN users u ON u.id = cm.sender_id
        WHERE cm.request_id = ?
        ORDER BY cm.id ASC
        """,
        (req_id,),
    ).fetchall()

    # ✅ Update last_seen_msg_id for current user
    last_id_row = conn.execute(
        "SELECT COALESCE(MAX(id),0) AS last_id FROM chat_messages WHERE request_id=?",
        (req_id,),
    ).fetchone()
    last_id = int(last_id_row["last_id"] or 0)

    if current_user.id == req["buyer_id"]:
        conn.execute(
            "UPDATE requests SET buyer_seen=1, buyer_last_seen_msg_id=? WHERE id=?",
            (last_id, req_id),
        )
    else:
        conn.execute(
            "UPDATE requests SET seller_seen=1, seller_last_seen_msg_id=? WHERE id=?",
            (last_id, req_id),
        )

    conn.commit()
    conn.close()

    # highlight latest incoming unread: simplest UX = highlight last message from other user
    last_incoming_id = None
    for m in reversed(messages):
        if m["sender_id"] != current_user.id:
            last_incoming_id = m["id"]
            break

    return render_template(
        "chat/chat.html",
        req=req,
        messages=messages,
        me_id=current_user.id,
        is_readonly=is_readonly,
        product_title=req["product_title"],
        buyer_name=req["buyer_name"],
        seller_name=req["seller_name"],
        buyer_photo=req["buyer_photo"],
        seller_photo=req["seller_photo"],
        last_incoming_id=last_incoming_id,
    )


# =====================================
# Mark Completed (buyer or seller)
# =====================================
@chat_bp.route("/<int:req_id>/complete", methods=["POST"])
@login_required
def mark_complete(req_id):
    conn = get_db_connection()

    req = conn.execute("SELECT * FROM requests WHERE id=?", (req_id,)).fetchone()
    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for("chat.my_chats"))

    if current_user.id not in (req["buyer_id"], req["seller_id"]):
        conn.close()
        flash("Not allowed.", "danger")
        return redirect(url_for("chat.my_chats"))

    if current_user.id == req["buyer_id"]:
        conn.execute("UPDATE requests SET buyer_completed=1 WHERE id=?", (req_id,))
    else:
        conn.execute("UPDATE requests SET seller_completed=1 WHERE id=?", (req_id,))

    # if both completed -> status completed
    req2 = conn.execute(
        "SELECT buyer_completed, seller_completed FROM requests WHERE id=?", (req_id,)
    ).fetchone()

    if int(req2["buyer_completed"] or 0) == 1 and int(req2["seller_completed"] or 0) == 1:
        conn.execute("UPDATE requests SET status='completed' WHERE id=?", (req_id,))

    conn.commit()
    conn.close()
    flash("Marked completed ✅", "success")
    return redirect(url_for("chat.chat_room", req_id=req_id))