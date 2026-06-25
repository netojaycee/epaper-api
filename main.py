from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import tempfile
import os
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from config import settings
from native_parser import IDMLNewsExtractor
from wordpress import post_to_wordpress, trash_wordpress_post, fetch_all_authors, fetch_all_categories, clear_cache

load_dotenv()

# ============================================================================
# COVER PAGE FILTER — filenames matching these patterns are skipped entirely
# (city editions / front pages should never be posted to WordPress)
# ============================================================================
_COVER_PATTERNS = [
    re.compile(r'lagos',           re.IGNORECASE),
    re.compile(r'abuja',           re.IGNORECASE),
    re.compile(r'port.?harcourt',  re.IGNORECASE),
    re.compile(r'\bph\b',          re.IGNORECASE),
]

def is_cover_page(filename: str) -> bool:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return any(p.search(stem) for p in _COVER_PATTERNS)


app = FastAPI(title="IDML News Extractor API", version="2.0.0")

# ============================================================================
# CORS
# ============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API KEY AUTHENTICATION MIDDLEWARE
# Reads REQUIRE_AUTH and API_KEY from .env
# Exempt: GET / and GET /health (so monitoring tools can reach them)
# ============================================================================
EXEMPT_PATHS = {"/", "/health"}

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if settings.require_auth and settings.api_key:
        if request.url.path not in EXEMPT_PATHS:
            key = (
                request.headers.get("X-API-Key") or
                request.query_params.get("api_key")
            )
            if key != settings.api_key:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or missing API key. Pass X-API-Key header."},
                )
    return await call_next(request)


# ============================================================================
# ROUTES
# ============================================================================

@app.get("/")
async def home():
    return {
        "message": "IDML News Extractor API v2",
        "endpoints": {
            "POST /extract-native/": "Upload IDML → extract articles → post to WordPress",
            "GET  /users":           "List all WordPress authors",
            "GET  /categories":      "List all WordPress categories",
            "POST /cache/clear":     "Refresh author/category cache",
            "GET  /health":          "Health check",
        },
        "auth": "Pass X-API-Key header when REQUIRE_AUTH=true",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "parser": "ready", "version": "2.0.0"}


