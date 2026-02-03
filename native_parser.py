"""
NATIVE IDML NEWS EXTRACTOR
Regex-based extraction with full formatting support and debug logging

This is the current production-grade parser that uses:
- Regular expressions for author/category detection
- Font size heuristics for content classification
- HTML formatting preservation from InDesign layout
"""

import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import re


class IDMLNewsExtractor:
    """
    IDML News Extractor with Rich Text Formatting Support
    
    This class processes InDesign Markup Language (IDML) files to extract news articles
    with preserved formatting for WordPress integration.
    
    KEY FEATURES:
    1. Extracts headlines, authors, and content from newspaper layouts
    2. Preserves formatting (bold, italic, font sizes) as HTML
    3. Generates WordPress-ready content with proper HTML tags
    4. Handles multiple authors per article
    5. Matches headlines with corresponding body content
    
    OUTPUT FORMATS:
    - Plain text (backward compatible)
    - Rich HTML (WordPress ready with <p>, <strong>, <em>, <h3>, <h4> tags)
    """
    
    def __init__(self, idml_file_path: str):
        self.idml_path = idml_file_path
        self.namespace = {'idPkg': 'http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging'}
    
    def extract_news_articles(self) -> List[Dict[str, Any]]:
        """
        Extract news articles with headlines, authors, and content
        
        PROCESS:
        1. Parse all stories in IDML and identify marker stories
        2. Marker stories: exactly 1 paragraph, 1 char range, 1 content element
        3. Category formed by FIRST CONSECUTIVE sequence of markers
        4. Multiple markers in sequence = concatenated (e.g., '247' + 'Business' = '247Business')
        5. Apply detected category to all other stories
        6. Filter out marker stories from final results
        
        EXAMPLE PATTERNS:
        - Single marker: 'news'
        - Multi-marker: '247' + 'Business' = '247Business'
        - Multi-marker: 'capital' + 'market' = 'capitalmarket'
        """
        all_stories = []
        detected_category = ''
        marker_story_ids = set()
        
        with zipfile.ZipFile(self.idml_path, 'r') as zip_file:
            story_files = sorted([f for f in zip_file.namelist() if f.startswith('Stories/Story_')])
            
            print(f"\n[DEBUG] Total story files found: {len(story_files)}")
            
            # FIRST PASS: Scan for ALL marker stories and their positions
            all_markers = []  # List of (index, story_id, content)
            for i, story_file in enumerate(story_files):
                try:
                    story_content = zip_file.read(story_file)
                    root = ET.fromstring(story_content)
                    story_id = root.find('.//Story').get('Self', '')
                    
                    # Check if this is a category marker story
                    if self._is_category_marker(root):
                        part = self._extract_category_from_story(root)
                        if part:
                            all_markers.append((i, story_id, part))
                            print(f"[DEBUG] Found marker at position {i}: '{part}' (story_id: {story_id})")
                
                except Exception as e:
                    print(f"[DEBUG] Error scanning story {i}: {e}")
                    continue
            
            # Extract first CONSECUTIVE sequence of markers as category
            if all_markers:
                category_parts = []
                expected_next_index = 0  # We want markers at positions 0, 1, 2, ...
                
                for marker_index, story_id, content in all_markers:
                    if marker_index == expected_next_index:
                        # This is a consecutive marker
                        category_parts.append(content)
                        marker_story_ids.add(story_id)
                        print(f"[DEBUG] Adding to category: '{content}'")
                        expected_next_index += 1
                    else:
                        # Gap found, stop collecting category markers
                        print(f"[DEBUG] Gap detected at position {marker_index} (expected {expected_next_index}), stopping category collection")
                        break
                
                if category_parts:
                    detected_category = ''.join(category_parts)
                    print(f"[DEBUG] ✓ Final category: '{detected_category}'")
                else:
                    print(f"[DEBUG] ✗ No consecutive markers from start found")
            else:
                print(f"[DEBUG] ✗ No marker stories detected in entire IDML")
            
            # SECOND PASS: Extract articles (excluding markers)
            for story_file in story_files:
                try:
                    story_content = zip_file.read(story_file)
                    article_data = self._parse_news_story(story_content, story_file)
                    
                    if article_data and article_data.get('raw_content'):
                        # Skip category marker stories
                        if article_data.get('story_id') not in marker_story_ids:
                            # Apply detected category to article
                            if detected_category and not article_data.get('category'):
                                article_data['category'] = detected_category
                            all_stories.append(article_data)
                        else:
                            print(f"[DEBUG] Filtering out category marker: {article_data['story_id']}")
                except Exception as e:
                    print(f"Error parsing {story_file}: {e}")
                    continue
        
        print(f"[DEBUG] Processing complete. Articles: {len(all_stories)}, Category: '{detected_category}'\n")
        
        # Match headlines with body content and create complete articles
        return self._match_headlines_with_content(all_stories)
    
    def extract_from_xml_file(self, xml_file_path: str) -> Optional[Dict[str, Any]]:
        """Extract from a single XML story file (for batch processing)"""
        try:
            with open(xml_file_path, 'rb') as f:
                xml_content = f.read()
            return self._parse_news_story(xml_content, xml_file_path)
        except Exception as e:
            print(f"Error parsing {xml_file_path}: {e}")
            return None
    
    def _parse_news_story(self, xml_content: bytes, filename: str) -> Optional[Dict[str, Any]]:
        """Parse individual story XML and extract structured content"""
        try:
            root = ET.fromstring(xml_content)
            
            # Extract category first (if present as simple content)
            category = self._extract_category_from_story(root)
            
            # Extract all content elements with their formatting and structure
            content_data = []
            paragraphs = []
            
            # Parse by paragraph to maintain structure
            # KEY FIX: Track which ParagraphStyleRange each element belongs to
            para_ranges = root.findall(".//ParagraphStyleRange")
            
            para_range_index = 0
            for para_range in para_ranges:
                para_range_index += 1
                para_content = []
                
                # Get all content within this paragraph, including line breaks  
                char_ranges = para_range.findall(".//CharacterStyleRange")
                
                for char_range in char_ranges:
                    # Handle both Content elements and Br (line break) elements
                    for child in char_range:
                        if child.tag == 'Content' and child.text:
                            text_content = child.text.strip()
                            if text_content:
                                # Get formatting information
                                font_size_str = char_range.get('PointSize', '12')
                                try:
                                    font_size = float(font_size_str)
                                except (ValueError, TypeError):
                                    font_size = 12.0
                                    
                                font_style = char_range.get('FontStyle', 'Regular')
                                is_bold = 'Bold' in font_style
                                is_italic = 'Italic' in font_style
                                
                                # FIX: Store the paragraph range index to properly separate paragraphs
                                content_item = {
                                    'text': text_content,
                                    'font_size': font_size,
                                    'font_style': font_style,
                                    'is_bold': is_bold,
                                    'is_italic': is_italic,
                                    'applied_style': char_range.get('AppliedCharacterStyle', ''),
                                    'paragraph_style': para_range.get('AppliedParagraphStyle', ''),
                                    'paragraph_range_index': para_range_index  # Track which ParagraphStyleRange this came from
                                }
                                content_data.append(content_item)
                                para_content.append(text_content)
                        
                        elif child.tag == 'Br':
                            # Handle line breaks within paragraphs
                            if para_content:  # Only add if we have content
                                paragraphs.append(' '.join(para_content))
                                para_content = []
                
                # Add any remaining content in this paragraph
                if para_content:
                    paragraphs.append(' '.join(para_content))
            
            if not content_data:
                return None
                
            raw_content = ' '.join(paragraphs)
            full_text = '\n'.join(paragraphs)  # Preserve paragraph structure
                
            return {
                'story_id': root.find('.//Story').get('Self', ''),
                'filename': filename,
                'content_elements': content_data,
                'raw_content': raw_content,
                'full_text': full_text,
                'paragraphs': paragraphs,
                'category': category
            }
            
        except ET.ParseError as e:
            print(f"XML Parse error in {filename}: {e}")
            return None
    
    def _extract_category_from_story(self, root: ET.Element) -> str:
        """
        Extract category from story XML
        
        CATEGORY MARKER DETECTION (IMPROVED):
        A category marker story has:
        1. EXACTLY 1 ParagraphStyleRange element
        2. That paragraph contains EXACTLY 1 CharacterStyleRange
        3. That range contains EXACTLY 1 Content element (no other content)
        4. The content value is the category name (e.g., 'news', 'metro', 'business')
        
        Examples:
        - Story_u184ec.xml: <Content>news</Content> (News IDML marker)
        - Story_uf768.xml: <Content>metro</Content> (DAP IDML marker)
        
        This approach is much more reliable than pattern matching.
        """
        # STEP 1: Check if this is a category marker story
        para_ranges = root.findall(".//ParagraphStyleRange")
        
        # Marker stories have exactly 1 paragraph
        if len(para_ranges) == 1:
            para_range = para_ranges[0]
            char_ranges = para_range.findall(".//CharacterStyleRange")
            
            # Marker stories have exactly 1 character range per paragraph
            if len(char_ranges) == 1:
                char_range = char_ranges[0]
                contents = char_range.findall("Content")
                
                # Marker stories have exactly 1 content element
                if len(contents) == 1:
                    content = contents[0]
                    
                    if content.text:
                        category_text = content.text.strip()
                        
                        # Validate: short, no special chars, looks like category
                        if (len(category_text) > 0 and 
                            len(category_text) <= 30 and  # Reasonable length for category
                            not category_text.startswith('\n') and  # Not empty/whitespace
                            self._is_valid_category(category_text)):
                            
                            print(f"[DEBUG] Detected CATEGORY MARKER: '{category_text}'")
                            return category_text
        
        return ''
    
    def _is_category_marker(self, root: ET.Element) -> bool:
        """
        Check if a story XML is a category marker story
        
        Category marker stories have:
        1. EXACTLY 1 ParagraphStyleRange element (not 2+)
        2. EXACTLY 1 CharacterStyleRange per paragraph
        3. EXACTLY 1 Content element (no other content)
        4. Very short content (< 30 chars)
        
        This is much more reliable than regex/pattern matching on content.
        """
        para_ranges = root.findall(".//ParagraphStyleRange")
        
        # Must have exactly 1 paragraph
        if len(para_ranges) != 1:
            return False
        
        para_range = para_ranges[0]
        char_ranges = para_range.findall(".//CharacterStyleRange")
        
        # Must have exactly 1 character range
        if len(char_ranges) != 1:
            return False
        
        char_range = char_ranges[0]
        contents = char_range.findall("Content")
        
        # Must have exactly 1 content element
        if len(contents) != 1:
            return False
        
        # Content must be short and valid
        content = contents[0]
        if content.text:
            text = content.text.strip()
            if len(text) > 0 and len(text) <= 30:
                return True
        
        return False
    
    def _is_valid_category(self, text: str) -> bool:
        """
        Check if text is a valid category name
        
        Valid categories:
        - Single word: 'metro', 'news', 'sports'
        - Multi-word with spaces: 'front page', 'inside story'
        - May contain hyphens: 'metro-news'
        - Must contain at least one letter (rejects pure numbers like '5', '37')
        """
        # Remove extra whitespace
        text = text.strip()
        
        if not text:
            return False
        
        # CRITICAL: Must contain at least one letter
        # This rejects page numbers (5, 37) and numeric IDs
        if not any(c.isalpha() for c in text):
            print(f"[DEBUG] Rejected category '{text}' - no letters found (likely a number/ID)")
            return False
        
        # Allow letters, numbers, spaces, hyphens, underscores
        # This covers: metro, news, front page, metro-news, etc.
        allowed_pattern = r'^[a-zA-Z0-9\s\-_&,\.]+$'
        
        if not re.match(allowed_pattern, text):
            return False
        
        # Minimum 1 character, maximum 30 (reasonable for category names)
        if len(text) < 1 or len(text) > 30:
            return False
        
        # Avoid common false positives (email, URLs, etc.)
        if '@' in text or 'http' in text.lower():
            return False
        
        return True
    
    def _match_headlines_with_content(self, all_stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Match headlines with their corresponding body content"""
        headlines = []
        body_stories = []
        
        # Separate headlines from body content
        for story in all_stories:
            if self._is_metadata_content(story['raw_content']):
                continue
                
            content_type = self._determine_story_type(story)
            
            if content_type == 'headline':
                headlines.append(story)
            elif content_type == 'body_content':
                body_stories.append(story)
        
        # Match headlines with body content
        matched_articles = []
        used_headlines = set()
        
        for body_story in body_stories:
            # Extract author and content from body - BOTH PLAIN AND RICH VERSIONS
            author = self._extract_author_from_body(body_story)
            
            # Generate plain text content (existing functionality)
            content_plain = self._clean_content_text(body_story)
            
            # Generate rich HTML content for WordPress (NEW!)
            content_html = self._generate_rich_content_html(body_story)
            
            # Try to find matching headline
            matching_headline = self._find_matching_headline(body_story, headlines, used_headlines)
            
            if matching_headline:
                headline_text = matching_headline['raw_content']
                used_headlines.add(matching_headline['story_id'])
            else:
                # Try to extract headline from first sentence if it's formatted differently
                headline_text = self._extract_headline_from_content(body_story)
            
            article = {
                'story_id': body_story['story_id'],
                'headline_story_id': matching_headline['story_id'] if matching_headline else '',
                'filename': body_story['filename'],
                'headline_filename': matching_headline['filename'] if matching_headline else '',
                'article_type': 'news_article',
                'headline': headline_text,
                'author': author,
                'category': body_story.get('category', ''),  # Add category from extraction
                
                # DUAL CONTENT FORMAT - Choose what you need for WordPress!
                'content': content_plain,           # Plain text version (backward compatibility)
                'content_html': content_html,       # Rich HTML version for WordPress
                'content_formatted': True,          # Flag indicating HTML is available
                
                'full_text': body_story.get('full_text', ''),
                'paragraphs': body_story.get('paragraphs', []),
                'metadata': {
                    'body_elements': len(body_story['content_elements']),
                    'headline_elements': len(matching_headline['content_elements']) if matching_headline else 0,
                    'has_matching_headline': bool(matching_headline),
                    'formatting_preserved': bool(content_html),
                    'html_paragraph_count': len(re.findall(r'<p>', content_html)) if content_html else 0
                }
            }
            
            matched_articles.append(article)
        
        # Add standalone headlines that weren't matched
        for headline in headlines:
            if headline['story_id'] not in used_headlines:
                article = {
                    'story_id': headline['story_id'],
                    'headline_story_id': headline['story_id'],
                    'filename': headline['filename'],
                    'headline_filename': headline['filename'],
                    'article_type': 'standalone_headline',
                    'headline': headline['raw_content'],
                    'author': '',
                    'category': headline.get('category', ''),  # Add category for headlines too
                    'content': '',
                    'full_text': headline['raw_content'],
                    'paragraphs': [headline['raw_content']],
                    'metadata': {
                        'body_elements': 0,
                        'headline_elements': len(headline['content_elements']),
                        'has_matching_headline': True
                    }
                }
                matched_articles.append(article)
        
        return matched_articles
    
    def _determine_story_type(self, story: Dict[str, Any]) -> str:
        """Determine if this story is a headline or body content"""
        content_elements = story['content_elements']
        raw_content = story['raw_content']
        
        if not content_elements:
            return 'unknown'
        
        avg_font_size = sum(elem['font_size'] for elem in content_elements) / len(content_elements)
        has_bold = any(elem['is_bold'] for elem in content_elements)
        text_length = len(raw_content)
        paragraph_count = len(story.get('paragraphs', []))
        
        # Headlines are typically: large font, bold, short, single paragraph
        if (avg_font_size >= 15 and has_bold and text_length < 100 and paragraph_count <= 1):
            return 'headline'
        
        # Body content: smaller font, multiple paragraphs, longer text
        elif (avg_font_size < 15 and text_length > 50 and paragraph_count > 1):
            return 'body_content'
        
        # Author line detection: starts with name pattern
        elif self._looks_like_author_line(raw_content):
            return 'body_content'
        
        return 'unknown'
    
    def _extract_author_from_body(self, body_story: Dict[str, Any]) -> str:
        """Extract author from body content"""
        paragraphs = body_story.get('paragraphs', [])
        if not paragraphs:
            return ''
        
        first_paragraph = paragraphs[0].strip()
        
        # Enhanced author patterns for Nigerian newspapers
        author_patterns = [
            # Standard "Name, City" format
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*),\s+[A-Z][a-z]+',
            # Multiple authors with "and" - more flexible
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*)\s*$',
            # Single author names at start of paragraph
            r'^([A-Z][a-z]+-[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+-[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*)',  # Hyphenated names
            # "By Author" format
            r'^By\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            # Author names that end with location
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*)\s*,\s*[A-Za-z]+',
        ]
        
        for pattern in author_patterns:
            match = re.match(pattern, first_paragraph)
            if match:
                author_name = match.group(1).strip()
                # Clean up common suffixes
                author_name = re.sub(r',.*$', '', author_name)  # Remove location part
                return author_name
        
        # If first paragraph looks like author names (all caps start, short), use it
        if (len(first_paragraph) < 60 and 
            re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*', first_paragraph)):
            return first_paragraph.strip()
        
        return ''
    
    def _clean_content_text(self, body_story: Dict[str, Any]) -> str:
        """Clean and extract main content from body story - PLAIN TEXT VERSION"""
        paragraphs = body_story.get('paragraphs', [])
        if not paragraphs:
            return ''
        
        cleaned_paragraphs = []
        first_para = paragraphs[0].strip()
        
        # Extract the author first to know exactly what to remove
        extracted_author = self._extract_author_from_body(body_story)
        
        if extracted_author:
            # Remove the author and location pattern from the first paragraph
            cleaned_first = self._remove_exact_author_from_paragraph(first_para, extracted_author)
            
            # Only add cleaned first paragraph if it has substantial content left
            if cleaned_first and len(cleaned_first.strip()) > 10:
                cleaned_paragraphs.append(cleaned_first.strip())
            
            # Add remaining paragraphs
            for i in range(1, len(paragraphs)):
                para = paragraphs[i].strip()
                if para:
                    cleaned_paragraphs.append(para)
        else:
            # No author found, keep all paragraphs
            cleaned_paragraphs = [p.strip() for p in paragraphs if p.strip()]
        
        return '\n'.join(cleaned_paragraphs)
    
    def _generate_rich_content_html(self, body_story: Dict[str, Any]) -> str:
        """Generate WordPress-ready HTML content with preserved InDesign formatting"""
        story_id = body_story.get('story_id', 'unknown')
        content_elements = body_story.get('content_elements', [])
        
        if not content_elements:
            print(f"[DEBUG] Story {story_id}: No content_elements found - returning empty HTML")
            return ''
        
        print(f"\n[DEBUG] Processing story {story_id}")
        print(f"[DEBUG] Total content_elements: {len(content_elements)}")
        
        # Extract the author first to know exactly what to remove from elements
        extracted_author = self._extract_author_from_body(body_story)
        
        print(f"[DEBUG] Extracted author: '{extracted_author}'")
        
        # Track paragraph boundaries using the paragraph style ranges
        para_ranges = self._group_elements_by_paragraph(content_elements)
        
        print(f"[DEBUG] Paragraph ranges: {len(para_ranges)}")
        
        html_paragraphs = []
        
        para_index = 0
        for para_elements in para_ranges:
            para_index += 1
            paragraph_html_parts = []
            paragraph_text_parts = []
            
            for element in para_elements:
                text_content = element['text'].strip()
                if not text_content:
                    continue
                
                # Build plain text version for author detection
                paragraph_text_parts.append(text_content)
                
                # Generate HTML with formatting
                html_text = self._wrap_text_with_formatting(text_content, element)
                paragraph_html_parts.append(html_text)
            
            # Join the current paragraph parts
            paragraph_text = ' '.join(paragraph_text_parts)
            paragraph_html = ''.join(paragraph_html_parts)
            
            # Check if this is author paragraph
            is_author_para = extracted_author and self._is_author_paragraph(paragraph_text, extracted_author)
            print(f"[DEBUG] Para {para_index}: text='{paragraph_text[:50]}...' | is_author={is_author_para} | html_len={len(paragraph_html)}")
            
            # Skip if this paragraph is just author information
            if is_author_para:
                print(f"[DEBUG]   → Skipped (matches author pattern)")
                continue
                
            # Add non-empty paragraphs
            if paragraph_html.strip():
                html_paragraphs.append(f'<p>{paragraph_html}</p>')
                print(f"[DEBUG]   → Added to HTML")
            else:
                print(f"[DEBUG]   → Skipped (empty HTML after formatting)")
        
        final_html = '\n'.join(html_paragraphs)
        print(f"[DEBUG] Final HTML length: {len(final_html)} chars | Paragraphs: {len(html_paragraphs)}")
        print(f"[DEBUG] Story {story_id} complete\n")
        
        return final_html
    
    def _group_elements_by_paragraph(self, content_elements: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Group content elements by paragraph boundaries"""
        paragraphs = []
        current_paragraph = []
        current_para_index = None
        
        for element in content_elements:
            para_index = element.get('paragraph_range_index', 0)
            
            # If paragraph index changes, start a new paragraph
            if current_para_index is not None and para_index != current_para_index:
                if current_paragraph:
                    paragraphs.append(current_paragraph)
                current_paragraph = []
            
            current_paragraph.append(element)
            current_para_index = para_index
        
        # Add the last paragraph
        if current_paragraph:
            paragraphs.append(current_paragraph)
        
        return paragraphs
    
    def _wrap_text_with_formatting(self, text: str, element: Dict[str, Any]) -> str:
        """Convert InDesign formatting to WordPress-compatible HTML tags"""
        html_text = text
        
        # STEP 1: Apply bold formatting
        if element.get('is_bold', False):
            html_text = f'<strong>{html_text}</strong>'
        
        # STEP 2: Apply italic formatting
        if element.get('is_italic', False):
            html_text = f'<em>{html_text}</em>'
        
        # STEP 3: Handle special font sizes
        font_size = element.get('font_size', 12)
        
        # If font is significantly larger than body text, treat as subheading
        if font_size >= 16 and not element.get('is_bold', False):
            html_text = f'<h4>{html_text}</h4>'
        elif font_size >= 20:
            html_text = f'<h3>{html_text}</h3>'
        
        return html_text
    
    def _is_author_paragraph(self, paragraph_text: str, extracted_author: str) -> bool:
        """Check if this paragraph is just author information that should be removed"""
        if not extracted_author:
            return False
            
        escaped_author = re.escape(extracted_author)
        author_patterns = [
            rf'^{escaped_author}',  # Starts with author name
            rf'^By\s+{escaped_author}',  # "By Author Name"
            rf'^{escaped_author},\s+[A-Za-z]+',  # "Author Name, Location"
        ]
        
        for pattern in author_patterns:
            if re.match(pattern, paragraph_text.strip(), re.IGNORECASE):
                print(f"[DEBUG]     Author pattern matched: {pattern}")
                return True
        
        return False
    
    def _remove_exact_author_from_paragraph(self, paragraph: str, author_name: str) -> str:
        """Remove the exact author pattern that was extracted"""
        if not author_name:
            return paragraph
            
        escaped_author = re.escape(author_name)
        
        removal_patterns = [
            rf'^{escaped_author},\s+[A-Za-z]+\s*',
            rf'^{escaped_author}\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+[A-Za-z]+\s*',
            rf'^{escaped_author}\s*',
            rf'^{escaped_author}\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*',
        ]
        
        cleaned = paragraph
        for pattern in removal_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
            if new_cleaned != cleaned:
                cleaned = new_cleaned
                break
        
        # If the above didn't work, try a more aggressive approach
        if cleaned == paragraph and author_name:
            match = re.search(r'\b(The|A|An|In|On|At|For|With|By|After|Before|During|Since|Until|About|Over|Under|Through|Against|Between|Among|Around|Inside|Outside|Upon|Within|Without|From|To|Of|Into|Onto|Across|Down|Up|Off|Out|In)\b', paragraph, re.IGNORECASE)
            if match:
                cleaned = paragraph[match.start():].strip()
        
        return cleaned
    
    def _is_likely_author_line(self, paragraph: str) -> bool:
        """Check if paragraph is likely just an author line"""
        paragraph = paragraph.strip()
        
        if len(paragraph) < 60:
            author_patterns = [
                r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*,\s+[A-Z][a-z]+$',
                r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*$',
                r'^By\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
            ]
            
            for pattern in author_patterns:
                if re.match(pattern, paragraph):
                    return True
        
        return False
    
    def _remove_author_from_paragraph(self, paragraph: str) -> str:
        """Remove author name from beginning of paragraph, return remaining content"""
        removal_patterns = [
            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*,\s+[A-Z][a-z]+\s*',
            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*\s+',
            r'^By\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*',
        ]
        
        cleaned = paragraph
        for pattern in removal_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
            if cleaned != paragraph:
                break
        
        return cleaned
    
    def _find_matching_headline(self, body_story: Dict[str, Any], headlines: List[Dict[str, Any]], used_headlines: set) -> Optional[Dict[str, Any]]:
        """Find headline that matches the body story using multiple strategies"""
        body_id = body_story['story_id']
        body_content = body_story['raw_content'].lower()
        
        # Strategy 1: Content similarity
        content_matches = []
        for headline in headlines:
            if headline['story_id'] in used_headlines:
                continue
                
            headline_text = headline['raw_content'].lower()
            similarity_score = self._calculate_content_similarity(headline_text, body_content)
            
            if similarity_score > 0:
                content_matches.append((headline, similarity_score))
        
        content_matches.sort(key=lambda x: x[1], reverse=True)
        
        if content_matches and content_matches[0][1] >= 2:
            return content_matches[0][0]
        
        # Strategy 2: ID proximity matching
        id_matches = []
        for headline in headlines:
            if headline['story_id'] in used_headlines:
                continue
                
            distance = self._calculate_id_distance(body_id, headline['story_id'])
            id_matches.append((headline, distance))
        
        id_matches.sort(key=lambda x: x[1])
        
        # Strategy 3: Combined scoring
        best_match = None
        best_score = -1
        
        for headline in headlines:
            if headline['story_id'] in used_headlines:
                continue
                
            content_score = self._calculate_content_similarity(headline['raw_content'].lower(), body_content)
            id_distance = self._calculate_id_distance(body_id, headline['story_id'])
            id_score = max(0, 10 - (id_distance / 10))
            
            combined_score = (content_score * 0.7) + (id_score * 0.3)
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = headline
        
        if best_match and best_score >= 1.0:
            return best_match
            
        return None
    
    def _calculate_content_similarity(self, headline: str, content: str) -> float:
        """Calculate similarity score between headline and content"""
        score = 0.0
        
        stop_words = {'this', 'that', 'with', 'from', 'they', 'were', 'been', 'have', 'will', 'would', 'could', 'should', 'said', 'says', 'also', 'more', 'most', 'much', 'many', 'some', 'very', 'when', 'where', 'what', 'which', 'while', 'after', 'before', 'during', 'since', 'until', 'about', 'above', 'below', 'between', 'through', 'against'}
        
        headline_words = set(re.findall(r'\b[a-z]{4,}\b', headline.lower())) - stop_words
        content_words = set(re.findall(r'\b[a-z]{4,}\b', content.lower()[:300])) - stop_words
        
        common_words = headline_words.intersection(content_words)
        if len(headline_words) > 0:
            word_overlap_score = len(common_words) / len(headline_words) * 5
            score += word_overlap_score
        
        headline_entities = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', headline))
        content_entities = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content[:400]))
        
        common_entities = headline_entities.intersection(content_entities)
        entity_score = len(common_entities) * 2
        score += entity_score
        
        important_keywords = ['president', 'minister', 'governor', 'senator', 'chairman', 'commission', 'committee', 'party', 'government', 'assembly', 'court', 'justice', 'university', 'union', 'movement', 'congress', 'forum']
        
        for keyword in important_keywords:
            if keyword in headline.lower() and keyword in content.lower():
                score += 1
        
        return score
    
    def _calculate_id_distance(self, id1: str, id2: str) -> float:
        """Calculate distance between two story IDs"""
        try:
            num1 = re.search(r'(\d+)', id1)
            num2 = re.search(r'(\d+)', id2)
            
            if num1 and num2:
                val1 = int(num1.group(1))
                val2 = int(num2.group(1))
                return abs(val1 - val2)
        except (ValueError, AttributeError):
            pass
        
        return float('inf')
    
    def _extract_headline_from_content(self, body_story: Dict[str, Any]) -> str:
        """Extract potential headline from content if no separate headline found"""
        content_elements = body_story['content_elements']
        
        for elem in content_elements:
            if elem['is_bold'] and elem['font_size'] > 10 and len(elem['text']) < 100:
                return elem['text']
        
        paragraphs = body_story.get('paragraphs', [])
        if paragraphs:
            first_sentence = paragraphs[0].split('.')[0]
            return first_sentence[:100] + '...' if len(first_sentence) > 100 else first_sentence
            
        return ''
    
    def _looks_like_author_line(self, text: str) -> bool:
        """Check if text looks like an author line"""
        author_patterns = [
            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+[A-Z][a-z]+',
            r'^By\s+[A-Z][a-z]+',
        ]
        
        for pattern in author_patterns:
            if re.match(pattern, text.strip()):
                return True
        return False

    def _determine_article_type(self, content_elements: List[Dict[str, Any]]) -> str:
        """Determine if this is a headline, caption, body text, etc."""
        if not content_elements:
            return 'unknown'
        
        avg_font_size = sum(elem['font_size'] for elem in content_elements) / len(content_elements)
        has_bold = any(elem['is_bold'] for elem in content_elements)
        text_length = sum(len(elem['text']) for elem in content_elements)
        
        if avg_font_size >= 25 and has_bold:
            return 'main_headline'
        elif avg_font_size >= 17 and has_bold:
            return 'secondary_headline'
        elif avg_font_size >= 12 and text_length > 200:
            return 'body_text'
        elif 'Caption' in str(content_elements[0].get('applied_style', '')):
            return 'caption'
        elif text_length < 50:
            return 'short_text'
        else:
            return 'content'
    
    def _extract_article_components(self, content_elements: List[Dict[str, Any]], full_text: str) -> Dict[str, str]:
        """Extract headline, author, and content from the elements"""
        components = {'headline': '', 'author': '', 'content': ''}
        
        author_patterns = [
            r'By\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+[A-Z][a-z]+$',
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+[A-Z][a-z]+,\s+[A-Z][a-z]+$',
        ]
        
        for pattern in author_patterns:
            author_match = re.search(pattern, full_text, re.IGNORECASE)
            if author_match:
                components['author'] = author_match.group(1)
                full_text = re.sub(pattern, '', full_text, flags=re.IGNORECASE).strip()
                break
        
        largest_font_elements = sorted(content_elements, key=lambda x: x['font_size'], reverse=True)
        
        if largest_font_elements and largest_font_elements[0]['font_size'] > 15:
            headline_elements = [elem for elem in content_elements 
                               if elem['font_size'] == largest_font_elements[0]['font_size']]
            components['headline'] = ' '.join([elem['text'] for elem in headline_elements]).strip()
            
            headline_text = components['headline']
            components['content'] = full_text.replace(headline_text, '').strip()
        else:
            components['content'] = full_text
        
        return components
    
    def _is_metadata_content(self, text: str) -> bool:
        """Check if content is metadata rather than news content"""
        text = text.strip()
        
        metadata_patterns = [
            r'^news$',
            r'^All stories continued on',
            r'^•L-R:',
            r'^\s*$',
            r'^MONDAY,.*\d{4}$',
            r'^\d{1,2}$',
            r'^Photo:',
            r'^Continued from'
        ]
        
        if len(text) < 3:
            return True
            
        for pattern in metadata_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True
        return False
