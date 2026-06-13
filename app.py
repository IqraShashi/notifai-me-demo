import os
import re
import secrets
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import json
import xml.etree.ElementTree as ET

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from sources import TRUSTED_SOURCES


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()

app = Flask(__name__)
IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production" or os.environ.get("ENV") == "production"
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set before running NotifAI.Me in production.")

app.config["SECRET_KEY"] = SECRET_KEY or "dev-only-change-this-secret-key"
app.config["DATABASE"] = os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "news_platform.sqlite"))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

COUNTRIES = {
    "bd": "Bangladesh",
    "us": "United States",
    "gb": "United Kingdom",
    "in": "India",
    "ca": "Canada",
    "au": "Australia",
}

COUNTRY_SEARCH_TERMS = {
    "bd": "Bangladesh",
    "us": "United States",
    "gb": "United Kingdom",
    "in": "India",
    "ca": "Canada",
    "au": "Australia",
}

COUNTRY_LANG_FALLBACKS = {
    "bd": ["en", "bn"],
    "in": ["en", "hi"],
}

CATEGORIES = {
    "general": "General",
    "education": "Education",
    "business": "Business",
    "entertainment": "Entertainment",
    "health": "Health",
    "sports": "Sports",
    "politics": "Politics",
    "science": "Science",
    "technology": "Technology",
    "world": "World",
}

GNEWS_DIRECT_CATEGORIES = {
    "general": "general",
    "business": "business",
    "entertainment": "entertainment",
    "health": "health",
    "sports": "sports",
    "science": "science",
    "technology": "technology",
    "world": "world",
}

CATEGORY_KEYWORDS = {
    "education": [
        "education",
        "school",
        "university",
        "college",
        "student",
        "teacher",
        "exam",
        "admission",
        "scholarship",
        "campus",
        "curriculum",
        "classroom",
    ],
    "politics": [
        "politics",
        "government",
        "minister",
        "parliament",
        "election",
        "vote",
        "party",
        "policy",
        "law",
        "president",
        "prime minister",
    ],
}

CATEGORY_QUERY_TERMS = {
    "education": "education OR university OR school OR students OR exams OR admission OR scholarship",
    "politics": "politics OR government OR election OR parliament OR minister OR policy",
}

STRICT_CATEGORY_QUERY_TERMS = {
    "education": "education university school students exams admission scholarship",
    "politics": "politics government election parliament minister policy",
}

SOURCE_CATEGORY_QUERIES = {
    "education": "(education OR university OR school OR students OR exams OR admission OR scholarship)",
    "politics": "(politics OR government OR election OR parliament OR minister OR policy)",
    "business": "(business OR economy OR market OR trade OR bank OR finance)",
    "technology": "(technology OR tech OR AI OR startup OR software OR internet)",
    "sports": "(sports OR cricket OR football OR match OR tournament)",
    "entertainment": "(entertainment OR film OR music OR celebrity OR drama)",
    "health": "(health OR hospital OR doctor OR medicine OR disease)",
    "science": "(science OR research OR climate OR space)",
    "world": "(world OR international OR global)",
}

DEMO_ARTICLES = [
    {
        "title": "Welcome to your personalized news platform",
        "description": "This demo article appears until you add a real GNews API key. The website structure is already working.",
        "url": "https://gnews.io/",
        "image": "",
        "source": "Demo News",
        "published_at": "Today",
    },
    {
        "title": "Search, country filters, and category filters are ready",
        "description": "Use the controls at the top to search by keyword, choose a country, or choose a category.",
        "url": "https://docs.gnews.io/",
        "image": "",
        "source": "Project Guide",
        "published_at": "Today",
    },
    {
        "title": "Create an account to customize your feed",
        "description": "After signing up, choose your preferred countries, categories, and keywords to build your own feed.",
        "url": "https://flask.palletsprojects.com/",
        "image": "",
        "source": "Local App",
        "published_at": "Today",
    },
]

