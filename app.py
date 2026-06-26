"""
Entry point. Run with:  python app.py
"""
import os
import logging
from flask import Flask

from config import Config
import db
from scheduler import start_scheduler
from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.api import api_bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY

    db.init_db()
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    return app


app = create_app()

if __name__ == "__main__":
    # Avoid starting two schedulers when Flask's debug reloader spawns a
    # second process — only the reloader's main process gets WERKZEUG_RUN_MAIN.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        start_scheduler()

    if not Config.INSTAGRAM_APP_ID or not Config.INSTAGRAM_APP_SECRET:
        print(
            "\n*** WARNING: INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET are not set. "
            "Copy .env.example to .env and fill them in. ***\n"
        )

    app.run(host="0.0.0.0", port=5050, debug=True)
