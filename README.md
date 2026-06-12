# NotifAI.Me Personalized News Platform

This is a beginner-friendly Python Flask news website and limited public demo.

## What it does

- Shows a general news feed
- Searches news by keyword
- Filters by country and category
- Lets users sign up and log in
- Lets users save feed preferences
- Shows a detail page with summary and original source link
- Collects article metadata into a local SQLite database
- Uses trusted source searches first, then GNews as backup
- Shows only headline, short description, source, date, image, and original link

## How to run it

Open a terminal inside this folder and run:

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:5055
```

## Add real news

1. Create a free API key at https://gnews.io/
2. Create a file named `.env` inside this project folder.
3. Add this line:

```text
GNEWS_API_KEY=paste-your-api-key-here
```

4. Start or restart the app:

```bash
python app.py
```

If you do not add an API key, the website still works with demo articles.

## Public demo deployment

Read `DEPLOYMENT.md`.

Recommended beginner deployment:

```text
Render + gunicorn + persistent disk
```

Required hosting environment variables:

```text
FLASK_ENV=production
SECRET_KEY=generate-a-long-random-secret
GNEWS_API_KEY=your-gnews-api-key
DATABASE_PATH=/data/news_platform.sqlite
ENABLE_DIAGNOSTICS=false
```

## Public demo limits

This is ready as a beginner demo, not a serious news business yet.

Before a serious launch, upgrade to:

- Managed auth
- PostgreSQL/Supabase database
- Scheduled collector
- Pagination
- Source-by-source legal review
- Better admin controls

## Files

- `app.py` contains the Python backend
- `sources.py` contains trusted news source domains
- `templates/` contains the website pages
- `static/styles.css` contains the design
- `instance/news_platform.sqlite` is created automatically for accounts and preferences
