"""
NATIVE IDML NEWS EXTRACTOR

Category detection (priority order):
  1. Filename section-code mapping (e.g. DAP→Metro, SPILL→News)
  2. Large-font section header story in the IDML (decorative masthead)
  3. Traditional category-marker story (single short paragraph)
  4. Fuzzy match of extracted string against WordPress categories (done in wordpress.py)
  5. Uncategorized fallback

Images:
  - Embedded: extracted from Spread XML CDATA base64 (large spreads like BackPage Mon)
  - Linked: extracted from Spread XML Link elements as file:// URIs (e.g. DAP pages)
    The JSX script should copy linked files alongside the IDML so they are available.

Output: one content field (content_html) — the WordPress-ready HTML.
"""

import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import re
import base64
from urllib.parse import unquote


# ---------------------------------------------------------------------------
# Known section-code → category mappings for filenames that don't spell out
# the section name. Keys are lowercase. Values are passed to WordPress fuzzy
# matching, so they don't need to be exact — just close enough.
# Add more entries here as you discover new section codes.
# ---------------------------------------------------------------------------
SECTION_CODE_MAP: Dict[str, str] = {
    "dap":          "Metro",
    "spill":        "News",
    "healthplus":   "HealthPlus",       # column
    "healthwise":   "HealthWise",
    # backpage / bp handled dynamically in _map_section_code (Sat→Sports, else Column)
    "mynews":       "News",
    "lagos":        "Lagos",
    "am business":  "Business",
    "247 business": "247 Business",     # subcategory of Business
    "business extra": "Business",
    "business opening": "Business",
    "stock page":   "Stock Market",
    "photonews":    "Photo News",
    "special feature": "Features",
    "politics pulse": "Politics",
    "capital mrk":  "Capital Market",
    "capital market": "Capital Market",
    "personal banking": "Personal Finance",
    "homes":        "Homes & Property",
    "panorama":     "Panorama",
    "viewpoint":    "Viewpoint",
    "editorial":    "Editorial",
    "insurance":    "Insurance",
}