NEWS_CACHE = {}
CACHE_SECONDS = 600


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_forms():
    if request.method == "POST":
        expected = session.get("csrf_token")
        submitted = request.form.get("csrf_token")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            abort(400)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def init_db():
    os.makedirs(app.instance_path, exist_ok=True)
    database_dir = os.path.dirname(app.config["DATABASE"])
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS preferences (
            user_id INTEGER PRIMARY KEY,
            countries TEXT NOT NULL DEFAULT '',
            categories TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            image TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'general',
            published_at TEXT NOT NULL,
            collected_at TEXT NOT NULL
        );
        """
    )
    db.commit()


@app.before_request
def load_logged_in_user():
    if request.endpoint == "static":
        return

    init_db()
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def split_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def unique_articles(articles, limit=12):
    seen = set()
    unique = []

    for article in articles:
        key = article.get("url") or article.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
        if len(unique) >= limit:
            break

    return unique


def save_articles(articles, country="", category="general"):
    if not articles:
        return 0

    db = get_db()
    saved = 0
    for article in articles:
        if not article.get("url") or article.get("url") == "#":
            continue

        cursor = db.execute(
            """
            INSERT OR IGNORE INTO articles
                (title, description, url, image, source, country, category, published_at, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.get("title", "Untitled article"),
                article.get("description", "No summary is available for this article."),
                article.get("url", "#"),
                article.get("image", ""),
                article.get("source", "Unknown source"),
                country,
                category,
                article.get("published_at", "Unknown date"),
                datetime.utcnow().isoformat(),
            ),
        )
        saved += cursor.rowcount

    db.commit()
    return saved


def row_to_article(row):
    return {
        "title": row["title"],
        "description": row["description"],
        "url": row["url"],
        "image": row["image"],
        "source": row["source"],
        "published_at": row["published_at"],
    }


