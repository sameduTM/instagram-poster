# Instagram Auto-Poster (Flask)

A complete, self-hosted Instagram automation tool: connect an Instagram
Business/Creator account, upload media, schedule posts, and let a background
job publish them automatically — with token refresh handled for you.

Built on **Instagram API with Instagram Login** (the "Business Login" flow),
Meta's current official API for Business/Creator accounts. It does **not**
require linking a Facebook Page, which makes setup noticeably simpler than
the older Facebook-Login-based Graph API flow.

---

## How it actually works (read this first)

Instagram's API has **no native "schedule for later"** for regular
posts/reels. Every scheduler you've ever seen (including this one) works the
same way under the hood:

1. You save the post + a future time in a database.
2. A background job wakes up periodically (here: every 60 seconds, configurable).
3. When a post's time has arrived, the app calls Instagram's publish API *right then*.

Publishing itself is a 2-step "container" process:
1. `POST /{ig-user-id}/media` — tell Instagram the public URL of your image/video. This creates a "container" and returns a `container_id`.
2. `POST /{ig-user-id}/media_publish` — publish that container with `creation_id={container_id}`.

For video, Instagram needs time to process the file, so the app polls
`GET /{container_id}?fields=status_code` until it reports `FINISHED` before
publishing.

**Critical constraint:** Instagram downloads your media from a public URL.
It cannot reach `localhost`. For local testing you need a tunnel like
[ngrok](https://ngrok.com/) (`ngrok http 5000`), and you must set `BASE_URL`
in `.env` to that public tunnel URL. In production, deploy this app
somewhere with a real public domain.

---

## 1. Set up your Meta App (one-time)

1. Make sure your Instagram account is a **Business or Creator** account
   (Settings → Account type in the Instagram app). Personal accounts cannot
   use this API at all.
2. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create App** → choose the **Business** app type.
3. In your app's dashboard, find **Instagram** in the left sidebar → **API setup with Instagram login**.
4. Under **3. Set up Instagram business login**:
   - Add a redirect URI: `http://localhost:5000/auth/callback` (or your tunnel URL + `/auth/callback`)
   - Copy your **Instagram App ID** and **Instagram App Secret**
5. Add yourself as an **Instagram tester** in the App Dashboard (Roles →
   Instagram testers) and accept the invite from within the Instagram app
   (Settings → Apps and Websites → Tester invites). This is required while
   your app is in development mode.
6. While in development mode you can only post to accounts you've added as
   testers/admins. To post to other people's accounts you'll need to submit
   the app for **App Review** (specifically the `instagram_business_content_publish`
   permission) — budget 2-4 weeks for this.

## 2. Install & configure

```bash
cd instagram-poster
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# now edit .env and fill in INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET
```

## 3. Run it

```bash
python app.py
```

Visit `http://localhost:5000`, click **Connect Instagram Account**, and log in.

If testing locally, open a second terminal and run:
```bash
ngrok http 5000
```
Copy the `https://xxxx.ngrok-free.app` URL into `BASE_URL` in `.env`, restart
the app, and also add `https://xxxx.ngrok-free.app/auth/callback` as a
redirect URI in the App Dashboard.

## 4. Post something

In the dashboard:
1. Upload an image (JPEG only — PNG/WebP are rejected by Instagram) or a video.
2. Paste the resulting public URL into the "Schedule a post" form (or click "upload" — it autofills).
3. Pick a time, or leave it blank to publish on the next scheduler tick (~60s).
4. Click **Schedule Post**.

Or via the JSON API (handy for cron jobs / other scripts):

```bash
curl -X POST http://localhost:5000/api/posts \
  -H "Content-Type: application/json" \
  -d '{
        "media_url": "https://your-public-host.com/photo.jpg",
        "caption": "Posted automatically",
        "media_type": "IMAGE",
        "scheduled_time": "2026-06-22T15:00:00+00:00"
      }'
```

`GET /api/posts`, `DELETE /api/posts/<id>`, and `POST /api/posts/<id>/publish-now` are also available.

---

## Token lifecycle (handled automatically)

- OAuth gives you a short-lived token (1 hour) → exchanged immediately for a long-lived token (60 days).
- A daily background job (`scheduler.py: refresh_expiring_tokens`) refreshes
  any token expiring within 5 days, extending it another 60 days.
- A long-lived token can only be refreshed if it's **at least 24 hours old**
  and **not yet expired**. If a token is allowed to fully expire, there's no
  recovery — the user has to click "Connect Instagram Account" again.

## Instagram's content rules to know about

- **Images:** JPEG only. Aspect ratio between 4:5 (portrait) and 1.91:1 (landscape); square is fine.
- **Videos:** MP4, H.264 recommended. 3–60 seconds for feed video; Reels support up to 15 minutes.
- **Captions:** up to 2,200 characters. No bold/italic/markdown.
- **Rate limit:** 100 API-published posts per rolling 24-hour period per account.
- Containers expire after 24 hours if not published.

## Project structure

```
instagram-poster/
├── app.py                 # Flask app factory + entry point
├── config.py               # env-based settings
├── db.py                   # SQLite data layer (accounts, scheduled_posts)
├── instagram_api.py        # All Instagram Graph API calls live here
├── scheduler.py             # APScheduler background jobs (publish + token refresh)
├── blueprints/
│   ├── auth.py              # OAuth login/callback
│   ├── dashboard.py          # HTML UI routes
│   └── api.py                # JSON REST API
├── templates/index.html
├── static/uploads/          # uploaded media is served from here
├── requirements.txt
└── .env.example
```

## Extending this

- **Carousels** (multi-image posts): create multiple `IMAGE` containers with
  `is_carousel_item=true`, then create one more container with
  `media_type=CAROUSEL` and `children=<comma-separated container ids>`,
  then publish that one.
- **Cloud storage for uploads:** swap the local `static/uploads` folder for
  S3/Cloudinary so `BASE_URL` doesn't depend on your server being reachable —
  this also removes the ngrok requirement entirely.
- **Multiple accounts:** the `accounts` table already supports more than one
  row; you'd add an account picker to the UI and an `account_id` selector
  when scheduling a post.
- **Production deployment:** run behind gunicorn, move `SECRET_KEY` and
  tokens-at-rest to something encrypted, and consider Celery + Redis instead
  of APScheduler if you need the scheduler to survive across multiple worker
  processes.
