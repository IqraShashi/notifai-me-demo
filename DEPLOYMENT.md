# Deploy NotifAI.Me Demo

This is a limited public demo setup. It is not a full production news business yet.

## Recommended beginner host

Use Render for the first demo because this Flask app can run with `gunicorn` and a small persistent disk.

## Required environment variables

Set these in the hosting dashboard:

```text
FLASK_ENV=production
SECRET_KEY=generate-a-long-random-secret
GNEWS_API_KEY=your-gnews-api-key
DATABASE_PATH=/data/news_platform.sqlite
ENABLE_DIAGNOSTICS=false
```

## Render settings

If using the included `render.yaml`, Render can read most settings automatically.

Manual settings:

```text
Build command: pip install -r requirements.txt
Start command: gunicorn app:app
```

Add a persistent disk:

```text
Mount path: /data
Size: 1 GB
```

## Before sharing publicly

- Keep `.env` private.
- Do not upload `instance/` or the local SQLite database unless you intentionally want that data online.
- Show only headline, short description, source, date, image, and original link.
- Review source terms before using the app beyond a demo.
- Use a managed auth/database service before treating this as a serious public product.
