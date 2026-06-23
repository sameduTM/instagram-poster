"""
Human-friendly UI: connect account, upload media, schedule posts, see status.
Everything here also has a JSON equivalent in blueprints/api.py for scripting.
"""
import os
import uuid
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

import db
from config import Config
from instagram_api import InstagramAPI, InstagramAPIError

dashboard_bp = Blueprint("dashboard", __name__)
api = InstagramAPI()

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "mp4", "mov"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@dashboard_bp.route("/")
def index():
    account = db.get_active_account()
    posts = db.get_all_posts()
    return render_template("index.html", account=account, posts=posts)


@dashboard_bp.route("/upload", methods=["POST"])
def upload():
    """Saves the uploaded file under static/uploads and redirects back with its public URL filled in."""
    file = request.files.get("media_file")
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("dashboard.index"))

    if not _allowed_file(file.filename):
        flash("Unsupported file type. Use jpg/png for images or mp4/mov for video.", "error")
        return redirect(url_for("dashboard.index"))

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(Config.UPLOAD_FOLDER, unique_name)
    file.save(save_path)

    public_url = f"{Config.BASE_URL}/static/uploads/{unique_name}"
    flash(f"Uploaded. Public URL: {public_url}", "success")
    return redirect(url_for("dashboard.index", prefill_url=public_url))


@dashboard_bp.route("/schedule", methods=["POST"])
def schedule_post():
    account = db.get_active_account()
    if not account:
        flash("Connect an Instagram account first.", "error")
        return redirect(url_for("dashboard.index"))

    media_url = request.form.get("media_url", "").strip()
    caption = request.form.get("caption", "").strip()
    media_type = request.form.get("media_type", "IMAGE")
    scheduled_time_local = request.form.get("scheduled_time", "").strip()

    if not media_url:
        flash("Media URL is required (upload a file above, or paste a public URL).", "error")
        return redirect(url_for("dashboard.index"))

    if not scheduled_time_local:
        # No time given -> publish as soon as the scheduler next runs
        scheduled_dt = datetime.now(timezone.utc)
    else:
        try:
            # <input type="datetime-local"> gives "YYYY-MM-DDTHH:MM" in the
            # browser's local time. We treat it as the SERVER's local time
            # here for simplicity; for production, send timezone-aware data.
            scheduled_dt = datetime.fromisoformat(scheduled_time_local).astimezone(timezone.utc)
        except ValueError:
            flash("Invalid date/time format.", "error")
            return redirect(url_for("dashboard.index"))

    db.create_scheduled_post(
        account_id=account["id"],
        caption=caption,
        media_url=media_url,
        media_type=media_type,
        scheduled_time=scheduled_dt.isoformat(),
    )
    flash("Post scheduled.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/<int:post_id>/cancel", methods=["POST"])
def cancel(post_id):
    db.cancel_post(post_id)
    flash("Post canceled.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/<int:post_id>/publish-now", methods=["POST"])
def publish_now(post_id):
    """Bypasses the schedule and publishes immediately — handy for testing."""
    post = db.get_post(post_id)
    account = db.get_active_account()
    if not post or not account:
        flash("Post or account not found.", "error")
        return redirect(url_for("dashboard.index"))

    db.update_post_status(post_id, "processing")
    try:
        media_id, permalink, container_id = api.publish_post(
            ig_user_id=account["ig_user_id"],
            access_token=account["access_token"],
            media_url=post["media_url"],
            caption=post["caption"],
            media_type=post["media_type"],
        )
        db.update_post_status(
            post_id, "published", container_id=container_id, ig_media_id=media_id, permalink=permalink
        )
        flash("Published!", "success")
    except InstagramAPIError as e:
        db.update_post_status(post_id, "failed", error_message=str(e))
        flash(f"Publish failed: {e}", "error")

    return redirect(url_for("dashboard.index"))
