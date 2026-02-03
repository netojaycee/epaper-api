import requests
from typing import Dict, Any, Optional, List
import logging
from difflib import SequenceMatcher
from config import settings

# Configure logging with console handler
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler if not already present
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)s - %(name)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# WordPress Configuration (loaded from environment variables)
WP_URL = settings.wp_url
WP_USER = settings.wp_user
WP_APP_PASSWORD = settings.wp_password
WP_CATEGORIES_URL = settings.wp_categories_url
WP_AUTHORS_URL = settings.wp_authors_url

# Cache for categories and authors
_CATEGORIES_CACHE = None
_AUTHORS_CACHE = None

def similarity_ratio(a: str, b: str) -> float:
    """Calculate similarity between two strings (0-1)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def fetch_all_categories() -> Dict[str, Any]:
    """
    Fetch all WordPress categories dynamically with parent-child relationships
    
    Returns:
        Dict with structure: {
            'flat': {category_name_lower: category_id},
            'hierarchical': {parent_id: {child_name_lower: child_id}},
            'all_categories': {category_id: {name, parent, id}},
            'parent_categories': {parent_name_lower: parent_id}
        }
    """
    global _CATEGORIES_CACHE
    
    if _CATEGORIES_CACHE is not None:
        return _CATEGORIES_CACHE
    
    try:
        logger.info("Fetching categories from WordPress with parent-child relationships...")
        r = requests.get(WP_CATEGORIES_URL, timeout=10, auth=(WP_USER, WP_APP_PASSWORD))
        r.raise_for_status()
        
        categories_data = r.json()
        flat = {}  # All categories by name
        hierarchical = {}  # Parent ID -> {child_name: child_id}
        all_categories = {}  # Category ID -> full data
        parent_categories = {}  # Parent category names
        
        for cat in categories_data:
            cat_id = cat["id"]
            cat_name = cat["name"].lower()
            parent_id = cat.get("parent", 0)
            
            # Store in flat and all_categories
            flat[cat_name] = cat_id
            all_categories[cat_id] = {
                "name": cat["name"],
                "parent": parent_id,
                "id": cat_id
            }
            
            # If it's a parent category (parent_id == 0), store it
            if parent_id == 0:
                parent_categories[cat_name] = cat_id
            else:
                # If it's a child, organize by parent
                if parent_id not in hierarchical:
                    hierarchical[parent_id] = {}
                hierarchical[parent_id][cat_name] = cat_id
        
        _CATEGORIES_CACHE = {
            'flat': flat,
            'hierarchical': hierarchical,
            'all_categories': all_categories,
            'parent_categories': parent_categories
        }
        
        logger.info(f"✓ Fetched {len(flat)} total categories from WordPress")
        logger.info(f"  Parent categories: {len(parent_categories)}")
        logger.info(f"  Parent categories list: {parent_categories}")
        return _CATEGORIES_CACHE
    except Exception as e:
        logger.error(f"Failed to fetch categories: {str(e)}")
        return {
            'flat': {},
            'hierarchical': {},
            'all_categories': {},
            'parent_categories': {}
        }

def fetch_all_authors() -> Dict[str, int]:
    """
    Fetch all WordPress authors dynamically with proper pagination
    
    Returns:
        Dict mapping author name to ID
    """
    global _AUTHORS_CACHE
    
    if _AUTHORS_CACHE is not None:
        return _AUTHORS_CACHE
    
    try:
        logger.info("Fetching authors from WordPress...")
        authors = {}
        page = 1
        per_page = 100
        
        # Fetch all pages with pagination
        # Use authentication to ensure we get all users with list_users capability
        while True:
            url = f"{WP_AUTHORS_URL.split('?')[0]}?per_page={per_page}&page={page}&orderby=name"
            logger.debug(f"  Fetching page {page}: {url}")
            # IMPORTANT: Add authentication to ensure proper user capability filtering
            r = requests.get(url, auth=(WP_USER, WP_APP_PASSWORD), timeout=10)
            r.raise_for_status()
            
            page_authors = r.json()
            if not page_authors:
                break  # No more authors to fetch
            
            for author in page_authors:
                # Try multiple fields for author name
                display_name = (
                    author.get("name", "") or 
                    author.get("username", "") or 
                    author.get("email", "")
                ).lower().strip()
                
                if display_name:
                    user_id = author.get("id")
                    authors[display_name] = user_id
                    logger.debug(f"    Added author: {display_name} (ID: {user_id})")
            
            # Check if there are more pages
            if len(page_authors) < per_page:
                break
            page += 1
        
        _AUTHORS_CACHE = authors
        logger.info(f"✓ Fetched {len(authors)} authors from WordPress")
        logger.info(f"  Authors: {authors}")
        return authors
    except Exception as e:
        logger.error(f"Failed to fetch authors: {str(e)}")
        return {}

def get_category_id(article_category: str) -> int:
    """
    Map extracted category to WordPress category ID with hierarchical matching
    
    Strategy:
    1. Try exact match on sub-categories (child categories)
    2. Try fuzzy match on sub-categories
    3. Try exact match on parent categories
    4. Try fuzzy match on parent categories
    5. If no match, create new category under the best matching parent
    6. If no category provided, use Uncategorized (ID: 1)
    
    Args:
        article_category: Category detected from IDML markers
        
    Returns:
        WordPress category ID
    """
    if not article_category:
        logger.warning("No category provided in article, using Uncategorized (ID: 1)")
        return 1
    
    logger.info(f"Matching category: '{article_category}'")
    cat_data = fetch_all_categories()
    if not cat_data or not cat_data.get('flat'):
        logger.warning("No categories fetched from WordPress, using Uncategorized (ID: 1)")
        return 1
    
    category_lower = article_category.lower().strip()
    logger.info(f"Looking for category (normalized): '{category_lower}'")
    
    flat_categories = cat_data['flat']
    hierarchical = cat_data['hierarchical']
    parent_categories = cat_data['parent_categories']
    
    # ========================================================================
    # STEP 1: Try exact match on all categories (including sub-categories)
    # ========================================================================
    if category_lower in flat_categories:
        cat_id = flat_categories[category_lower]
        logger.info(f"✓ Exact match found: '{article_category}' → Category ID: {cat_id}")
        return cat_id
    
    # ========================================================================
    # STEP 2: Try fuzzy match on sub-categories first (highest priority)
    # ========================================================================
    best_sub_match = None
    best_sub_score = 0.6
    best_sub_category = None
    
    # Check all subcategories (from hierarchical structure)
    for parent_id, subcats in hierarchical.items():
        for subcat_name, subcat_id in subcats.items():
            score = similarity_ratio(category_lower, subcat_name)
            logger.debug(f"  Comparing (subcat) '{category_lower}' vs '{subcat_name}': score={score:.2f}")
            if score > best_sub_score:
                best_sub_score = score
                best_sub_match = subcat_id
                best_sub_category = subcat_name
    
    if best_sub_match:
        logger.info(f"✓ Fuzzy matched (sub-category): '{article_category}' → '{best_sub_category}' (ID: {best_sub_match}, score: {best_sub_score:.2f})")
        return best_sub_match
    
    # ========================================================================
    # STEP 3: Try exact match on parent categories
    # ========================================================================
    if category_lower in parent_categories:
        cat_id = parent_categories[category_lower]
        logger.info(f"✓ Exact match found (parent): '{article_category}' → Category ID: {cat_id}")
        return cat_id
    
    # ========================================================================
    # STEP 4: Try fuzzy match on parent categories
    # ========================================================================
    best_parent_match = None
    best_parent_score = 0.6
    best_parent_category = None
    
    for parent_name, parent_id in parent_categories.items():
        score = similarity_ratio(category_lower, parent_name)
        logger.debug(f"  Comparing (parent) '{category_lower}' vs '{parent_name}': score={score:.2f}")
        if score > best_parent_score:
            best_parent_score = score
            best_parent_match = parent_id
            best_parent_category = parent_name
    
    if best_parent_match:
        logger.info(f"✓ Fuzzy matched (parent): '{article_category}' → '{best_parent_category}' (ID: {best_parent_match}, score: {best_parent_score:.2f})")
        return best_parent_match
    
    # ========================================================================
    # STEP 5: Create new category under best matching parent
    # ========================================================================
    logger.info(f"✗ No exact or fuzzy match found for '{article_category}'")
    
    # Find the best matching parent to use as parent for new category
    parent_for_new_cat = None
    if parent_categories:
        # Try to find best parent match
        best_parent_for_new = None
        best_parent_new_score = 0.4  # Lower threshold for parent selection
        
        for parent_name, parent_id in parent_categories.items():
            score = similarity_ratio(category_lower, parent_name)
            if score > best_parent_new_score:
                best_parent_new_score = score
                best_parent_for_new = parent_id
        
        parent_for_new_cat = best_parent_for_new
    
    try:
        logger.info(f"  Creating new category '{article_category}' in WordPress...")
        new_cat_payload = {
            "name": article_category,
            "slug": article_category.lower().replace(" ", "-")
        }
        
        # If found a suitable parent, use it
        if parent_for_new_cat:
            new_cat_payload["parent"] = parent_for_new_cat
            logger.info(f"    Parent category ID: {parent_for_new_cat}")
        
        r = requests.post(
            WP_CATEGORIES_URL.split('?')[0],
            json=new_cat_payload,
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=10
        )
        
        r.raise_for_status()
        new_cat = r.json()
        new_cat_id = new_cat.get("id")
        
        logger.info(f"✓ Successfully created new category: '{article_category}' (ID: {new_cat_id})")
        
        # Clear cache to pick up new category
        clear_cache()
        
        return new_cat_id
        
    except requests.exceptions.RequestException as e:
        logger.error(f"✗ Failed to create new category '{article_category}': {str(e)}")
        logger.warning(f"  Falling back to Uncategorized (ID: 1)")
        return 1

def parse_author_string(author_string: str) -> List[str]:
    """
    Parse author string to extract individual author names
    
    Supports multiple delimiters:
    - "and" (case-insensitive): "John and Jane"
    - "&": "John & Jane"
    - ",": "John, Jane"
    - Mix: "John and Jane, Bob"
    
    Args:
        author_string: Raw author string from article
        
    Returns:
        List of cleaned author names
    """
    if not author_string:
        return []
    
    # Split by common delimiters
    import re
    
    # Replace "&" with "and"
    text = author_string.replace("&", "and")
    
    # Split by "and" (case-insensitive)
    authors = re.split(r'\s+and\s+', text, flags=re.IGNORECASE)
    
    # Further split by commas
    final_authors = []
    for author in authors:
        parts = author.split(",")
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                final_authors.append(cleaned)
    
    logger.debug(f"Parsed author string '{author_string}' → {final_authors}")
    return final_authors


def get_author_id(author_name: str) -> int:
    """
    Map extracted author name to WordPress author ID using fuzzy matching
    
    Args:
        author_name: Author name extracted from article
        
    Returns:
        WordPress author ID (defaults to jaycee user if not found)
    """
    if not author_name:
        logger.warning("No author provided in article, using default author: Agency Report")
        return get_default_author_id()
    
    logger.info(f"Matching author: '{author_name}'")
    authors = fetch_all_authors()
    if not authors:
        logger.warning("No authors fetched from WordPress, using default author: Agency Report")
        return get_default_author_id()
    
    author_lower = author_name.lower().strip()
    logger.info(f"Looking for author (normalized): '{author_lower}'")
    
    # Exact match first
    if author_lower in authors:
        author_id = authors[author_lower]
        logger.info(f"✓ Exact match found: '{author_name}' → Author ID: {author_id}")
        return author_id
    
    # Fuzzy match - find best matching author
    best_match = None
    best_score = 0.6  # Minimum threshold
    best_wp_author = None
    
    for wp_author, author_id in authors.items():
        score = similarity_ratio(author_lower, wp_author)
        logger.debug(f"  Comparing '{author_lower}' vs '{wp_author}': score={score:.2f}")
        if score > best_score:
            best_score = score
            best_match = author_id
            best_wp_author = wp_author
    
    if best_match:
        logger.info(f"✓ Fuzzy matched: '{author_name}' ({author_lower}) → '{best_wp_author}' (ID: {best_match}, score: {best_score:.2f})")
        return best_match
    
    default_id = get_default_author_id()
    logger.warning(f"✗ No author match found for '{author_name}', using default author: Agency Report (ID: {default_id})")
    return default_id


def get_author_ids(author_string: str) -> List[int]:
    """
    Parse author string and return list of matched WordPress author IDs
    
    Flexible function to handle:
    - Single author: "John Smith"
    - Multiple authors with "and": "John Smith and Jane Doe"
    - Multiple authors with "&": "John Smith & Jane Doe"
    - Multiple authors with commas: "John Smith, Jane Doe, Bob Jones"
    - Mixed delimiters: "John and Jane, Bob"
    - Any number of authors
    
    Args:
        author_string: Raw author string from article (can be single or multiple authors)
        
    Returns:
        List of WordPress author IDs (at minimum returns default author if none found)
    """
    if not author_string:
        logger.warning("No authors provided, using default author: Agency Report")
        return [get_default_author_id()]
    
    logger.info(f"Matching multiple authors from: '{author_string}'")
    
    # Parse the author string to get individual names
    author_names = parse_author_string(author_string)
    
    if not author_names:
        logger.warning("No author names extracted, using default author: Agency Report")
        return [get_default_author_id()]
    
    logger.info(f"Found {len(author_names)} author(s): {author_names}")
    
    # Get IDs for each author
    author_ids = []
    matched_authors = []
    unmatched_authors = []
    
    for author_name in author_names:
        author_id = get_author_id(author_name)
        # Check if this is the default ID (meaning no match found)
        default_id = get_default_author_id()
        
        if author_id == default_id and author_name.lower().strip() != 'jaycee':
            # This author wasn't matched
            unmatched_authors.append(author_name)
        else:
            matched_authors.append((author_name, author_id))
        
        author_ids.append(author_id)
    
    # Remove duplicates while preserving order
    author_ids = list(dict.fromkeys(author_ids))
    
    logger.info(f"✓ Matched {len(matched_authors)} author(s)")
    for name, aid in matched_authors:
        logger.info(f"  - {name} (ID: {aid})")
    
    if unmatched_authors:
        logger.warning(f"⚠ Could not match {len(unmatched_authors)} author(s): {unmatched_authors}")
    
    return author_ids if author_ids else [get_default_author_id()]


def get_default_author_id() -> int:
    """Get the default author ID (Agency Report user)"""
    authors = fetch_all_authors()
    # Try to find 'agency report' user
    if 'agency report' in authors:
        return authors['agency report']
    # Otherwise return first author or 1
    return 1


def post_to_wordpress(article: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post article to WordPress automatically with category and multiple author support
    
    Args:
        article: Article dict with headline, content_html, category, author, etc.
        
    Returns:
        Dict with post_id, status, author_ids list, or error details
    """
    try:
        headline = article.get("headline", "Untitled")
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing article: {headline}")
        logger.info(f"  Extracted category: '{article.get('category', 'N/A')}'")
        logger.info(f"  Extracted author(s): '{article.get('author', 'N/A')}'")
        
        # Get category ID from article's category field
        category_id = get_category_id(article.get("category", ""))
        
        # Get author IDs from article's author field (supports multiple authors)
        author_ids = get_author_ids(article.get("author", ""))
        
        # Prepare payload for WordPress
        # Note: WordPress REST API typically accepts 'author' as single ID or list
        # We'll set the first author as primary and add co-authors if supported
        payload = {
            "title": headline,
            "content": article.get("content_html", ""),
            "status": "draft",  # Start as draft for review
            "categories": [category_id],
            "author": author_ids[0] if author_ids else get_default_author_id()
        }
        
        logger.info(f"\n→ Posting to WordPress:")
        logger.info(f"  Title: {headline}")
        logger.info(f"  Category ID: {category_id}")
        logger.info(f"  Primary Author ID: {payload['author']}")
        
        if len(author_ids) > 1:
            logger.info(f"  Co-author IDs: {author_ids[1:]}")
        
        # Post to WordPress
        r = requests.post(
            WP_URL,
            json=payload,
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=60
        )
        
        r.raise_for_status()
        response_data = r.json()
        post_id = response_data.get("id")
        
        logger.info(f"✓ Successfully posted to WordPress!")
        logger.info(f"  Post ID: {post_id}")
        logger.info(f"  Status: {response_data.get('status')}")
        logger.info(f"  Link: {response_data.get('link')}")
        
        # If there are co-authors, try to add them via post meta or custom handling
        # This depends on your WordPress setup - you might use plugins or custom meta
        if len(author_ids) > 1:
            logger.info(f"  Additional authors (co-authors): {author_ids[1:]}")
            # Note: WordPress REST API doesn't have native co-author support
            # You may need to:
            # 1. Use a co-authors plugin and add via custom endpoint
            # 2. Store in post meta
            # 3. Use a custom solution
            # For now, we log them for manual or plugin-based handling
        
        logger.info(f"{'='*80}\n")
        
        return {
            "success": True,
            "post_id": post_id,
            "status": response_data.get("status"),
            "link": response_data.get("link"),
            "category_id": category_id,
            "primary_author_id": payload['author'],
            "all_author_ids": author_ids,
            "author_count": len(author_ids)
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"✗ WordPress API error: {str(e)}")
        logger.info(f"{'='*80}\n")
        return {
            "success": False,
            "error": f"Failed to post to WordPress: {str(e)}"
        }
    except Exception as e:
        logger.error(f"✗ Unexpected error posting to WordPress: {str(e)}")
        logger.info(f"{'='*80}\n")
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }


def clear_cache():
    """Clear categories and authors cache"""
    global _CATEGORIES_CACHE, _AUTHORS_CACHE
    _CATEGORIES_CACHE = None
    _AUTHORS_CACHE = None
    logger.info("Cleared WordPress categories and authors cache")
