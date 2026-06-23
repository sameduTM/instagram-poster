"""
Background scheduler using APScheduler.

Job 1 (every SCHEDULER_INTERVAL_SECONDS): find pending posts whose
scheduled_time has arrived, and publish them.

Job 2 (once a day): refresh any account token that's getting close to its
60-day expiry, so it never goes stale.

This is what makes "scheduling" actually work — Instagram's API has no
"publish_at" parameter, so the app itself has to wake up and trigger the
publish at the right time.
"""
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler

import db
from config import Config
from instagram_api import InstagramAPI, InstagramAPIError

logger = logging.getLogger(__name__)
api = InstagramAPI()


def publish_due_posts():
    now_str = datetime.now(timezone.utc).isoformat()
    due = db.get_due_posts(now_str)
    if not due:
        return

    accounts = {a["id"]: a for a in db.get_all_accounts()}

    for post in due:
        db.update_post_status(post["id"], "processing")
        account = accounts.get(post["account_id"])
        if not account:
            db.update_post_status(post["id"], "failed", error_message="No connected account found")
            continue

        try:
            media_id, permalink, container_id = api.publish_post(
                ig_user_id=account["ig_user_id"],
                access_token=account["access_token"],
                media_url=post["media_url"],
                caption=post["caption"],
                media_type=post["media_type"],
            )
            db.update_post_status(
                post["id"],
                "published",
                container_id=container_id,
                ig_media_id=media_id,
                permalink=permalink,
            )
            logger.info("Published post %s -> media_id=%s", post["id"], media_id)
        except InstagramAPIError as e:
            logger.error("Failed to publish post %s: %s", post["id"], e)
            db.update_post_status(post["id"], "failed", error_message=str(e))
        except Exception as e:  # noqa: BLE001 - never let one bad post kill the scheduler
            logger.exception("Unexpected error publishing post %s", post["id"])
            db.update_post_status(post["id"], "failed", error_message=f"Unexpected error: {e}")


def refresh_expiring_tokens():
    accounts = db.get_all_accounts()
    soon = datetime.now(timezone.utc) + timedelta(days=5)

    for account in accounts:
        try:
            expires_at = datetime.fromisoformat(account["token_expires_at"])
        except (TypeError, ValueError):
            continue

        if expires_at > soon:
            continue  # not expiring soon, leave it alone

        try:
            result = api.refresh_long_lived_token(account["access_token"])
            new_expiry = datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])
            db.update_account_token(account["id"], result["access_token"], new_expiry.isoformat())
            logger.info("Refreshed token for account %s, new expiry %s", account["ig_user_id"], new_expiry)
        except InstagramAPIError as e:
            # If this fails, the token is too old/expired and needs a full
            # re-login via /auth/login — log loudly so it's noticed.
            logger.error(
                "Could not refresh token for account %s — user must re-authenticate. Error: %s",
                account["ig_user_id"], e,
            )


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        publish_due_posts,
        "interval",
        seconds=Config.SCHEDULER_INTERVAL_SECONDS,
        id="publish_due_posts",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        refresh_expiring_tokens,
        "interval",
        hours=24,
        id="refresh_expiring_tokens",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # also run once at startup
    )
    scheduler.start()
    return scheduler
