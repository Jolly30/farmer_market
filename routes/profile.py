# routes/profile.py
import os, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from db import get_db_connection

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")

UPLOAD_FOLDER = os.path.join("static", "uploads", "profile_images")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@profile_bp.route("/", methods=["GET", "POST"], endpoint="profile")
@login_required
def profile():
    conn = get_db_connection()

    if request.method == "POST":
        # ----- basic fields -----
        phone = request.form.get("phone", "").strip()

        full_name = request.form.get("full_name", "").strip()
        address = request.form.get("address", "").strip()
        bio = request.form.get("bio", "").strip()

        # professional fields
        farm_name = request.form.get("farm_name", "").strip()
        business_hours = request.form.get("business_hours", "").strip()
        facebook_link = request.form.get("facebook_link", "").strip()
        website_link = request.form.get("website_link", "").strip()
        location_city = request.form.get("location_city", "").strip()
        contact_preference = request.form.get("contact_preference", "").strip()
        tagline = request.form.get("tagline", "").strip()
        whatsapp = request.form.get("whatsapp", "").strip()
        location = request.form.get("location", "").strip()

        # load current db values
        me = conn.execute(
            "SELECT id, username, email, profile_image FROM users WHERE id=?",
            (current_user.id,),
        ).fetchone()

        if not me:
            conn.close()
            abort(404)

        username = me["username"]
        email = me["email"]

        # ✅ REMOVE PHOTO (works now)
        if request.form.get("remove_photo") == "1":
            if me["profile_image"]:
                # delete file from disk
                file_path = os.path.join("static", me["profile_image"])
                if os.path.exists(file_path):
                    os.remove(file_path)

                # clear DB field
                conn.execute(
                    "UPDATE users SET profile_image=NULL WHERE id=?",
                    (current_user.id,),
                )
                conn.commit()

            conn.close()
            flash("Profile photo removed ✅", "success")
            return redirect(url_for("profile.profile"))

        # ----- profile image upload -----
        image = request.files.get("profile_image")
        image_path = None
        if image and image.filename:
            if not allowed_file(image.filename):
                flash("Image must be png/jpg/jpeg/webp.", "danger")
                conn.close()
                return redirect(url_for("profile.profile"))

            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(image.filename)
            unique_name = f"user_{current_user.id}_{int(time.time())}_{filename}"
            save_path = os.path.join(UPLOAD_FOLDER, unique_name)
            image.save(save_path)
            image_path = f"uploads/profile_images/{unique_name}"  # relative to /static

        # ----- update DB -----
        if image_path:
            conn.execute(
                """
                UPDATE users
                SET username=?, email=?, phone=?,
                    full_name=?, address=?, bio=?,
                    profile_image=?,
                    farm_name=?, business_hours=?, facebook_link=?, website_link=?,
                    location_city=?, contact_preference=?, tagline=?, whatsapp=?, location=?
                WHERE id=?
                """,
                (
                    username, email, phone,
                    full_name, address, bio,
                    image_path,
                    farm_name, business_hours, facebook_link, website_link,
                    location_city, contact_preference, tagline, whatsapp, location,
                    current_user.id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET username=?, email=?, phone=?,
                    full_name=?, address=?, bio=?,
                    farm_name=?, business_hours=?, facebook_link=?, website_link=?,
                    location_city=?, contact_preference=?, tagline=?, whatsapp=?, location=?
                WHERE id=?
                """,
                (
                    username, email, phone,
                    full_name, address, bio,
                    farm_name, business_hours, facebook_link, website_link,
                    location_city, contact_preference, tagline, whatsapp, location,
                    current_user.id,
                ),
            )

        conn.commit()
        conn.close()

        flash("Profile updated successfully ✅", "success")
        return redirect(url_for("profile.profile"))

    conn.close()
    return render_template("account/profile.html")


@profile_bp.route("/<int:user_id>", methods=["GET"], endpoint="view_user")
def view_user(user_id):
    conn = get_db_connection()
    u = conn.execute(
        """
        SELECT id, username, full_name, bio, address, phone,
               seller_status, delivery_eta, profile_image,
               farm_name, business_hours, facebook_link, website_link,
               location_city, contact_preference, tagline, whatsapp, location
        FROM users
        WHERE id=?
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if not u:
        abort(404)

    is_me = False
    if current_user.is_authenticated:
        is_me = (current_user.id == u["id"])

    return render_template("profile/view_user.html", u=u, is_me=is_me)