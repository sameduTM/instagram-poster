"""
Central configuration, loaded from environment variables (.env file).
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- Meta App credentials ---
    # Find these in: Meta App Dashboard > Instagram > API setup with Instagram login
    #   > 3. Set up Instagram business login > Business login settings
    INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID")
    INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")

    # Must exactly match a "Valid OAuth Redirect URI" registered in the App Dashboard
    REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI", "http://localhost:5000/auth/callback")

    # Public base URL of THIS app. Instagram's servers must be able to reach
    # BASE_URL/static/uploads/<file> over the public internet to fetch your media.
    # Locally this means you need a tunnel (e.g. ngrok) — see README.
    BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

    # Permissions requested from the user during OAuth.
    # instagram_business_basic is required for everything else to work.
    SCOPES = "instagram_business_basic,instagram_business_content_publish"

    GRAPH_API_VERSION = "v22.0"
    GRAPH_HOST = "https://graph.instagram.com"
    OAUTH_AUTHORIZE_HOST = "https://www.instagram.com"
    OAUTH_TOKEN_HOST = "https://api.instagram.com"

    DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "app.db"))
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")

    # How often (seconds) the background scheduler checks for due posts
    SCHEDULER_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-this-in-production")

    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB upload limit