def search_saved_articles(keyword="", country="", category="general", limit=12):
    keyword = keyword.strip()
    clauses = []
    params = []

    if country:
        clauses.append("country = ?")
        params.append(country)

    if category and category != "general":
        clauses.append("category = ?")
        params.append(category)

    if keyword:
        clauses.append("(title LIKE ? OR description LIKE ? OR source LIKE ?)")
        search_term = f"%{keyword}%"
        params.extend([search_term, search_term, search_term])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = get_db().execute(
        f"""
        SELECT title, description, url, image, source, published_at
        FROM articles
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [row_to_article(row) for row in rows]


def normalize_article(article):
    source = article.get("source") or {}
    return {
        "title": article.get("title") or "Untitled article",
        "description": article.get("description") or "No summary is available for this article.",
        "url": article.get("url") or "#",
        "image": article.get("image") or "",
        "source": source.get("name") or "Unknown source",
        "published_at": format_date(article.get("publishedAt")),
    }


def format_date(value):
    if not value:
        return "Unknown date"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%b %d, %Y")
    except ValueError:
        return value


def request_gnews(endpoint, params):
    cache_key = f"{endpoint}?{urlencode(sorted(params.items()))}"
    cached = NEWS_CACHE.get(cache_key)
    now = datetime.utcnow().timestamp()
    if cached and now - cached["time"] < CACHE_SECONDS:
        return cached["articles"]

    with urlopen(f"{endpoint}?{urlencode(params)}", timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    articles = [normalize_article(article) for article in data.get("articles", [])]
    NEWS_CACHE[cache_key] = {"time": now, "articles": articles}
    return articles


def strip_html(value):
    return re.sub(r"<[^>]+>", " ", value or "").strip()


def format_rss_date(value):
    if not value:
        return "Unknown date"
    try:
        return parsedate_to_datetime(value).strftime("%b %d, %Y")
    except Exception:
        return value


def rss_text(element, name):
    child = element.find(name)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def source_matches_country(source, country):
    if not country:
        return True
    if country == "bd":
        return source["country"] == "bd"
    return source["country"] == "international"


def google_news_rss_url(source, keyword, country, category):
    terms = [f"site:{source['domain']}"]
    if country:
        terms.append(COUNTRY_SEARCH_TERMS.get(country, country))
    if category != "general":
        terms.append(SOURCE_CATEGORY_QUERIES.get(category, category))
    if keyword:
        terms.append(keyword)

    params = {
        "q": " ".join(terms),
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"https://news.google.com/rss/search?{urlencode(params)}"


def request_source_feed(source, keyword, country, category):
    url = google_news_rss_url(source, keyword, country, category)
    cache_key = f"source:{url}"
    cached = NEWS_CACHE.get(cache_key)
    now = datetime.utcnow().timestamp()
    if cached and now - cached["time"] < CACHE_SECONDS:
        return cached["articles"]

    with urlopen(url, timeout=10) as response:
        root = ET.fromstring(response.read())

    articles = []
    for item in root.findall("./channel/item"):
        title = rss_text(item, "title")
        title = title.rsplit(" - ", 1)[0] if " - " in title else title
        article = {
            "title": title or "Untitled article",
            "description": strip_html(rss_text(item, "description")) or "No summary is available for this article.",
            "url": rss_text(item, "link") or "#",
            "image": "",
            "source": source["name"],
            "published_at": format_rss_date(rss_text(item, "pubDate")),
        }
        articles.append(article)

    NEWS_CACHE[cache_key] = {"time": now, "articles": articles}
    return articles


def fetch_source_news(keyword="", country="", category="general", limit=12):
    articles = []
    matching_sources = [source for source in TRUSTED_SOURCES if source_matches_country(source, country)]

    for source in matching_sources:
        try:
            articles.extend(request_source_feed(source, keyword, country, category))
        except Exception:
            continue

        articles = unique_articles(articles, limit * 2)
        if len(articles) >= limit:
            break

    if category != "general":
        articles = filter_by_category(articles, category)

    return unique_articles(articles, limit)


def article_text(article):
    return " ".join(
        [
            article.get("title", ""),
            article.get("description", ""),
            article.get("source", ""),
        ]
    ).lower()


def filter_by_category(articles, category):
    keywords = CATEGORY_KEYWORDS.get(category, [])
    if not keywords:
        return articles

    matching = []
    for article in articles:
        text = article_text(article)
        if any(keyword in text for keyword in keywords):
            matching.append(article)

    return matching


def build_search_query(keyword, country, category):
    parts = []
    if country:
        parts.append(COUNTRY_SEARCH_TERMS.get(country, country))
    if category != "general":
        parts.append(CATEGORY_QUERY_TERMS.get(category, category))
    if keyword:
        parts.append(keyword)
    return " ".join(parts)


def build_strict_search_query(keyword, country, category):
    parts = []
    if country:
        parts.append(COUNTRY_SEARCH_TERMS.get(country, country))
    if category != "general":
        parts.append(STRICT_CATEGORY_QUERY_TERMS.get(category, category))
    if keyword:
        parts.append(keyword)
    return " ".join(parts)


def readable_api_error(error):
    if isinstance(error, HTTPError):
        try:
            data = json.loads(error.read().decode("utf-8"))
            errors = data.get("errors")
            if isinstance(errors, list) and errors:
                return f"GNews error: {errors[0]}"
        except Exception:
            pass
        return f"GNews returned HTTP {error.code}."
    return f"{type(error).__name__}: {error}"


def fetch_news(keyword="", country="", category="general", limit=12, show_message=True):
    load_local_env()
    keyword = keyword.strip()
    country = country.strip()
    category = category.strip() or "general"

    saved_articles = search_saved_articles(keyword=keyword, country=country, category=category, limit=limit)
    if len(saved_articles) >= limit:
        return saved_articles

    source_articles = fetch_source_news(keyword=keyword, country=country, category=category, limit=limit)
    if source_articles:
        save_articles(source_articles, country=country, category=category)
        return unique_articles(saved_articles + source_articles, limit)

    api_key = os.environ.get("GNEWS_API_KEY", "").strip()
    if not api_key:
        if show_message:
            flash("No source articles found and no GNews API key found yet. Showing demo news.")
        return DEMO_ARTICLES

    try:
        articles = []
        query_parts = []
        should_use_search = keyword or category in CATEGORY_QUERY_TERMS or country == "bd"
        if should_use_search:
            query = build_search_query(keyword, country, category)
            query_parts.append(query)

        if query_parts:
            endpoint = "https://gnews.io/api/v4/search"
            params = {"q": " ".join(query_parts), "lang": "en", "max": limit, "apikey": api_key}
            if country and country != "bd":
                params["country"] = country
            articles = request_gnews(endpoint, params)
            category_matches = filter_by_category(articles, category)
            if category_matches:
                save_articles(category_matches, country=country, category=category)
                return category_matches
        else:
            endpoint = "https://gnews.io/api/v4/top-headlines"
            params = {
                "category": GNEWS_DIRECT_CATEGORIES.get(category, "general"),
                "lang": "en",
                "max": limit,
                "apikey": api_key,
            }
            if country:
                params["country"] = country
            articles = request_gnews(endpoint, params)

        if articles:
            category_matches = filter_by_category(articles, category)
            if category != "general":
                if category_matches:
                    save_articles(category_matches, country=country, category=category)
                    return category_matches
            else:
                save_articles(articles, country=country, category=category)
                return articles

        fallback_terms = []
        fallback_query = build_search_query(keyword, country, category)
        if fallback_query:
            fallback_terms.append(fallback_query)

        if fallback_terms:
            search_params = {
                "q": " ".join(fallback_terms),
                "lang": "en",
                "max": limit,
                "apikey": api_key,
            }
            articles = request_gnews("https://gnews.io/api/v4/search", search_params)
            category_matches = filter_by_category(articles, category)
            if category != "general" and category_matches:
                save_articles(category_matches, country=country, category=category)
                return category_matches
            if category == "general" and articles:
                save_articles(articles, country=country, category=category)
                return articles

        strict_query = build_strict_search_query(keyword, country, category)
        if strict_query and strict_query != fallback_query:
            strict_params = {
                "q": strict_query,
                "lang": "en",
                "max": limit,
                "apikey": api_key,
            }
            articles = request_gnews("https://gnews.io/api/v4/search", strict_params)
            category_matches = filter_by_category(articles, category)
            if category_matches:
                save_articles(category_matches, country=country, category=category)
                return category_matches

        for language in COUNTRY_LANG_FALLBACKS.get(country, [])[1:]:
            if category not in GNEWS_DIRECT_CATEGORIES:
                continue
            language_params = {
                "category": GNEWS_DIRECT_CATEGORIES.get(category, "general"),
                "lang": language,
                "country": country,
                "max": limit,
                "apikey": api_key,
            }
            articles = request_gnews("https://gnews.io/api/v4/top-headlines", language_params)
            category_matches = filter_by_category(articles, category)
            if category != "general" and category_matches:
                save_articles(category_matches, country=country, category=category)
                return category_matches
            if category == "general" and articles:
                save_articles(articles, country=country, category=category)
                return articles

        return []
    except Exception as error:
        if show_message:
            flash(f"Real news could not be loaded right now. {readable_api_error(error)}")
        return []


def collect_latest_news(keyword="", country="", category="general", limit=20):
    keyword = keyword.strip()
    country = country.strip()
    category = category.strip() or "general"
    articles = fetch_source_news(keyword=keyword, country=country, category=category, limit=limit)

    if not articles:
        api_key = os.environ.get("GNEWS_API_KEY", "").strip()
        if api_key:
            articles = fetch_news(keyword=keyword, country=country, category=category, limit=limit, show_message=False)

    return save_articles(articles, country=country, category=category)


@app.route("/api-status")
def api_status():
    if os.environ.get("ENABLE_DIAGNOSTICS") != "true":
        abort(404)

    load_local_env()
    api_key = os.environ.get("GNEWS_API_KEY", "").strip()
    country = request.args.get("country", "us")
    category = request.args.get("category", "general")
    status = {
        "key_found": bool(api_key),
        "key_length": len(api_key),
        "connected": False,
        "article_count": 0,
        "country": country,
        "category": category,
        "message": "No API key found. Check that the file is named .env, not .env.txt.",
    }

    if api_key:
        params = urlencode({"category": category, "lang": "en", "country": country, "max": 3, "apikey": api_key})
        try:
            with urlopen(f"https://gnews.io/api/v4/top-headlines?{params}", timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
            status["connected"] = True
            status["article_count"] = len(data.get("articles", []))
            status["message"] = "GNews connected successfully."
        except HTTPError as error:
            try:
                body = error.read().decode("utf-8")
            except Exception:
                body = ""
            status["message"] = f"GNews returned HTTP {error.code}. {body[:220]}"
        except URLError as error:
            status["message"] = f"Network error: {error.reason}"
        except Exception as error:
            status["message"] = f"{type(error).__name__}: {error}"

    return status


def fetch_personalized_news(countries, categories, keywords, limit=12):
    countries = countries or ["us"]
    categories = categories or ["general"]
    keyword_query = " ".join(keywords[:2])
    articles = []

    for country in countries[:3]:
        for category in categories[:3]:
            remaining = limit - len(unique_articles(articles, limit))
            if remaining <= 0:
                break
            batch = fetch_news(
                keyword=keyword_query,
                country=country,
                category=category,
                limit=min(5, remaining),
                show_message=False,
            )
            articles.extend(batch)

    return unique_articles(articles, limit) or DEMO_ARTICLES


@app.route("/")
def index():
    keyword = request.args.get("q", "")
    country = request.args.get("country", "")
    category = request.args.get("category", "general")
    articles = fetch_news(keyword=keyword, country=country, category=category)
    if not articles:
        flash("No matching articles were found for this country/category yet. Try another category or search keyword.")

    return render_template(
        "index.html",
        articles=articles,
        countries=COUNTRIES,
        categories=CATEGORIES,
        selected_country=country,
        selected_category=category,
        keyword=keyword,
        page_title="NotifAI.Me",
    )


@app.route("/collect", methods=("POST",))
@login_required
def collect():
    keyword = request.form.get("q", "")
    country = request.form.get("country", "")
    category = request.form.get("category", "general")
    saved_count = collect_latest_news(keyword=keyword, country=country, category=category)

    if saved_count:
        flash(f"Collected {saved_count} new article(s) into your local database.")
    else:
        flash("No new articles were found for this filter right now.")

    return redirect(url_for("index", q=keyword, country=country, category=category))


@app.route("/my-feed")
@login_required
def my_feed():
    pref = get_db().execute("SELECT * FROM preferences WHERE user_id = ?", (g.user["id"],)).fetchone()
    countries = split_csv(pref["countries"]) if pref else []
    categories = split_csv(pref["categories"]) if pref else []
    keywords = split_csv(pref["keywords"]) if pref else []

    country = countries[0] if countries else "us"
    category = categories[0] if categories else "general"
    keyword = " ".join(keywords[:2])
    articles = fetch_personalized_news(countries, categories, keywords)

    return render_template(
        "index.html",
        articles=articles,
        countries=COUNTRIES,
        categories=CATEGORIES,
        selected_country=country,
        selected_category=category,
        keyword=keyword,
        page_title="My Feed",
    )


@app.route("/article")
def article_detail():
    article = {
        "title": request.args.get("title", "Untitled article"),
        "description": request.args.get("description", "No summary is available."),
        "url": request.args.get("url", "#"),
        "image": request.args.get("image", ""),
        "source": request.args.get("source", "Unknown source"),
        "published_at": request.args.get("published_at", "Unknown date"),
    }
    return render_template("article.html", article=article)


@app.route("/about")
def about():
    return render_template("about.html", page_title="About NotifAI.Me")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", page_title="Privacy")


@app.route("/signup", methods=("GET", "POST"))
def signup():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        error = None

        if not email:
            error = "Email is required."
        elif not password:
            error = "Password is required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."

        if error is None:
            try:
                db = get_db()
                cursor = db.execute(
                    "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                db.execute("INSERT INTO preferences (user_id) VALUES (?)", (cursor.lastrowid,))
                db.commit()
            except sqlite3.IntegrityError:
                error = "An account with this email already exists."
            else:
                flash("Account created. Please log in.")
                return redirect(url_for("login"))

        flash(error)

    return render_template("signup.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("my_feed"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/preferences", methods=("GET", "POST"))
@login_required
def preferences():
    db = get_db()

    if request.method == "POST":
        selected_countries = ",".join(request.form.getlist("countries"))
        selected_categories = ",".join(request.form.getlist("categories"))
        keywords = request.form.get("keywords", "").strip()
        db.execute(
            """
            INSERT INTO preferences (user_id, countries, categories, keywords)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                countries = excluded.countries,
                categories = excluded.categories,
                keywords = excluded.keywords
            """,
            (g.user["id"], selected_countries, selected_categories, keywords),
        )
        db.commit()
        flash("Preferences saved.")
        return redirect(url_for("my_feed"))

    pref = db.execute("SELECT * FROM preferences WHERE user_id = ?", (g.user["id"],)).fetchone()
    selected_countries = split_csv(pref["countries"]) if pref else []
    selected_categories = split_csv(pref["categories"]) if pref else []
    keywords = pref["keywords"] if pref else ""

    return render_template(
        "preferences.html",
        countries=COUNTRIES,
        categories=CATEGORIES,
        selected_countries=selected_countries,
        selected_categories=selected_categories,
        keywords=keywords,
    )


@app.errorhandler(404)
def not_found(error):
    return render_template("message.html", page_title="Page not found", title="Page not found", message="That page is not available."), 404


@app.errorhandler(500)
def server_error(error):
    return render_template("message.html", page_title="Something went wrong", title="Something went wrong", message="Please try again in a moment."), 500


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5055")),
        debug=not IS_PRODUCTION,
    )
