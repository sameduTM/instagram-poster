"""
JSON API equivalents of the dashboard actions, for scripting / integrating
into other tools (cron jobs, n8n, Zapier-style automations, etc).
"""

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

import db
from instagram_api import InstagramAPI, InstagramAPIError

api_bp = Blueprint("api", __name__, url_prefix="/api")
ig_api = InstagramAPI()


@api_bp.route("/account", methods=["GET"])
def get_account():
    account = db.get_active_account()
    if not account:
        return jsonify({"connected": False}), 200
    return jsonify(
        {
            "connected": True,
            "ig_user_id": account["ig_user_id"],
            "username": account["username"],
            "token_expires_at": account["token_expires_at"],
        }
    )


@api_bp.route("/posts", methods=["GET"])
def list_posts():
    return jsonify(db.get_all_posts())


@api_bp.route("/posts/<int:post_id>", methods=["GET"])
def get_post(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({"error": "not found"}), 404
    return jsonify(post)


@api_bp.route("/posts", methods=["POST"])
def schedule_post():
    """
    Body (JSON):
    {
      "media_url": "https://your-public-host.com/image.jpg",
      "caption": "Hello world",
      "media_type": "IMAGE",            // IMAGE | VIDEO | REELS
      "scheduled_time": "2026-06-22T15:00:00+00:00"   // ISO 8601, omit to publish ASAP
    }
    """
    account = db.get_active_account()
    if not account:
        return (
            jsonify(
                {"error": "No connected Instagram account. Visit /auth/login first."}
            ),
            400,
        )

    body = request.get_json(silent=True) or {}
    media_url = body.get("media_url")
    if not media_url:
        return jsonify({"error": "media_url is required"}), 400

    caption = body.get("caption", "")
    media_type = body.get("media_type", "IMAGE")
    if media_type not in ("IMAGE", "VIDEO", "REELS"):
        return jsonify({"error": "media_type must be IMAGE, VIDEO, or REELS"}), 400

    scheduled_time = body.get("scheduled_time")
    if scheduled_time:
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time)
            if scheduled_dt.tzinfo is None:
                scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "scheduled_time must be ISO 8601"}), 400
    else:
        scheduled_dt = datetime.now(timezone.utc)

    post_id = db.create_scheduled_post(
        account_id=account["id"],
        caption=caption,
        media_url=media_url,
        media_type=media_type,
        scheduled_time=scheduled_dt.astimezone(timezone.utc).isoformat(),
    )
    return jsonify({"id": post_id, "status": "pending"}), 201


@api_bp.route("/posts/<int:post_id>", methods=["DELETE"])
def cancel_post(post_id):
    db.cancel_post(post_id)
    return jsonify({"id": post_id, "status": "canceled"})


@api_bp.route("/posts/<int:post_id>/publish-now", methods=["POST"])
def publish_now(post_id):
    post = db.get_post(post_id)
    account = db.get_active_account()
    if not post or not account:
        return jsonify({"error": "post or account not found"}), 404

    db.update_post_status(post_id, "processing")
    try:
        media_id, permalink, container_id = ig_api.publish_post(
            ig_user_id=account["ig_user_id"],
            access_token=account["access_token"],
            media_url=post["media_url"],
            caption=post["caption"],
            media_type=post["media_type"],
        )
        db.update_post_status(
            post_id,
            "published",
            container_id=container_id,
            ig_media_id=media_id,
            permalink=permalink,
        )
        return jsonify(
            {
                "id": post_id,
                "status": "published",
                "media_id": media_id,
                "permalink": permalink,
            }
        )
    except InstagramAPIError as e:
        db.update_post_status(post_id, "failed", error_message=str(e))
        return jsonify({"id": post_id, "status": "failed", "error": str(e)}), 502
