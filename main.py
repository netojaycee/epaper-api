from fastapi import FastAPI, UploadFile, File, HTTPException
import tempfile
import os
import re
from typing import List, Dict, Any
from dotenv import load_dotenv

from config import settings
from native_parser import IDMLNewsExtractor
from wordpress import post_to_wordpress, fetch_all_authors, fetch_all_categories, clear_cache

# Load environment variables from .env file
load_dotenv()

app = FastAPI()


# ============================================================================
# NOTE: IDMLNewsExtractor class moved to native_parser.py
# This file now serves as the API endpoint router only
# ============================================================================

@app.get("/")
async def home():
    return {
        "message": "IDML News Extractor API",
        "endpoints": {
            "/extract-native/": "Regex-based extraction (fast, consistent)",
            "/users": "Get all WordPress users",
            "/categories": "Get all WordPress categories",
            "/cache/clear": "Clear categories and authors cache (call when users are added)",
            "/health": "Check API status"
        }
    }


@app.get("/users")
async def get_users():
    """
    Get all WordPress users/authors
    
    Returns cached list of authors. If you've added new users to WordPress,
    call /cache/clear first to refresh the cache.
    """
    try:
        authors = fetch_all_authors()
        return {
            "success": True,
            "count": len(authors),
            "users": authors
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching users: {str(e)}")


@app.get("/categories")
async def get_categories():
    """
    Get all WordPress categories with parent-child hierarchy
    
    Returns:
    - flat: All categories indexed by name (for quick lookup)
    - parent_categories: Parent categories only
    - hierarchical: Parent ID -> {child_name: child_id}
    - all_categories: Full details for each category
    
    If you've added new categories to WordPress, call /cache/clear first to refresh.
    """
    try:
        cat_data = fetch_all_categories()
        return {
            "success": True,
            "total_categories": len(cat_data.get('flat', {})),
            "parent_categories_count": len(cat_data.get('parent_categories', {})),
            "data": cat_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching categories: {str(e)}")


@app.post("/cache/clear")
async def clear_cache_endpoint():
    """
    Clear the categories and authors cache
    
    Call this endpoint after adding new users or categories to WordPress
    to ensure they appear in subsequent requests.
    """
    try:
        clear_cache()
        return {
            "success": True,
            "message": "Cache cleared successfully. Users and categories will be refetched on next request."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")


@app.get("/health")
async def health():
    """Check API health"""
    return {
        "status": "healthy",
        "native_parser": "ready"
    }


@app.post("/extract-native/")
async def extract_native(file: UploadFile = File(...)):
    """
    Extract news articles using NATIVE regex-based parser
    
    NATIVE PARSER FEATURES:
    - Fast regex-based extraction
    - Consistent results
    - No external dependencies
    - Good for single/dual authors
    
    Returns:
    - Extracted articles with headlines, authors, content, category
    - Plain text and formatted HTML content
    - Detailed metadata and statistics
    """
    
    if not file.filename.lower().endswith('.idml'):
        raise HTTPException(status_code=400, detail="File must be an IDML file")
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.idml') as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_path = temp_file.name
    
    try:
        extractor = IDMLNewsExtractor(temp_path)
        articles = extractor.extract_news_articles()
        
        # ====================================================================
        # POST ARTICLES TO WORDPRESS
        # ====================================================================
        posted = []
        wordpress_errors = []
        
        for article in articles:
            if article.get("content_html"):
                result = post_to_wordpress(article)
                if result.get("success"):
                    posted.append({
                        "headline": article["headline"],
                        "post_id": result.get("post_id"),
                        "status": result.get("status"),
                        "link": result.get("link"),
                        "category": article.get("category", "unknown"),
                        "author": article.get("author", "unknown")
                    })
                else:
                    wordpress_errors.append({
                        "headline": article["headline"],
                        "error": result.get("error")
                    })
        
        # ====================================================================
        # ANALYTICS AND RESPONSE
        # ====================================================================
        
        # Group articles by type for better analysis
        grouped_articles = {}
        for article in articles:
            article_type = article['article_type']
            if article_type not in grouped_articles:
                grouped_articles[article_type] = []
            grouped_articles[article_type].append(article)
        
        # Calculate detailed author statistics
        articles_with_authors = [a for a in articles if a['author']]
        total_unique_authors = set()
        multi_author_articles = []
        
        for article in articles_with_authors:
            author_text = article['author']
            # Check for multiple authors (look for "and" pattern)
            if ' and ' in author_text.lower():
                multi_author_articles.append({
                    'headline': article['headline'][:50] + '...' if len(article['headline']) > 50 else article['headline'],
                    'authors': author_text
                })
                # Split and count individual authors
                author_names = re.split(r'\s+and\s+', author_text, flags=re.IGNORECASE)
                for name in author_names:
                    clean_name = re.sub(r',.*$', '', name.strip())  # Remove location part
                    if clean_name:
                        total_unique_authors.add(clean_name)
            else:
                # Single author
                clean_name = re.sub(r',.*$', '', author_text.strip())
                if clean_name:
                    total_unique_authors.add(clean_name)
        
        return {
            "success": True,
            "total_articles": len(articles),
            "articles_by_type": {k: len(v) for k, v in grouped_articles.items()},
            "articles": articles,
            "wordpress": {
                "posted": len(posted),
                "failed": len(wordpress_errors),
                "posted_articles": posted,
                "errors": wordpress_errors if wordpress_errors else None
            },
            "summary": {
                "headlines_found": len([a for a in articles if a['headline']]),
                "articles_with_authors": len(articles_with_authors),
                "total_unique_authors": len(total_unique_authors),
                "multi_author_articles": len(multi_author_articles),
                "content_pieces": len([a for a in articles if a['content']]),
                
                # Rich text formatting statistics
                "formatting_stats": {
                    "articles_with_html": len([a for a in articles if a.get('content_html')]),
                    "total_html_paragraphs": sum(a.get('metadata', {}).get('html_paragraph_count', 0) for a in articles),
                    "wordpress_ready": True  # All articles now have HTML content for WordPress
                },
                
                "author_details": {
                    "single_author_articles": len(articles_with_authors) - len(multi_author_articles),
                    "multi_author_articles": multi_author_articles if multi_author_articles else []
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing IDML file: {str(e)}")
    
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)
