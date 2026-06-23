"""
OAuth flow: /auth/login redirects to Instagram, /auth/callback receives the
code, trades it for tokens, and saves the connected account to the DB.
"""
import secrets
from datetime import datetime, timedelta, timezone
from flask import Blueprint, redirect, request, session, url_for, flash

import db
from instagram_api import InstagramAPI, InstagramAPIError

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
api = InstagramAPI()


@auth_bp.route("/login")
def login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return redirect(api.get_authorize_url(state))


@auth_bp.route("/callback")
def callback():
    # Instagram canceled / user denied
    if request.args.get("error"):
        flash(f"Instagram login was canceled: {request.args.get('error_description', 'unknown reason')}", "error")
        return redirect(url_for("dashboard.index"))

    code = request.args.get("code")
    returned_state = request.args.get("state")

    if not code:
        flash("No authorization code returned by Instagram.", "error")
        return redirect(url_for("dashboard.index"))

    if not returned_state or returned_state != session.get("oauth_state"):
        flash("State mismatch — possible CSRF attempt. Please try logging in again.", "error")
        return redirect(url_for("dashboard.index"))

    # Instagram appends a stray "#_" fragment sometimes — strip just in case
    code = code.split("#")[0]

    try:
        short_lived = api.exchange_code_for_token(code)
        long_lived = api.get_long_lived_token(short_lived["access_token"])
        info = api.get_account_info(long_lived["access_token"])

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=long_lived["expires_in"])

        db.save_account(
            ig_user_id=str(info["user_id"]),
            username=info.get("username"),
            access_token=long_lived["access_token"],
            token_expires_at=expires_at.isoformat(),
        )
        flash(f"Connected Instagram account @{info.get('username')}", "success")
    except InstagramAPIError as e:
        flash(f"Failed to connect Instagram account: {e}", "error")

    return redirect(url_for("dashboard.index"))