@app.get("/users")
async def get_users():
    try:
        authors = fetch_all_authors()
        return {"success": True, "count": len(authors), "users": authors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching users: {e}")


@app.get("/categories")
async def get_categories():
    try:
        cat_data = fetch_all_categories()
        return {
            "success": True,
            "total_categories": len(cat_data.get("flat", {})),
            "parent_categories_count": len(cat_data.get("parent_categories", {})),
            "data": cat_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching categories: {e}")


@app.post("/cache/clear")
async def clear_cache_endpoint():
    try:
        clear_cache()
        return {"success": True, "message": "Cache cleared. Data will refresh on next request."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {e}")


@app.post("/extract-native/")
async def extract_native(
    file: UploadFile = File(...),
    trash_post_ids: Optional[str] = Form(None),
):
    """
    Main pipeline endpoint:
    1. Accept .idml upload
    2. If trash_post_ids supplied, move those WP drafts to Trash first (update flow)
    3. Parse: headlines, authors, category (from filename), content HTML, images
    4. Post each article to WordPress as draft (if WORDPRESS_ENABLE_POSTING=true)
    5. Return full results JSON including new post IDs for watcher to store
    """
    if not file.filename.lower().endswith(".idml"):
        raise HTTPException(status_code=400, detail="File must be an .idml file")

    if is_cover_page(file.filename):
        return {
            "success": False,
            "skipped": True,
            "reason": f"Cover/city-edition page ignored: {file.filename}",
        }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".idml") as tmp:
        tmp.write(await file.read())
        temp_path = tmp.name

    try:
        extractor = IDMLNewsExtractor(temp_path)
        extractor.original_filename = file.filename or ''
        articles = extractor.extract_news_articles()

        # ----------------------------------------------------------------
        # TRASH OLD DRAFTS (update flow — watcher sends previous post IDs)
        # ----------------------------------------------------------------
        trashed_ids = []
        if trash_post_ids and settings.wp_enable_posting:
            for pid_str in trash_post_ids.split(","):
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    if trash_wordpress_post(int(pid_str)):
                        trashed_ids.append(int(pid_str))

        # ----------------------------------------------------------------
        # POST TO WORDPRESS (only if enabled in .env)
        # ----------------------------------------------------------------
        posted = []
        wordpress_errors = []
        all_new_post_ids = []

        if settings.wp_enable_posting:
            for article in articles:
                content_html = article.get("content_html", "")
                if (
                    article.get("article_type") != "standalone_headline"
                    and content_html
                    and len(content_html) > 200
                ):
                    result = post_to_wordpress(article)
                    if result.get("success"):
                        all_new_post_ids.append(str(result.get("post_id")))
                        posted.append({
                            "headline": article["headline"],
                            "post_id": result.get("post_id"),
                            "slug": result.get("slug"),
                            "status": result.get("status"),
                            "link": result.get("link"),
                            "category": article.get("category", "unknown"),
                            "author": article.get("author", "unknown"),
                            "featured_media_id": result.get("featured_media_id"),
                        })
                    else:
                        wordpress_errors.append({
                            "headline": article["headline"],
                            "error": result.get("error"),
                        })
        else:
            print("[INFO] WORDPRESS_ENABLE_POSTING=false — skipping WordPress post")

        # ----------------------------------------------------------------
        # STRIP BINARY IMAGE DATA FROM RESPONSE (not serialisable as JSON)
        # ----------------------------------------------------------------
        for article in articles:
            article.pop("featured_image_bytes", None)

        # ----------------------------------------------------------------
        # ANALYTICS
        # ----------------------------------------------------------------
        grouped = {}
        for a in articles:
            t = a["article_type"]
            grouped.setdefault(t, []).append(a)

        articles_with_authors = [a for a in articles if a["author"]]
        unique_authors: set = set()
        multi_author_articles = []

        for a in articles_with_authors:
            author_text = a["author"]
            if " and " in author_text.lower():
                multi_author_articles.append({
                    "headline": a["headline"][:50],
                    "authors": author_text,
                })
                for name in re.split(r"\s+and\s+", author_text, flags=re.IGNORECASE):
                    clean = re.sub(r",.*$", "", name.strip())
                    if clean:
                        unique_authors.add(clean)
            else:
                clean = re.sub(r",.*$", "", author_text.strip())
                if clean:
                    unique_authors.add(clean)

        return {
            "success": True,
            "total_articles": len(articles),
            "articles_by_type": {k: len(v) for k, v in grouped.items()},
            "articles": articles,
            "wordpress": {
                "posting_enabled": settings.wp_enable_posting,
                "posted": len(posted),
                "failed": len(wordpress_errors),
                "post_ids": ",".join(all_new_post_ids),
                "trashed_ids": trashed_ids or None,
                "posted_articles": posted,
                "errors": wordpress_errors or None,
            },
            "summary": {
                "headlines_found": len([a for a in articles if a["headline"]]),
                "articles_with_authors": len(articles_with_authors),
                "total_unique_authors": len(unique_authors),
                "multi_author_articles": len(multi_author_articles),
                "images_extracted": len(extractor.extracted_images),
                "images_with_cartoon_filtered": len([
                    r for r in getattr(extractor, 'image_records', []) if r.get('is_cartoon')
                ]),
                "linked_images": getattr(extractor, 'linked_image_uris', []),
                "articles_with_html": len([a for a in articles if a.get("content_html")]),
                "total_html_paragraphs": sum(
                    a.get("metadata", {}).get("html_paragraph_count", 0) for a in articles
                ),
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing IDML: {e}")

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