class IDMLNewsExtractor:
    """
    IDML News Extractor with Rich Text Formatting, Image Extraction,
    and Filename-Based Category Detection.
    """

    def __init__(self, idml_file_path: str):
        self.idml_path = idml_file_path
        self.namespace = {'idPkg': 'http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging'}
        self.extracted_images: List[bytes] = []   # populated during extract_news_articles()
        self.document_name: str = ''              # original .indd filename from designmap

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def extract_news_articles(self) -> List[Dict[str, Any]]:
        """
        Extract news articles with headlines, authors, content, and images.

        Returns list of article dicts. Call self.extracted_images after this
        to get the raw image bytes found in the IDML Spread files.
        """
        self.extracted_images = []
        all_stories = []
        detected_category = ''
        marker_story_ids = set()

        with zipfile.ZipFile(self.idml_path, 'r') as zip_file:
            # ------------------------------------------------------------------
            # STEP 1: Parse designmap.xml for story order + document name
            # ------------------------------------------------------------------
            story_order, self.document_name = self._parse_designmap(zip_file)

            print(f"\n[DEBUG] Document name: '{self.document_name}'")
            print(f"[DEBUG] Story order from designmap: {len(story_order)} stories")

            # ------------------------------------------------------------------
            # STEP 2: Category — multi-strategy detection
            # ------------------------------------------------------------------
            filename_category = self._extract_category_from_filename(
                self.document_name or self.idml_path
            )
            print(f"[DEBUG] Category from filename raw: '{filename_category}'")

            # ------------------------------------------------------------------
            # STEP 3: Build ordered list of story files
            # ------------------------------------------------------------------
            available = set(zip_file.namelist())
            if story_order:
                story_files = [
                    f'Stories/Story_{sid}.xml'
                    for sid in story_order
                    if f'Stories/Story_{sid}.xml' in available
                ]
                # Append any stories not in designmap order (safety net)
                all_story_files = sorted([
                    f for f in available if f.startswith('Stories/Story_')
                ])
                for sf in all_story_files:
                    if sf not in story_files:
                        story_files.append(sf)
            else:
                story_files = sorted([
                    f for f in available if f.startswith('Stories/Story_')
                ])

            print(f"[DEBUG] Total story files to process: {len(story_files)}")

            # ------------------------------------------------------------------
            # STEP 4: Scan stories for category signals (markers + section headers)
            # ------------------------------------------------------------------
            section_header_category = ''   # large-font decorative section header
            all_markers = []

            for i, story_file in enumerate(story_files):
                try:
                    story_content = zip_file.read(story_file)
                    root = ET.fromstring(story_content)
                    story_el = root.find('.//Story')
                    if story_el is None:
                        continue
                    story_id = story_el.get('Self', '')

                    # Large-font section header (e.g. "metro" at 119pt)
                    if not section_header_category:
                        sh = self._extract_section_header_category(root)
                        if sh:
                            section_header_category = sh
                            marker_story_ids.add(story_id)
                            print(f"[DEBUG] Section header category: '{sh}' (id={story_id})")

                    # Traditional single-text marker (must have letters, not just a number)
                    if self._is_category_marker(root):
                        part = self._extract_category_from_story(root)
                        if part:
                            all_markers.append((i, story_id, part))

                except Exception as e:
                    print(f"[DEBUG] Error scanning {story_file}: {e}")

            # Collect first consecutive sequence of non-numeric markers
            if all_markers:
                category_parts = []
                expected = 0
                for idx, sid, content in all_markers:
                    if idx == expected:
                        category_parts.append(content)
                        marker_story_ids.add(sid)
                        expected += 1
                    else:
                        break
                if category_parts:
                    detected_category = ''.join(category_parts)
                    print(f"[DEBUG] Category from markers: '{detected_category}'")

            # Priority: mapped filename > section header > raw filename > marker
            final_category = (
                self._map_section_code(filename_category)
                or section_header_category
                or filename_category
                or detected_category
            )
            print(f"[DEBUG] Final category: '{final_category}'")

            # ------------------------------------------------------------------
            # STEP 5: Extract images from Spread XML files
            # ------------------------------------------------------------------
            self.extracted_images = self._extract_images_from_spreads(zip_file)
            print(f"[DEBUG] Images extracted (non-cartoon): {len(self.extracted_images)}")

            # ------------------------------------------------------------------
            # STEP 6: Parse all article stories
            # ------------------------------------------------------------------
            for story_file in story_files:
                try:
                    story_content = zip_file.read(story_file)
                    article_data = self._parse_news_story(story_content, story_file)

                    if article_data and article_data.get('raw_content'):
                        if article_data.get('story_id') not in marker_story_ids:
                            if not article_data.get('category'):
                                article_data['category'] = final_category
                            all_stories.append(article_data)
                        else:
                            print(f"[DEBUG] Filtered marker story: {article_data['story_id']}")
                except Exception as e:
                    print(f"[DEBUG] Error parsing {story_file}: {e}")

            # ------------------------------------------------------------------
            # STEP 7: Detect photo-caption author attribution stories
            # (e.g. 247-Business "OLUWAKEMI ABIMBOLA reports" in caption style)
            # ------------------------------------------------------------------
            author_attributions = self._detect_author_attributions(zip_file, story_files)

        print(f"[DEBUG] Processing done. Stories: {len(all_stories)}, Category: '{final_category}'\n")

        articles = self._match_headlines_with_content(all_stories, author_attributions)

        # ------------------------------------------------------------------
        # Per-article image assignment
        # Priority: author-name match in linked image filename → first non-cartoon embedded
        # Cartoon images (CARTOON in path) are never used as featured images.
        # ------------------------------------------------------------------
        image_records = getattr(self, 'image_records', [])
        used_image_indices: set = set()

        for article in articles:
            if not article.get('content_html'):
                continue
            author = article.get('author', '')
            if author:
                # Look for a non-cartoon image whose filename contains part of the author name
                author_words = [w.lower() for w in author.split() if len(w) > 2]
                for idx, rec in enumerate(image_records):
                    if idx in used_image_indices or rec.get('is_cartoon') or not rec.get('bytes'):
                        continue
                    fname_lower = rec['filename'].lower()
                    fname_no_ext = re.sub(r'\.[a-z]{2,5}$', '', fname_lower)
                    if any(w in fname_no_ext for w in author_words):
                        article['featured_image_bytes'] = rec['bytes']
                        used_image_indices.add(idx)
                        print(f"[DEBUG] Image matched: '{rec['filename']}' -> author '{author}'")
                        break

        # Fallback: assign first unused non-cartoon embedded image to the lead article
        if self.extracted_images:
            lead_candidates = [
                a for a in articles
                if a.get('content_html') and not a.get('featured_image_bytes')
            ]
            if lead_candidates:
                lead = max(lead_candidates, key=lambda a: len(a.get('content_html', '')))
                # Find first unused non-cartoon record
                for idx, rec in enumerate(image_records):
                    if idx not in used_image_indices and not rec.get('is_cartoon') and rec.get('bytes'):
                        lead['featured_image_bytes'] = rec['bytes']
                        used_image_indices.add(idx)
                        print(f"[DEBUG] Fallback image -> lead article '{lead.get('headline', '')[:40]}'")
                        break

        return articles

    def extract_from_xml_file(self, xml_file_path: str) -> Optional[Dict[str, Any]]:
        """Extract from a single XML story file (for batch processing)"""
        try:
            with open(xml_file_path, 'rb') as f:
                xml_content = f.read()
            return self._parse_news_story(xml_content, xml_file_path)
        except Exception as e:
            print(f"Error parsing {xml_file_path}: {e}")
            return None

    # =========================================================================
    # DESIGNMAP + CATEGORY + IMAGE EXTRACTION
    # =========================================================================

    def _parse_designmap(self, zip_file: zipfile.ZipFile):
        """
        Parse designmap.xml to get:
        - Ordered list of story IDs (from StoryList attribute)
        - Document name (original .indd filename)
        """
        story_order = []
        document_name = ''
        try:
            dm_content = zip_file.read('designmap.xml')
            root = ET.fromstring(dm_content)
            story_list_str = root.get('StoryList', '')
            if story_list_str:
                story_order = story_list_str.split()
            document_name = root.get('Name', '')
        except Exception as e:
            print(f"[DEBUG] Could not parse designmap.xml: {e}")
        return story_order, document_name

    def _extract_category_from_filename(self, name: str) -> str:
        """
        Extract section/category from the InDesign document filename.

        Examples:
          'Capital Mrk 26.indd'      → 'Capital Mrk'
          'News - 8 - Copy.indd'     → 'News'
          '247 Business -12.indd'    → '247 Business'
          'BackPage Mon.indd'        → 'BackPage Mon'
          'DAP4,5.indd'              → 'DAP'
          'Special feature 42&43'    → 'Special feature'
        """
        import os
        # Use just the basename (handle full paths)
        name = os.path.basename(name)

        # Remove .indd extension
        name = re.sub(r'\.indd$', '', name, flags=re.IGNORECASE)
        # Remove .idml extension (if given an IDML path directly)
        name = re.sub(r'\.idml$', '', name, flags=re.IGNORECASE)
        # Remove " - Copy" or " copy" suffix
        name = re.sub(r'\s*-\s*Copy\s*$', '', name, flags=re.IGNORECASE)

        # Remove trailing page numbers with separator (e.g. " 26", " -12", " 42&43")
        name = re.sub(r'[\s\-,]+\d[\d,&\s]*$', '', name)
        # Remove digits directly attached without separator (e.g. "DAP4,5" → "DAP")
        name = re.sub(r'\d[\d,&]*$', '', name)

        name = name.strip(' -,')
        return name

    def _extract_images_from_spreads(self, zip_file: zipfile.ZipFile) -> List[bytes]:
        """
        Extract images from Spread XML files.

        Correlates each Link URI with its embedded CDATA block (they live inside the
        same <Image> element in InDesign).  Cartoon images (CARTOON in path) are
        recorded but EXCLUDED from the returned bytes list so they are never used as
        featured images.

        Populates:
          self.linked_image_uris  – all linked file paths (for reporting)
          self.image_records      – structured list of
                                    {bytes, uri, filename, is_cartoon}

        Returns list of non-cartoon image bytes (embedded or loaded from disk).
        """
        import os
        images: List[bytes] = []
        self.linked_image_uris: List[str] = []
        self.image_records: List[Dict] = []
        spread_files = [f for f in zip_file.namelist() if f.startswith('Spreads/')]

        for spread_file in spread_files:
            try:
                raw = zip_file.read(spread_file)
                if len(raw) > 200 * 1024 * 1024:
                    print(f"[DEBUG] Skipping oversized spread: {spread_file} ({len(raw)//1024//1024}MB)")
                    continue
                spread_text = raw.decode('utf-8', errors='ignore')

                # Collect positions of all Link URIs in this spread
                link_positions = [
                    (m.start(), m.group(1))
                    for m in re.finditer(r'LinkResourceURI="([^"]+)"', spread_text)
                ]

                # Collect positions of all valid (non-XMP) CDATA image blocks
                cdata_positions = []
                for m in re.finditer(
                    r'<Contents><!\[CDATA\[(.*?)\]\]></Contents>', spread_text, re.DOTALL
                ):
                    clean_b64 = ''.join(m.group(1).split())
                    if clean_b64 and not clean_b64.startswith('<?xpacket') and len(clean_b64) > 100:
                        cdata_positions.append((m.start(), clean_b64))

                for i, (link_pos, raw_uri) in enumerate(link_positions):
                    # Normalise URI → UNC/local path
                    decoded = unquote(raw_uri.replace('file://', '').replace('file:', ''))
                    if decoded.startswith('//'):
                        unc = decoded.replace('/', '\\')
                    elif len(decoded) > 2 and decoded[1] == ':':
                        unc = decoded.replace('/', '\\')
                    elif len(decoded) > 3 and decoded[2] == ':':
                        unc = decoded[1:].replace('/', '\\')
                    else:
                        unc = decoded.replace('/', '\\')

                    filename = unc.replace('\\', '/').split('/')[-1]
                    is_cartoon = 'CARTOON' in unc.upper()
                    self.linked_image_uris.append(unc)

                    # Find the CDATA block that comes AFTER this Link and BEFORE the next Link
                    next_link_pos = link_positions[i + 1][0] if i + 1 < len(link_positions) else len(spread_text)
                    cdata_in_range = [
                        (pos, b64) for pos, b64 in cdata_positions
                        if link_pos < pos < next_link_pos
                    ]

                    img_bytes: Optional[bytes] = None
                    if cdata_in_range:
                        try:
                            img_bytes = base64.b64decode(cdata_in_range[0][1])
                            if len(img_bytes) < 5 * 1024:
                                img_bytes = None
                        except Exception:
                            img_bytes = None

                    # Fallback: try to read from disk (works when file server is reachable)
                    if img_bytes is None:
                        try:
                            if os.path.exists(unc):
                                with open(unc, 'rb') as img_f:
                                    img_bytes = img_f.read()
                                if len(img_bytes) < 5 * 1024:
                                    img_bytes = None
                        except Exception:
                            pass

                    record: Dict[str, Any] = {
                        'bytes':      img_bytes,
                        'uri':        unc,
                        'filename':   filename,
                        'is_cartoon': is_cartoon,
                    }
                    self.image_records.append(record)

                    tag = 'CARTOON' if is_cartoon else 'columnist'
                    size_kb = len(img_bytes) // 1024 if img_bytes else 0
                    print(f"[DEBUG] Image [{tag}] {filename} ({size_kb}KB embedded)")

                    if img_bytes and not is_cartoon:
                        images.append(img_bytes)
                        if len(images) >= 10:
                            return images

            except Exception as e:
                print(f"[DEBUG] Error reading spread {spread_file}: {e}")

        return images

    # =========================================================================
    # STORY PARSING
    # =========================================================================

    def _parse_news_story(self, xml_content: bytes, filename: str) -> Optional[Dict[str, Any]]:
        """Parse individual story XML and extract structured content"""
        try:
            try:
                root = ET.fromstring(xml_content)
            except ET.ParseError:
                # Recover: re-encode as CP1252 → UTF-8 for Windows-1252 bytes in XML
                try:
                    recovered = xml_content.decode('cp1252', errors='replace').encode('utf-8')
                    root = ET.fromstring(recovered)
                    print(f"[DEBUG] CP1252 recovery applied: {filename}")
                except Exception as e:
                    print(f"[DEBUG] XML parse error in {filename}: {e}")
                    return None
            story_el = root.find('.//Story')
            if story_el is None:
                return None

            para_ranges = root.findall(".//ParagraphStyleRange")
            if not para_ranges:
                return None

            # Skip Date Line stories (e.g. "MONDAY, JUNE 16, 2025")
            for pr in para_ranges:
                style = pr.get('AppliedParagraphStyle', '')
                if 'Date Line' in style or 'DateLine' in style:
                    return None

            # Extract category from story (marker detection)
            category = self._extract_category_from_story(root)

            content_data = []
            paragraphs = []
            para_range_index = 0

            for para_range in para_ranges:
                para_range_index += 1
                para_content = []
                para_style = para_range.get('AppliedParagraphStyle', '')
                para_justification = para_range.get('Justification', '')

                char_ranges = para_range.findall(".//CharacterStyleRange")
                for char_range in char_ranges:
                    for child in char_range:
                        if child.tag == 'Content' and child.text:
                            text_content = child.text.strip()
                            if not text_content:
                                continue

                            font_size_str = char_range.get('PointSize', '12')
                            try:
                                font_size = float(font_size_str)
                            except (ValueError, TypeError):
                                font_size = 12.0

                            font_style = char_range.get('FontStyle', 'Regular')
                            is_bold = 'Bold' in font_style
                            is_italic = 'Italic' in font_style

                            content_item = {
                                'text': text_content,
                                'font_size': font_size,
                                'font_style': font_style,
                                'is_bold': is_bold,
                                'is_italic': is_italic,
                                'applied_style': char_range.get('AppliedCharacterStyle', ''),
                                'paragraph_style': para_style,
                                'paragraph_justification': para_justification,
                                'paragraph_range_index': para_range_index,
                            }
                            content_data.append(content_item)
                            para_content.append(text_content)

                        elif child.tag == 'Br':
                            if para_content:
                                paragraphs.append(' '.join(para_content))
                                para_content = []

                if para_content:
                    paragraphs.append(' '.join(para_content))

            if not content_data:
                return None

            raw_content = ' '.join(paragraphs)
            full_text = '\n'.join(paragraphs)

            # Skip stories with garbled encoding (3+ consecutive ? = CP1252 bytes misread)
            if re.search(r'\?{3,}', raw_content):
                print(f"[DEBUG] Skipping garbled story (encoding issue): {filename}")
                return None

            return {
                'story_id': story_el.get('Self', ''),
                'filename': filename,
                'content_elements': content_data,
                'raw_content': raw_content,
                'full_text': full_text,
                'paragraphs': paragraphs,
                'category': category,
            }

        except Exception as e:
            print(f"[DEBUG] Error parsing story {filename}: {e}")
            return None

    # =========================================================================
    # CATEGORY MARKER DETECTION
    # =========================================================================

    def _is_category_marker(self, root: ET.Element) -> bool:
        """
        Check if a story is a category marker (single short paragraph with letters).
        Rejects page numbers (pure digits like '5', '37') and Date Line stories.
        """
        para_ranges = root.findall(".//ParagraphStyleRange")
        if len(para_ranges) != 1:
            return False

        # Reject Date Line paragraph style
        style = para_ranges[0].get('AppliedParagraphStyle', '')
        if 'Date Line' in style or 'DateLine' in style:
            return False

        char_ranges = para_ranges[0].findall(".//CharacterStyleRange")
        if len(char_ranges) != 1:
            return False
        contents = char_ranges[0].findall("Content")
        if len(contents) != 1 or not contents[0].text:
            return False

        text = contents[0].text.strip()
        if not text or len(text) > 30:
            return False

        # Must contain at least one letter — rejects page numbers like "5", "37"
        return any(c.isalpha() for c in text)

    def _extract_category_from_story(self, root: ET.Element) -> str:
        """Extract category text from a marker story"""
        para_ranges = root.findall(".//ParagraphStyleRange")
        if len(para_ranges) == 1:
            char_ranges = para_ranges[0].findall(".//CharacterStyleRange")
            if len(char_ranges) == 1:
                contents = char_ranges[0].findall("Content")
                if len(contents) == 1 and contents[0].text:
                    text = contents[0].text.strip()
                    if text and len(text) <= 30 and self._is_valid_category(text):
                        return text
        return ''

    def _map_section_code(self, raw: str) -> str:
        """
        Map a raw filename section string to a readable category name.
        Uses SECTION_CODE_MAP for known codes; returns '' if no match.
        """
        if not raw:
            return ''
        key = raw.lower().strip()
        # BackPage / BP: Saturday edition → Sports, all other days → Column
        if key.startswith('backpage') or key == 'bp' or key.startswith('bp '):
            return 'Sports' if 'sat' in key else 'Column'
        # Direct lookup
        if key in SECTION_CODE_MAP:
            return SECTION_CODE_MAP[key]
        # Prefix lookup (e.g. "lagos mon" starts with "lagos")
        for code, name in SECTION_CODE_MAP.items():
            if key.startswith(code) or code.startswith(key):
                return name
        return ''

    def _extract_section_header_category(self, root: ET.Element) -> str:
        """
        Detect large-font decorative section headers like the 119pt 'metro' story.
        These are single-paragraph stories with very large font size and short text.
        Must have at least 3 letters and NOT be a page number or date.
        """
        para_ranges = root.findall(".//ParagraphStyleRange")
        if len(para_ranges) != 1:
            return ''

        char_ranges = para_ranges[0].findall(".//CharacterStyleRange")
        if len(char_ranges) != 1:
            return ''

        contents = char_ranges[0].findall("Content")
        if len(contents) != 1 or not contents[0].text:
            return ''

        text = contents[0].text.strip()
        if not text or len(text) > 30:
            return ''

        # Must have at least 3 letters (rejects page numbers like "5", "4")
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 3:
            return ''

        # Section headers are simple category names — reject headlines that contain
        # question marks, exclamation marks, digits in parens, or en-dashes
        if re.search(r'[?!–—]|\(\d+\)', text):
            return ''

        # Must have large font size (section header visual style)
        size_str = char_ranges[0].get('PointSize', '0')
        try:
            size = float(size_str)
        except (ValueError, TypeError):
            return ''

        if size >= 30:
            return text.strip()

        return ''

    def _looks_like_person_name(self, text: str) -> bool:
        """
        Return True if text looks like a journalist/columnist name
        (2–4 Title-Case words, no punctuation, no common English words).
        Used to detect BackPage-style standalone columnist name stories.
        """
        text = text.strip()
        if re.search(r'[?!:;/\\",\(\)\[\]]', text):
            return False
        words = text.split()
        if len(words) < 2 or len(words) > 4:
            return False
        # Common headline / non-name words (lowercase comparison)
        not_name = {
            'the', 'a', 'an', 'and', 'but', 'for', 'or', 'nor', 'so', 'yet',
            'in', 'on', 'at', 'to', 'by', 'of', 'as', 'up', 'off', 'out',
            'with', 'from', 'into', 'over', 'under', 'amid', 'upon', 'amid',
            'are', 'is', 'was', 'were', 'be', 'been', 'has', 'have', 'had',
            'will', 'would', 'could', 'should', 'can', 'may', 'must',
            'says', 'said', 'gets', 'hits', 'sets', 'runs', 'backs',
            'faces', 'urges', 'seeks', 'warns', 'vows', 'wins', 'loses',
            'new', 'old', 'big', 'key', 'top', 'its', 'his', 'her',
            'this', 'that', 'these', 'those', 'our', 'their',
        }
        for word in words:
            if not word[0].isupper():
                return False
            if len(word) < 2:
                return False
            if word.lower().rstrip('.,') in not_name:
                return False
        return True

    def _name_hint_from_uri(self, uri: str) -> str:
        """
        Extract a journalist name hint from a linked image filename.
        e.g. 'KUNLE SOMORIN.tif'  → 'Kunle Somorin'
             'Lekan Sote copy.tif' → 'Lekan Sote'
             'Tella.tif'           → 'Tella'
        Returns '' for cartoon images or paths with no useful name.
        """
        if 'CARTOON' in uri.upper():
            return ''
        filename = uri.replace('\\', '/').split('/')[-1]
        name = re.sub(r'\.[a-zA-Z]{2,5}$', '', filename)      # strip extension
        name = re.sub(r'\s*copy\s*$', '', name, flags=re.IGNORECASE).strip()
        return name.title() if name else ''

    def _detect_author_attributions(
        self, zip_file: zipfile.ZipFile, story_files: List[str]
    ) -> Dict[str, str]:
        """
        Scan stories for Photo-caption-style stories that contain an ALL-CAPS Bold
        name followed by 'reports' or 'writes'.  Pattern found in 247-Business-style
        pages:
            [regular text]  [BOLD ALL-CAPS "OLUWAKEMI ABIMBOLA"]  [regular "reports"]

        Returns {story_id: author_name (title-cased)}.
        """
        attributions: Dict[str, str] = {}
        for story_file in story_files:
            try:
                content = zip_file.read(story_file)
                root = ET.fromstring(content)
                story_el = root.find('.//Story')
                if story_el is None:
                    continue
                story_id = story_el.get('Self', '')

                for pr in root.findall('.//ParagraphStyleRange'):
                    style = pr.get('AppliedParagraphStyle', '').lower()
                    if 'caption' not in style and 'photo' not in style:
                        continue
                    char_ranges = pr.findall('.//CharacterStyleRange')
                    for i, cr in enumerate(char_ranges):
                        if 'bold' not in cr.get('FontStyle', '').lower():
                            continue
                        for c in cr.findall('Content'):
                            if not c.text:
                                continue
                            name_text = c.text.strip()
                            if not name_text.isupper() or len(name_text.split()) < 2:
                                continue
                            # Confirm next char-range contains 'reports' / 'writes'
                            confirmed = False
                            if i + 1 < len(char_ranges):
                                for nc in char_ranges[i + 1].findall('Content'):
                                    if nc.text and nc.text.strip().lower() in (
                                        'reports', 'writes', 'reports.', 'writes.'
                                    ):
                                        confirmed = True
                            if confirmed or len(name_text.split()) <= 4:
                                attributions[story_id] = name_text.title()
                                print(f"[DEBUG] Photo-caption author: '{name_text.title()}' (story {story_id})")

            except Exception:
                pass
        return attributions

    # Common words that look like valid text but are never category names
    _NOT_A_CATEGORY = {
        'the', 'a', 'an', 'and', 'or', 'in', 'on', 'at', 'to', 'of', 'by',
        'for', 'is', 'it', 'its', 'be', 'was', 'are', 'as', 'up', 'no',
        'so', 'do', 'go', 'he', 'she', 'we', 'they', 'you', 'but', 'not',
    }

    def _is_valid_category(self, text: str) -> bool:
        """Validate category text"""
        text = text.strip()
        if not text:
            return False
        if not any(c.isalpha() for c in text):
            return False
        if not re.match(r'^[a-zA-Z0-9\s\-_&,\.]+$', text):
            return False
        if len(text) < 1 or len(text) > 30:
            return False
        if '@' in text or 'http' in text.lower():
            return False
        if text.lower() in self._NOT_A_CATEGORY:
            return False
        return True

    # =========================================================================
    # HEADLINE / BODY MATCHING
    # =========================================================================

    def _match_headlines_with_content(
        self,
        all_stories: List[Dict[str, Any]],
        author_attributions: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Match headlines with their corresponding body content."""
        headlines = []
        body_stories = []
        person_name_stories = []   # BackPage-style columnist name stories

        for story in all_stories:
            if self._is_metadata_content(story['raw_content']):
                continue
            content_type = self._determine_story_type(story)
            if content_type == 'headline':
                headlines.append(story)
            elif content_type == 'body_content':
                body_stories.append(story)
            elif content_type == 'person_name':
                person_name_stories.append(story)
                print(f"[DEBUG] Person-name story: '{story['raw_content']}' (id={story['story_id']})")

        matched_articles = []
        used_headlines = set()

        for body_story in body_stories:
            author = self._extract_author_from_body(body_story)
            content_html = self._generate_rich_content_html(body_story)
            matching_headline = self._find_matching_headline(body_story, headlines, used_headlines)

            if matching_headline:
                headline_text = matching_headline['raw_content']
                used_headlines.add(matching_headline['story_id'])
            else:
                headline_text = self._extract_headline_from_content(body_story)

            article = {
                'story_id': body_story['story_id'],
                'article_type': 'news_article',
                'headline': headline_text,
                'author': author,
                'category': body_story.get('category', ''),
                'content_html': content_html,
                'featured_image_bytes': None,
                'metadata': {
                    'has_matching_headline': bool(matching_headline),
                    'html_paragraph_count': len(re.findall(r'<p>', content_html)) if content_html else 0,
                },
            }
            matched_articles.append(article)

        # Standalone headlines with no matched body
        for headline in headlines:
            if headline['story_id'] not in used_headlines:
                matched_articles.append({
                    'story_id': headline['story_id'],
                    'article_type': 'standalone_headline',
                    'headline': headline['raw_content'],
                    'author': '',
                    'category': headline.get('category', ''),
                    'content_html': '',
                    'featured_image_bytes': None,
                    'metadata': {
                        'has_matching_headline': True,
                        'html_paragraph_count': 0,
                    },
                })

        # ------------------------------------------------------------------
        # SECOND PASS: assign BackPage-style person-name stories as authors
        # Only consider body stories with substantial content (≥2 <p> tags)
        # to avoid assigning columnist names to pullquotes or short sidebars.
        # ------------------------------------------------------------------
        used_person_names: set = set()
        if person_name_stories:
            for article in matched_articles:
                if article.get('author'):
                    continue
                # Skip short/empty articles (pullquotes, disclaimers, sidebars)
                para_count = article.get('metadata', {}).get('html_paragraph_count', 0)
                if para_count < 2:
                    continue
                available = [
                    s for s in person_name_stories
                    if s['story_id'] not in used_person_names
                ]
                if not available:
                    break
                nearest = min(
                    available,
                    key=lambda s: self._calculate_id_distance(article['story_id'], s['story_id']),
                )
                dist = self._calculate_id_distance(article['story_id'], nearest['story_id'])
                if dist < 2000:     # only assign if reasonably close in story order
                    # Normalise non-breaking spaces in the name
                    name = nearest['raw_content'].replace('\xa0', ' ').strip()
                    article['author'] = name
                    used_person_names.add(nearest['story_id'])
                    print(f"[DEBUG] Assigned columnist author '{name}' -> story {article['story_id']}")

        # ------------------------------------------------------------------
        # THIRD PASS: author from photo-caption attribution stories
        # (e.g. 247-Business where "OLUWAKEMI ABIMBOLA reports" is a
        #  separate Photo caption story next to the body story)
        # ------------------------------------------------------------------
        if author_attributions:
            for article in matched_articles:
                if article.get('author'):
                    continue
                nearest_attr = min(
                    author_attributions.items(),
                    key=lambda x: self._calculate_id_distance(article['story_id'], x[0]),
                    default=(None, None),
                )
                if nearest_attr[1]:
                    dist = self._calculate_id_distance(article['story_id'], nearest_attr[0])
                    if dist < 2000:
                        article['author'] = nearest_attr[1]
                        print(f"[DEBUG] Assigned caption author '{nearest_attr[1]}' -> story{article['story_id']}")

        for article in matched_articles:
            if not article.get('author'):
                article['author'] = 'Agency Report'

        return matched_articles

    def _determine_story_type(self, story: Dict[str, Any]) -> str:
        """Determine if a story is a headline or body content"""
        content_elements = story['content_elements']
        raw_content = story['raw_content']

        if not content_elements:
            return 'unknown'

        avg_font_size = sum(e['font_size'] for e in content_elements) / len(content_elements)
        max_font_size = max(e['font_size'] for e in content_elements)
        has_bold = any(e['is_bold'] for e in content_elements)
        text_length = len(raw_content)
        paragraph_count = len(story.get('paragraphs', []))

        # Headlines: use MAX font size so kicker+headline layouts (where a small kicker
        # pulls the average below 15pt) are still caught.  Allows up to 3 paragraphs
        # (kicker / main head / deck) and up to 250 chars.
        if max_font_size >= 15 and has_bold and text_length < 250 and paragraph_count <= 3:
            # BackPage columns: columnist name is a separate Bold story at ~14-24pt
            # (actual article headlines on BackPage are typically 29pt+)
            if avg_font_size < 25 and self._looks_like_person_name(raw_content):
                return 'person_name'
            return 'headline'

        # Body content: smaller font, multiple paragraphs, substantial text
        if avg_font_size < 15 and text_length > 50 and paragraph_count > 1:
            return 'body_content'

        if self._looks_like_author_line(raw_content):
            return 'body_content'

        return 'unknown'

    # =========================================================================
    # AUTHOR EXTRACTION
    # =========================================================================

    def _extract_author_from_body(self, body_story: Dict[str, Any]) -> str:
        """
        Extract author from first paragraph of body story.

        Confirmed pattern from IDML inspection:
        - First ParagraphStyleRange uses Justification="CenterAlign"
        - CharacterStyleRange has FontStyle="Bold"
        - Content is "Name, City" e.g. "Deborah Musa, Abuja"
        """
        content_elements = body_story.get('content_elements', [])
        paragraphs = body_story.get('paragraphs', [])

        if not paragraphs:
            return ''

        first_paragraph = paragraphs[0].strip()

        # Check if first element has center-align + bold (strong byline signal)
        first_elements = [
            e for e in content_elements if e.get('paragraph_range_index', 0) == 1
        ]
        first_is_centered_bold = any(
            e.get('is_bold') and 'Center' in e.get('paragraph_justification', '')
            for e in first_elements
        )

        if first_is_centered_bold:
            # High confidence: extract the byline directly
            byline = first_paragraph.strip().replace('\xa0', ' ')
            # Strip location: "Name, City" → "Name"
            name_part = re.sub(r',.*$', '', byline).strip()
            if name_part and len(name_part) < 80:
                return name_part

        # Fallback: regex patterns for Nigerian newspaper bylines
        author_patterns = [
            # "Name, City" or "Name and Name, City"
            r'^([A-Z][a-z]+(?:[\-][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?)*'
            r'(?:\s+and\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?)*)*)'
            r',\s+[A-Z][a-z]+',
            # Name alone (no city)
            r'^([A-Z][a-z]+(?:[\-][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?)*'
            r'(?:\s+and\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[\-][A-Z][a-z]+)?)*)*)\s*$',
            # "By Name" format
            r'^By\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]

        for pattern in author_patterns:
            match = re.match(pattern, first_paragraph)
            if match:
                author_name = match.group(1).strip()
                author_name = re.sub(r',.*$', '', author_name)
                return author_name

        # Last resort: short title-case paragraph without article-like words
        if (len(first_paragraph) < 60 and
                re.match(r'^[A-Z][a-z]+', first_paragraph) and
                not any(w in first_paragraph.lower() for w in
                        ['the ', ' of ', ' in ', ' to ', ' a ', ' and '])):
            return first_paragraph.strip()

        return ''

    # =========================================================================
    # CONTENT CLEANING + HTML GENERATION
    # =========================================================================

    def _clean_content_text(self, body_story: Dict[str, Any]) -> str:
        """Plain text content with author paragraph removed"""
        paragraphs = body_story.get('paragraphs', [])
        if not paragraphs:
            return ''

        extracted_author = self._extract_author_from_body(body_story)
        cleaned_paragraphs = []
        first_para = paragraphs[0].strip()

        if extracted_author:
            cleaned_first = self._remove_exact_author_from_paragraph(first_para, extracted_author)
            if cleaned_first and len(cleaned_first.strip()) > 10:
                cleaned_paragraphs.append(cleaned_first.strip())
            for i in range(1, len(paragraphs)):
                para = paragraphs[i].strip()
                if para:
                    cleaned_paragraphs.append(para)
        else:
            cleaned_paragraphs = [p.strip() for p in paragraphs if p.strip()]

        return '\n'.join(cleaned_paragraphs)

    def _generate_rich_content_html(self, body_story: Dict[str, Any]) -> str:
        """Generate WordPress-ready HTML with preserved InDesign formatting"""
        story_id = body_story.get('story_id', 'unknown')
        content_elements = body_story.get('content_elements', [])

        if not content_elements:
            return ''

        extracted_author = self._extract_author_from_body(body_story)
        para_ranges = self._group_elements_by_paragraph(content_elements)
        html_paragraphs = []

        for para_index, para_elements in enumerate(para_ranges, start=1):
            paragraph_html_parts = []
            paragraph_text_parts = []

            for element in para_elements:
                text_content = element['text'].strip()
                if not text_content:
                    continue
                paragraph_text_parts.append(text_content)
                paragraph_html_parts.append(
                    self._wrap_text_with_formatting(text_content, element)
                )

            paragraph_text = ' '.join(paragraph_text_parts)
            paragraph_html = ''.join(paragraph_html_parts)

            is_author_para = (
                extracted_author and
                self._is_author_paragraph(paragraph_text, extracted_author)
            )

            if is_author_para:
                continue

            if paragraph_html.strip():
                html_paragraphs.append(f'<p>{paragraph_html}</p>')

        return '\n'.join(html_paragraphs)

    def _group_elements_by_paragraph(
        self, content_elements: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group content elements by paragraph boundary (paragraph_range_index)"""
        paragraphs = []
        current_paragraph: List[Dict[str, Any]] = []
        current_index = None

        for element in content_elements:
            idx = element.get('paragraph_range_index', 0)
            if current_index is not None and idx != current_index:
                if current_paragraph:
                    paragraphs.append(current_paragraph)
                current_paragraph = []
            current_paragraph.append(element)
            current_index = idx

        if current_paragraph:
            paragraphs.append(current_paragraph)

        return paragraphs

    def _wrap_text_with_formatting(self, text: str, element: Dict[str, Any]) -> str:
        """Convert InDesign formatting to HTML tags"""
        html_text = text
        font_size = element.get('font_size', 12)

        if element.get('is_bold'):
            html_text = f'<strong>{html_text}</strong>'

        if element.get('is_italic'):
            html_text = f'<em>{html_text}</em>'

        # Subheadings: only for non-bold large text (headlines are handled separately)
        if not element.get('is_bold'):
            if font_size >= 20:
                html_text = f'<h3>{html_text}</h3>'
            elif font_size >= 16:
                html_text = f'<h4>{html_text}</h4>'

        return html_text

    # =========================================================================
    # HEADLINE MATCHING
    # =========================================================================

    def _find_matching_headline(
        self,
        body_story: Dict[str, Any],
        headlines: List[Dict[str, Any]],
        used_headlines: set,
    ) -> Optional[Dict[str, Any]]:
        """Find the headline that best matches a body story"""
        body_id = body_story['story_id']
        body_content = body_story['raw_content'].lower()

        best_match = None
        best_score = -1

        for headline in headlines:
            if headline['story_id'] in used_headlines:
                continue

            content_score = self._calculate_content_similarity(
                headline['raw_content'].lower(), body_content
            )
            id_distance = self._calculate_id_distance(body_id, headline['story_id'])
            id_score = max(0, 10 - (id_distance / 10))
            combined = (content_score * 0.7) + (id_score * 0.3)

            if combined > best_score:
                best_score = combined
                best_match = headline

        return best_match if best_match and best_score >= 1.0 else None

    def _calculate_content_similarity(self, headline: str, content: str) -> float:
        """Word overlap score between headline and content"""
        stop_words = {
            'this', 'that', 'with', 'from', 'they', 'were', 'been', 'have',
            'will', 'would', 'could', 'should', 'said', 'says', 'also', 'more',
            'most', 'much', 'many', 'some', 'very', 'when', 'where', 'what',
            'which', 'while', 'after', 'before', 'during', 'since', 'until',
            'about', 'above', 'below', 'between', 'through', 'against',
        }
        headline_words = set(re.findall(r'\b[a-z]{4,}\b', headline)) - stop_words
        content_words = set(re.findall(r'\b[a-z]{4,}\b', content[:300])) - stop_words
        score = 0.0
        if headline_words:
            score += len(headline_words & content_words) / len(headline_words) * 5

        headline_entities = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', headline))
        content_entities = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content[:400]))
        score += len(headline_entities & content_entities) * 2

        keywords = [
            'president', 'minister', 'governor', 'senator', 'chairman',
            'commission', 'committee', 'party', 'government', 'assembly',
            'court', 'justice', 'university', 'union', 'movement',
        ]
        for kw in keywords:
            if kw in headline and kw in content:
                score += 1

        return score

    def _calculate_id_distance(self, id1: str, id2: str) -> float:
        """Numeric distance between two hex story IDs"""
        try:
            # IDs are hex like 'u1b2fe' — parse the hex number part
            n1 = int(re.search(r'([0-9a-f]+)', id1.lstrip('u'), re.I).group(1), 16)
            n2 = int(re.search(r'([0-9a-f]+)', id2.lstrip('u'), re.I).group(1), 16)
            return abs(n1 - n2)
        except (AttributeError, ValueError):
            return float('inf')

    def _extract_headline_from_content(self, body_story: Dict[str, Any]) -> str:
        """Fallback: extract headline-like text from body elements"""
        for elem in body_story['content_elements']:
            if elem['is_bold'] and elem['font_size'] > 10 and len(elem['text']) < 100:
                return elem['text']
        paragraphs = body_story.get('paragraphs', [])
        if paragraphs:
            first = paragraphs[0].split('.')[0]
            return (first[:100] + '...') if len(first) > 100 else first
        return ''

    # =========================================================================
    # AUTHOR / CONTENT HELPERS
    # =========================================================================

    def _is_author_paragraph(self, paragraph_text: str, extracted_author: str) -> bool:
        """Check if paragraph is just the author byline"""
        if not extracted_author:
            return False
        escaped = re.escape(extracted_author)
        patterns = [
            rf'^{escaped}',
            rf'^By\s+{escaped}',
            rf'^{escaped},\s+[A-Za-z]+',
        ]
        for pattern in patterns:
            if re.match(pattern, paragraph_text.strip(), re.IGNORECASE):
                return True
        return False

    def _remove_exact_author_from_paragraph(self, paragraph: str, author_name: str) -> str:
        """Remove the author byline from the start of a paragraph"""
        if not author_name:
            return paragraph
        escaped = re.escape(author_name)
        patterns = [
            rf'^{escaped},\s+[A-Za-z]+\s*',
            rf'^{escaped}\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+[A-Za-z]+\s*',
            rf'^{escaped}\s*',
            rf'^{escaped}\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*',
        ]
        for pattern in patterns:
            result = re.sub(pattern, '', paragraph, flags=re.IGNORECASE).strip()
            if result != paragraph:
                return result

        # Fallback: find first article word and cut from there
        match = re.search(
            r'\b(The|A|An|In|On|At|For|With|By|After|Before|During|Since)\b',
            paragraph, re.IGNORECASE
        )
        if match:
            return paragraph[match.start():].strip()

        return paragraph

    def _looks_like_author_line(self, text: str) -> bool:
        patterns = [
            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+[A-Z][a-z]+',
            r'^By\s+[A-Z][a-z]+',
        ]
        for p in patterns:
            if re.match(p, text.strip()):
                return True
        return False

    def _is_metadata_content(self, text: str) -> bool:
        """Reject date headers, captions, page numbers, and newspaper boilerplate."""
        text = text.strip()
        if len(text) < 3:
            return True
        patterns = [
            r'^news$',
            r'^All stories continued on',
            r'^•L-R:',
            r'^\s*$',
            r'^(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),.*\d{4}',
            r'^\d{1,2}$',
            r'^Photo:',
            r'^Continued from',
            # Newspaper boilerplate / disclaimer lines
            r'^We,\s+Punch',
            r'^Printed and Published by',
            r'^Round-the-clock advert',
            r'^E-mail:yourviews',
            r'^Puzzle on Page',
            r'^\+234\d',            # phone number only
            r'^lekansote@',         # columnist email
            r'^kunlesomorin@',
            # Column/section descriptor lines (end with "…" or "...")
            r'.+[.…]{3}\s*$',
        ]
        for p in patterns:
            if re.match(p, text, re.IGNORECASE):
                return True
        return False
