"""
Thin wrapper around the Instagram API with Instagram Login (Business Login).

Reference (verified against Meta's docs):
  Authorize:          GET  https://www.instagram.com/oauth/authorize
  Code -> short token: POST https://api.instagram.com/oauth/access_token
  Short -> long token: GET  https://graph.instagram.com/access_token
  Refresh long token:  GET  https://graph.instagram.com/refresh_access_token
  All other calls:     https://graph.instagram.com/<version>/...

Important gotcha: once you have a token, ALL Graph calls must go to
graph.instagram.com — NOT graph.facebook.com. Using the wrong host is the
most common "Invalid OAuth access token" error people hit with this API.
"""

import time
import requests
from urllib.parse import urlencode
from config import Config


class InstagramAPIError(Exception):
    """Raised for any non-2xx response or a graph API {error: ...} payload."""

    def __init__(self, message, response_json=None, status_code=None):
        super().__init__(message)
        self.response_json = response_json
        self.status_code = status_code

def _check(resp):
    try:
        data = resp.json()
    except ValueError:
        raise InstagramAPIError(
            f"Non-JSON response ({resp.status_code}): {resp.text[:300]}"
        )
    if resp.status_code >= 400 or "error" in data or "error_message" in data:
        raise InstagramAPIError(
            f"Instagram API error: {data}",
            response_json=data,
            status_code=resp.status_code,
        )
    return data


class InstagramAPI:
    def __init__(self, app_id=None, app_secret=None, redirect_uri=None):
        self.app_id = app_id or Config.INSTAGRAM_APP_ID
        self.app_secret = app_secret or Config.INSTAGRAM_APP_SECRET
        self.redirect_uri = redirect_uri or Config.REDIRECT_URI
        self.graph_host = Config.GRAPH_HOST
        self.version = Config.GRAPH_API_VERSION

    # ---------------------------------------------------------------- auth --

    def get_authorize_url(self, state):
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": Config.SCOPES,
            "state": state,
        }
        return f"{Config.OAUTH_AUTHORIZE_HOST}/oauth/authorize?{urlencode(params)}"

    def exchange_code_for_token(self, code):
        """Authorization code -> short-lived token (valid ~1 hour)."""
        resp = requests.post(
            f"{Config.OAUTH_TOKEN_HOST}/oauth/access_token",
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
            timeout=15,
        )
        data = _check(resp)
        # Some accounts get back {"data": [{...}]}, others get the object directly.
        if "data" in data and isinstance(data["data"], list):
            data = data["data"][0]
        return data  # {access_token, user_id, permissions}

    def get_long_lived_token(self, short_lived_token):
        """Short-lived token -> long-lived token (valid 60 days)."""
        resp = requests.get(
            f"{self.graph_host}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.app_secret,
                "access_token": short_lived_token,
            },
            timeout=15,
        )
        return _check(resp)  # {access_token, token_type, expires_in}

    def refresh_long_lived_token(self, long_lived_token):
        """
        Refresh a long-lived token for another 60 days.
        Only works if the token is >= 24h old and not yet expired.
        """
        resp = requests.get(
            f"{self.graph_host}/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": long_lived_token,
            },
            timeout=15,
        )
        return _check(resp)  # {access_token, token_type, expires_in}

    def get_account_info(self, access_token):
        resp = requests.get(
            f"{self.graph_host}/me",
            params={
                "fields": "user_id,username,account_type",
                "access_token": access_token,
            },
            timeout=15,
        )
        return _check(resp)

    # --------------------------------------------------------- publishing --

    def create_media_container(
        self, ig_user_id, access_token, media_url, caption, media_type="IMAGE"
    ):
        """
        Step 1 of publishing: tell Instagram where your media lives.
        media_type: IMAGE | VIDEO | REELS
        media_url must be a PUBLICLY reachable URL (no auth, no localhost).

        Stories notes:
          - Captions are not supported (silently ignored by Instagram).
          - Stories expire after 24 hours — that's a platform limit, not an API one.
          - Recommended aspect ratio: 9:16 (1080x1920). Images must be JPEG.
          - Video stories: MP4, up to 60 seconds.
        """
        payload = {
            "caption": caption or "",
            "access_token": access_token,
        }
        if media_type == "IMAGE":
            payload["image_url"] = media_url
        elif media_type in ("VIDEO", "REELS"):
            payload["video_url"] = media_url
            payload["media_type"] = media_type
        elif media_type == "STORIES_IMAGE":
            # Stories use media_type=STORIES + image_url; captions are ignored.
            payload["image_url"] = media_url
            payload["media_type"] = "STORIES"
        elif media_type == "STORIES_VIDEO":
            payload["video_url"] = media_url
            payload["media_type"] = "STORIES"
        else:
            raise ValueError(f"Unsupported media_type: {media_type}")

        resp = requests.post(
            f"{self.graph_host}/{self.version}/{ig_user_id}/media",
            data=payload,
            timeout=30,
        )
        data = _check(resp)
        return data["id"]  # container id

    def get_container_status(self, container_id, access_token):
        resp = requests.get(
            f"{self.graph_host}/{self.version}/{container_id}",
            params={"fields": "status_code,status", "access_token": access_token},
            timeout=15,
        )
        return _check(resp)  # {status_code: IN_PROGRESS|FINISHED|ERROR|EXPIRED, ...}

    def wait_for_container_ready(self, container_id, access_token, media_type="IMAGE"):
        """
        Polls container status until FINISHED, ERROR, or EXPIRED.
        Images are usually instant; video/reels can take a while to process.
        """
        max_attempts = 6 if media_type == "IMAGE" else 60
        delay_seconds = 5 if media_type == "IMAGE" else 10

        for _ in range(max_attempts):
            status = self.get_container_status(container_id, access_token)
            code = status.get("status_code")
            if code == "FINISHED":
                return True
            if code in ("ERROR", "EXPIRED"):
                raise InstagramAPIError(f"Container {container_id} failed: {status}")
            time.sleep(delay_seconds)

        raise InstagramAPIError(
            f"Container {container_id} timed out waiting to process"
        )

    def publish_container(self, ig_user_id, access_token, container_id):
        resp = requests.post(
            f"{self.graph_host}/{self.version}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=30,
        )
        data = _check(resp)
        return data["id"]  # published media id

    def get_permalink(self, media_id, access_token):
        resp = requests.get(
            f"{self.graph_host}/{self.version}/{media_id}",
            params={"fields": "permalink", "access_token": access_token},
            timeout=15,
        )
        data = _check(resp)
        return data.get("permalink")

    def publish_post(
        self, ig_user_id, access_token, media_url, caption, media_type="IMAGE"
    ):
        """
        Full end-to-end publish: create container -> wait until ready -> publish.
        Returns (media_id, permalink, container_id).
        """
        container_id = self.create_media_container(
            ig_user_id, access_token, media_url, caption, media_type
        )
        self.wait_for_container_ready(container_id, access_token, media_type)
        media_id = self.publish_container(ig_user_id, access_token, container_id)
        permalink = None
        try:
            permalink = self.get_permalink(media_id, access_token)
        except InstagramAPIError:
            pass  # not critical — the post is already live
        return media_id, permalink, container_id
