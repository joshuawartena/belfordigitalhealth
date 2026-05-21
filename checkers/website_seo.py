"""
checkers/website_seo.py
═══════════════════════════════════════════════════════════════════════════════
Website SEO Checker — crawls the franchise homepage and evaluates on-page SEO.

Ported from the legacy HTMLCollector with additional checks for canonical tags,
viewport meta, SSL/HTTPS, XML sitemap, Open Graph tags, and internal links.
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import logging
import re
import time
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment

from checkers import AuditResult, CategoryResult
from config import (
    HEADERS,
    META_MAX_CHARS,
    META_MIN_CHARS,
    REQUEST_TIMEOUT,
    SCRAPE_DELAY,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
    USER_AGENT,
    WEBSITE_SEO_POINTS,
)

log = logging.getLogger('audit')

_REVIEW_WIDGET_PATTERNS = (
    'birdeye', 'podium.com', 'gatherup', 'grade.us',
    'reviewwave', 'trustpilot', 'reviews.io', 'widewail',
)

_FACEBOOK_SHARE_PATTERNS = (
    'sharer', 'share', 'dialog/feed', 'intent/tweet', 'intent/share',
    '#', 'javascript:',
)

# ─── Helper ──────────────────────────────────────────────────────────────────

def _pts(check_key: str) -> Tuple[float, str]:
    """Return (points_possible, priority) for a check key from config."""
    return WEBSITE_SEO_POINTS.get(check_key, (0, 'low'))


def _normalize_phone(raw: str) -> str:
    """Strip a phone string to digits only for comparison."""
    return re.sub(r'\D', '', raw or '')


# ─── Checker ─────────────────────────────────────────────────────────────────

class WebsiteSEOChecker:
    """Fetch and analyse a franchise homepage for on-page SEO factors.

    Usage::

        checker = WebsiteSEOChecker(domain='chemdry-example.com')
        result: CategoryResult = checker.run(audit)
    """

    def __init__(self, domain: str):
        self.domain = domain.strip().rstrip('/')
        self.base_url = f'https://{self.domain}'
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, audit: AuditResult) -> CategoryResult:
        """Execute all SEO checks and return a populated CategoryResult."""
        cat = CategoryResult(name='Website SEO', key='website_seo', icon='🌐')

        # Fetch homepage HTML
        soup, final_url, http_status = self._fetch_page(self.base_url)
        audit.http_status = http_status

        if soup is None:
            cat.add(
                name='Homepage Reachable',
                status='error',
                priority='critical',
                detail=f'Could not fetch {self.base_url} (HTTP {http_status})',
                recommendation='Ensure the website is live and responds to HTTP requests.',
            )
            return cat

        log.info('Fetched %s (HTTP %d, final URL: %s)', self.base_url, http_status, final_url)

        # Run every check
        self._check_ssl(cat, final_url)
        self._check_title(cat, soup, audit)
        self._check_meta_description(cat, soup, audit)
        self._check_h1(cat, soup, audit)
        self._check_heading_hierarchy(cat, soup)
        self._check_canonical(cat, soup, final_url)
        self._check_viewport(cat, soup)
        self._check_robots_txt(cat)
        self._check_xml_sitemap(cat)
        self._check_schema(cat, soup)
        self._check_og_tags(cat, soup)
        self._check_images(cat, soup)
        self._check_image_file_naming(cat, soup)
        self._check_internal_links(cat, soup, final_url)
        self._check_footer_nap(cat, soup, audit)
        self._check_city_page(cat, audit)
        self._check_housecall_pro(cat, soup, audit)
        self._check_maps_embed(cat, soup, audit)
        self._check_facebook_page(cat, soup)

        return cat

    # ── Network helpers ───────────────────────────────────────────────────

    def _fetch_page(self, url: str) -> Tuple[Optional[BeautifulSoup], str, int]:
        """GET a URL, return (soup, final_url, status_code).

        Returns ``(None, url, 0)`` on network/parse failure.
        """
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            return soup, resp.url, resp.status_code
        except requests.RequestException as exc:
            log.warning('Failed to fetch %s: %s', url, exc)
            status = getattr(getattr(exc, 'response', None), 'status_code', 0)
            return None, url, status

    def _head_ok(self, url: str) -> Tuple[bool, int]:
        """HEAD request — returns (ok, status_code)."""
        try:
            resp = self.session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            return resp.status_code < 400, resp.status_code
        except requests.RequestException:
            return False, 0

    # ── Individual checks ─────────────────────────────────────────────────

    def _check_ssl(self, cat: CategoryResult, final_url: str):
        """Verify the page loaded over HTTPS."""
        pts, pri = _pts('ssl_https')
        is_https = final_url.lower().startswith('https://')
        if is_https:
            cat.add(
                name='SSL / HTTPS', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='HTTPS', detail='Site loads securely over HTTPS, preserving user trust and satisfying a core search engine ranking requirement.',
            )
        else:
            cat.add(
                name='SSL / HTTPS', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='HTTP', detail='Site does NOT load securely over HTTPS. It is using the outdated, insecure HTTP protocol.',
                recommendation='⚠️ CRITICAL SSL SECURITY ACTION: A secure website is a fundamental trust signal for both users and search engines. You must immediately install an SSL/TLS certificate on your web server and configure global 301 redirects to force all HTTP requests to their secure HTTPS equivalents. Without SSL, search engines like Google will flag the site as "Not Secure" to users, driving up bounce rates and directly suppressing your local organic search visibility.',
            )

    # ── Title Tag ─────────────────────────────────────────────────────────

    def _check_title(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        title_tag = soup.find('title')
        title_text = title_tag.get_text(strip=True) if title_tag else ''

        # 1. Title exists
        pts, pri = _pts('title_tag')
        if title_text:
            cat.add(
                name='Title Tag', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=title_text, detail='Title tag is present in the HTML head.',
            )
        else:
            cat.add(
                name='Title Tag', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)', detail='No <title> tag found in the HTML source code.',
                recommendation='⚠️ CRITICAL ON-PAGE SEO ACTION: Your website is missing its most important on-page SEO element: the <title> tag. Search engines rely on this tag to understand what your page is about and display it in Search Engine Results Pages (SERPs). You must immediately add a title tag. For a franchise, the ideal format is: "Carpet Cleaning in [City, State] | [Brand Name]" to target local high-intent search terms.',
            )
            return  # remaining title checks are moot

        # 2. Title length
        pts, pri = _pts('title_length')
        length = len(title_text)
        if TITLE_MIN_CHARS <= length <= TITLE_MAX_CHARS:
            cat.add(
                name='Title Length', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{length} chars',
                detail=f'Title length ({length} characters) is within the optimal search display range ({TITLE_MIN_CHARS}–{TITLE_MAX_CHARS} characters).',
            )
        elif length < TITLE_MIN_CHARS:
            cat.add(
                name='Title Length', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{length} chars',
                detail=f'Title tag is too short ({length} characters, target is {TITLE_MIN_CHARS}–{TITLE_MAX_CHARS} characters).',
                recommendation=f'📈 TITLE OPTIMIZATION OPPORTUNITY: The current title is too short, leaving valuable SEO real estate unused. Expand the title to between 50 and 60 characters by integrating primary local keywords (e.g., "Upholstery & Carpet Cleaning") along with your target city. This maximizes your ranking potential for multiple search terms while retaining a natural, human-friendly presentation.',
            )
        else:
            cat.add(
                name='Title Length', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{length} chars',
                detail=f'Title tag is too long ({length} characters, target is {TITLE_MIN_CHARS}–{TITLE_MAX_CHARS} characters).',
                recommendation=f'✂️ TITLE TRUNCATION WARNING: The title exceeds the recommended limit of {TITLE_MAX_CHARS} characters. Search engines will truncate excessive title lengths with an ellipsis ("...") in search results, creating a messy appearance and reducing CTR. Refactor the title to be under 60 characters by placing your primary high-priority keyword and city name at the front, and branding at the end.',
            )

        # 3. City in title
        pts, pri = _pts('title_city')
        city = (audit.city or '').strip()
        if city and city.lower() in title_text.lower():
            cat.add(
                name='City in Title', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=city, detail=f'City "{city}" found in title, providing a strong local relevancy signal.',
            )
        elif city:
            cat.add(
                name='City in Title', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)', detail=f'City "{city}" was not found in the title tag.',
                recommendation=f'📍 LOCAL SEARCH OPTIMIZATION ACTION: Your title tag does not contain your target city. For local franchise businesses, incorporating the primary service area in the title is absolutely paramount for ranking in local search results. Update the title tag to explicitly include your city name (e.g., "Carpet Cleaning in {city}") to signal strong local relevance to search crawlers.',
            )
        # If no city provided, skip this check silently

        # 4. Brand in title
        pts, pri = _pts('title_brand')
        brand_term = 'chem-dry'
        if brand_term in title_text.lower() or brand_term.replace('-', '') in title_text.lower():
            cat.add(
                name='Brand in Title', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Yes', detail='Brand name is present in the title tag.',
            )
        else:
            cat.add(
                name='Brand in Title', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value='(missing)', detail='Brand name "Chem-Dry" not found in the title tag.',
                recommendation='🏷️ BRAND CITATION RECOMMENDATION: The franchise brand name is missing from the homepage title tag. Including "Chem-Dry" establishes consumer trust, leverages national advertising campaigns, and builds local brand equity. Append " | Chem-Dry" or similar approved brand styling to the end of the title tag to align with national brand standards.',
            )

    # ── Meta Description ──────────────────────────────────────────────────

    def _check_meta_description(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        meta = soup.find('meta', attrs={'name': re.compile(r'^description$', re.I)})
        desc = (meta.get('content', '') if meta else '').strip()

        # 1. Exists
        pts, pri = _pts('meta_description')
        if desc:
            cat.add(
                name='Meta Description', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=desc[:80] + ('…' if len(desc) > 80 else ''),
                detail='Meta description is present in the HTML head.',
            )
        else:
            cat.add(
                name='Meta Description', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)', detail='No meta description tag was found in the HTML head.',
                recommendation='✍️ CRITICAL CTR ACTION: No meta description was found in the HTML source. The meta description acts as your organic ad copy in search results; if it is missing, search engines will auto-generate a snippet from random page text, which often looks disorganized. Write a compelling 120–160 character meta description highlighting your unique selling propositions (e.g., green-certified, fast drying) and a clear call-to-action.',
            )
            return

        # 2. Length
        pts, pri = _pts('meta_desc_length')
        length = len(desc)
        if META_MIN_CHARS <= length <= META_MAX_CHARS:
            cat.add(
                name='Meta Description Length', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{length} chars',
                detail=f'Meta description length ({length} characters) is within the recommended search range ({META_MIN_CHARS}–{META_MAX_CHARS} characters).',
            )
        elif length < META_MIN_CHARS:
            cat.add(
                name='Meta Description Length', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{length} chars',
                detail=f'Meta description is too short ({length} characters, target is {META_MIN_CHARS}–{META_MAX_CHARS} characters).',
                recommendation=f'📈 META DESCRIPTION OPTIMIZATION: The meta description is too short, underutilizing your digital billboard space. Expand the copy to at least 110-120 characters. Detail your proprietary Hot Carbonating Extraction (HCE) process, mention pet-safe green cleaning, and ensure you make a complete, persuasive statement that encourages users to click.',
            )
        else:
            cat.add(
                name='Meta Description Length', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{length} chars',
                detail=f'Meta description is too long ({length} characters, target is {META_MIN_CHARS}–{META_MAX_CHARS} characters).',
                recommendation=f'✂️ META DESCRIPTION TRUNCATION: The meta description exceeds {META_MAX_CHARS} characters. Google and other search engines will truncate the excess text, cut off your call-to-action, and reduce your organic click-through rate. Streamline the message to be between 120 and 155 characters, focusing on punchy, high-impact benefits and a clear contact prompt.',
            )

        # 3. Quality — contains a call-to-action keyword
        pts, pri = _pts('meta_desc_quality')
        cta_keywords = ['call', 'contact', 'schedule', 'free', 'quote',
                        'estimate', 'book', 'today', 'learn', 'get']
        has_cta = any(kw in desc.lower() for kw in cta_keywords)
        if has_cta:
            cat.add(
                name='Meta Description CTA', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Yes', detail='Meta description contains a clear call-to-action keyword.',
            )
        else:
            cat.add(
                name='Meta Description CTA', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value='(none)', detail='No high-impact call-to-action keyword was found in the meta description.',
                recommendation='📞 CALL-TO-ACTION RECOMMENDATION: Your meta description lacks a strong call-to-action (CTA) keyword. A persuasive CTA keyword (such as "Call today", "Schedule a free quote", or "Book online") bridges the gap between searching and booking. Revise the description to include an active, enticing prompt that instructs the user on their next step.',
            )

    # ── H1 Tag ────────────────────────────────────────────────────────────

    def _check_h1(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        h1_tags = soup.find_all('h1')
        h1_text = h1_tags[0].get_text(strip=True) if h1_tags else ''

        # 1. H1 exists (and only one)
        pts, pri = _pts('h1_tag')
        if len(h1_tags) == 1 and h1_text:
            cat.add(
                name='H1 Tag', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=h1_text[:60], detail='Exactly one H1 tag is present on the page, serving as the main topical heading.',
            )
        elif len(h1_tags) > 1:
            cat.add(
                name='H1 Tag', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{len(h1_tags)} H1 tags',
                detail=f'Multiple H1 tags found ({len(h1_tags)}). Standard SEO practices dictate using exactly one primary H1 header per page.',
                recommendation='⚠️ HEADING STRUCTURE WARNING: Multiple <h1> tags were detected on the homepage. The <h1> tag should serve as the singular main title of the page, acting as the primary topical signal. Multiple H1 tags confuse search crawlers and dilute topical authority. Demote secondary H1 tags to <h2> or <h3> headers, leaving only one primary, keyword-optimized <h1> at the top of the page.',
            )
        else:
            cat.add(
                name='H1 Tag', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)', detail='No <h1> tag was found in the HTML document body.',
                recommendation='⚠️ CRITICAL HEADLINE ACTION: No <h1> tag was found. The H1 is the single most important on-page text element for search engines to evaluate what your website homepage is about. You must add exactly one <h1> tag near the top of the page, structured like: "Professional Carpet Cleaning in [City, State]" to immediately establish local topical authority.',
            )
            return

        # 2. Service keyword in H1
        pts, pri = _pts('h1_keyword')
        service_keywords = ['carpet', 'clean', 'upholster', 'tile', 'rug',
                            'stain', 'pet', 'odor', 'floor', 'water']
        has_keyword = any(kw in h1_text.lower() for kw in service_keywords)
        if has_keyword:
            cat.add(
                name='H1 Service Keyword', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Yes', detail='H1 contains a relevant, high-volume service keyword.',
            )
        else:
            cat.add(
                name='H1 Service Keyword', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value='(none)', detail='The <h1> tag does not contain a primary service keyword.',
                recommendation='🔍 HEADLINE OPTIMIZATION: The primary <h1> tag does not contain any core service keywords (such as "carpet", "cleaning", "upholstery", or "rug"). An H1 must clearly declare the main services offered. Rewrite the <h1> to seamlessly include a high-volume search term (e.g., "Your Healthier Carpet Cleaning Choice in [City]") to boost keyword ranking relevance.',
            )

    # ── Heading Hierarchy ─────────────────────────────────────────────────

    def _check_heading_hierarchy(self, cat: CategoryResult, soup: BeautifulSoup):
        """Verify headings follow a logical hierarchy (no skipping levels) and proper order (H1 first)."""
        pts, pri = _pts('heading_hierarchy')
        headings = soup.find_all(re.compile(r'^h[1-6]$', re.I))
        if not headings:
            cat.add(
                name='Heading Hierarchy', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value='(none)', detail='No HTML heading tags (H1-H6) were found on the homepage.',
                recommendation='🏗️ ON-PAGE STRUCTURE RECOMMENDATION: No heading tags (H1-H6) were found on the homepage. Standard HTML headings are essential for dividing content into logical, readable sections for both human visitors and search crawlers. Restructure the page copy by adding a clear heading hierarchy (a singular H1 followed by H2 subheadings and H3 details) to improve accessibility and topical indexing.',
            )
            return

        levels = [int(h.name[1]) for h in headings]
        
        # Check for subheadings before the first H1 tag
        first_h1_index = levels.index(1) if 1 in levels else -1
        subheadings_before_h1 = []
        if first_h1_index > 0:
            for idx in range(first_h1_index):
                subheadings_before_h1.append(f"H{levels[idx]}")

        # Check if levels are skipped
        skipped = False
        for i in range(1, len(levels)):
            if levels[i] > levels[i - 1] + 1:
                skipped = True
                break

        if subheadings_before_h1:
            preceding_str = ", ".join(subheadings_before_h1)
            cat.add(
                name='Heading Hierarchy', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{preceding_str} before H1',
                detail=f'Subheadings ({preceding_str}) were found physically appearing before the first primary H1 tag in the HTML source.',
                recommendation=(
                    '🏗️ OUT-OF-ORDER HEADING WARNING: A subheading (such as H2 or H3) appears physically in the code '
                    'before the primary H1 topic heading. HTML heading hierarchy should always flow sequentially, '
                    'starting with a single H1 as the page title, followed by H2 and H3 tags to organize sections. '
                    'Placing subheadings before the main topic title disrupts the structural outline of your site, '
                    'reducing search crawler understanding and screen reader usability. Demote or re-order these '
                    'preceding subheadings in your theme/code so that the H1 is the first heading in the HTML source.'
                ),
            )
        elif skipped:
            cat.add(
                name='Heading Hierarchy', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=', '.join(f'H{l}' for l in levels[:8]),
                detail='Heading hierarchy is broken because it skips levels (e.g., jumping from H1 directly to H3).',
                recommendation='🏗️ SEQUENTIAL HEADING RECOMMENDATION: The heading hierarchy skips levels (for example, jumping from an H1 directly to an H3). Crawlers and screen readers rely on a strict sequential outline (H1 → H2 → H3) to map your page\'s structure. Adjust your HTML structure so that headings nest logically, ensuring a sequential hierarchy without skipping levels.',
            )
        else:
            cat.add(
                name='Heading Hierarchy', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{len(levels)} headings',
                detail='Heading hierarchy is fully sequential and correct (no levels are skipped and H1 comes first).',
            )

    # ── Canonical Tag ─────────────────────────────────────────────────────

    def _check_canonical(self, cat: CategoryResult, soup: BeautifulSoup, final_url: str):
        """Check for <link rel='canonical'> and verify it matches the page URL."""
        pts, pri = _pts('canonical_tag')
        canonical = soup.find('link', rel='canonical')

        if not canonical or not canonical.get('href'):
            cat.add(
                name='Canonical Tag', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No canonical link element was found in the HTML head.',
                recommendation='🔗 DUPLICATE CONTENT MITIGATION: No canonical link tag was found. Canonical tags tell search engines which version of a URL is the master copy, preventing indexing issues caused by duplicate URL structures (such as http vs https, or www vs non-www). Add a `<link rel="canonical" href="https://[your-domain]/">` to the HTML `<head>` to consolidate all link equity.',
            )
            return

        href = urljoin(final_url, canonical['href'].strip()).rstrip('/')
        normalized_final = final_url.strip().rstrip('/')

        if href.lower() == normalized_final.lower():
            cat.add(
                name='Canonical Tag', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=href,
                detail='Canonical tag matches the active homepage URL, protecting from duplicate indexing issues.',
            )
        else:
            cat.add(
                name='Canonical Tag', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=href,
                detail=f'Canonical tag URL ({href}) does not match the actual page URL ({normalized_final}).',
                recommendation='🔗 CANONICAL MISMATCH WARNING: The canonical URL specified does not match the actual page URL. This mismatch confuses search crawlers and can result in the page being ignored or indexed incorrectly. Update the canonical link tag in the HTML head to precisely match the active URL of the homepage, preserving all search rankings and link value.',
            )

    # ── Viewport Meta ─────────────────────────────────────────────────────

    def _check_viewport(self, cat: CategoryResult, soup: BeautifulSoup):
        """Check for <meta name='viewport'>."""
        pts, pri = _pts('viewport_meta')
        viewport = soup.find('meta', attrs={'name': re.compile(r'^viewport$', re.I)})

        if viewport and viewport.get('content'):
            cat.add(
                name='Viewport Meta', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=viewport['content'][:60],
                detail='Viewport meta tag is present, enabling mobile device optimization.',
            )
        else:
            cat.add(
                name='Viewport Meta', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No viewport meta tag was found in the HTML head.',
                recommendation='📱 MOBILE RESPONSIVENESS ACTION: No viewport meta tag was detected. Over 60% of local cleaning service searches occur on mobile devices. Without a viewport tag, mobile browsers will render the desktop version of your site, resulting in microscopic text, poor usability, and a direct penalty in Google\'s mobile-first indexing. Add `<meta name="viewport" content="width=device-width, initial-scale=1.0">` immediately.',
            )

    # ── robots.txt ────────────────────────────────────────────────────────

    def _check_robots_txt(self, cat: CategoryResult):
        pts, pri = _pts('robots_txt')
        robots_url = f'{self.base_url}/robots.txt'
        ok, status = self._head_ok(robots_url)

        if ok:
            cat.add(
                name='robots.txt', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=robots_url, detail='robots.txt file is present and accessible.',
            )
        else:
            cat.add(
                name='robots.txt', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'HTTP {status}',
                detail=f'robots.txt returned HTTP status code {status} or is completely missing.',
                recommendation='🤖 CRAWLER GUIDANCE ACTION: The robots.txt file was not found or returned a server error. Search engine bots require a robots.txt file at the root directory of your site to understand which sections to crawl and which to ignore. Create and upload a plain text `robots.txt` file (specifying standard access rules and the path to your XML sitemap) to improve crawling efficiency.',
            )
        time.sleep(SCRAPE_DELAY)

    # ── XML Sitemap ───────────────────────────────────────────────────────

    def _check_xml_sitemap(self, cat: CategoryResult):
        """Check if /sitemap.xml is accessible."""
        pts, pri = _pts('xml_sitemap')
        sitemap_url = f'{self.base_url}/sitemap.xml'
        ok, status = self._head_ok(sitemap_url)

        if ok:
            cat.add(
                name='XML Sitemap', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=sitemap_url, detail='XML sitemap is present and accessible.',
            )
        else:
            cat.add(
                name='XML Sitemap', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'HTTP {status}',
                detail=f'sitemap.xml returned HTTP status code {status} or was not found.',
                recommendation='🗺️ SITEMAP DISCOVERY ACTION: No active XML sitemap was located at `/sitemap.xml`. An XML sitemap is a digital map of your website that lists all active pages, allowing search engines to discover and index your services instantly. Generate an XML sitemap and upload it to the root directory, then submit it via Google Search Console to ensure full page indexing.',
            )
        time.sleep(SCRAPE_DELAY)

    # ── Schema / JSON-LD ──────────────────────────────────────────────────

    def _check_schema(self, cat: CategoryResult, soup: BeautifulSoup):
        """Check for structured data (JSON-LD) and LocalBusiness schema."""
        scripts = soup.find_all('script', type='application/ld+json')
        schemas = []
        for script in scripts:
            try:
                data = json.loads(script.string or '{}')
                schemas.append(data)
            except (json.JSONDecodeError, TypeError):
                continue

        # 1. Any JSON-LD present
        pts, pri = _pts('schema_jsonld')
        if schemas:
            types = []
            for s in schemas:
                if isinstance(s, dict):
                    types.append(s.get('@type', 'unknown'))
                elif isinstance(s, list):
                    types.extend(item.get('@type', 'unknown') for item in s if isinstance(item, dict))
            cat.add(
                name='Schema / JSON-LD', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=', '.join(str(t) for t in types[:5]),
                detail=f'Found {len(schemas)} JSON-LD schema block(s) in the HTML source.',
            )
        else:
            cat.add(
                name='Schema / JSON-LD', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(none)',
                detail='No structured JSON-LD data was found in the HTML source code.',
                recommendation='📊 STRUCTURED DATA RECOMMENDATION: No JSON-LD structured data was found on the homepage. Schema markup is a powerful technical SEO tool that directly translates your site\'s information into a machine-readable format. Implement JSON-LD schema (incorporating business details, logo, and social profiles) in the header to earn rich snippets and elevate search engine prominence.',
            )

        # 2. LocalBusiness specifically
        pts, pri = _pts('local_business_schema')
        local_types = ['LocalBusiness', 'HomeAndConstructionBusiness',
                       'CleaningService', 'ProfessionalService']
        found_local = False
        for s in schemas:
            if isinstance(s, dict):
                stype = s.get('@type', '')
                if isinstance(stype, list):
                    if any(t in local_types for t in stype):
                        found_local = True
                elif stype in local_types:
                    found_local = True
            elif isinstance(s, list):
                for item in s:
                    if isinstance(item, dict):
                        stype = item.get('@type', '')
                        if stype in local_types:
                            found_local = True

        if found_local:
            cat.add(
                name='LocalBusiness Schema', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Yes', detail='LocalBusiness (or specific CleaningService) schema type is present.',
            )
        else:
            cat.add(
                name='LocalBusiness Schema', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No specific LocalBusiness (or CleaningService) schema type was detected.',
                recommendation='🏠 LOCAL BUSINESS SCHEMA ACTION: The homepage is missing LocalBusiness (or CleaningService) structured schema. LocalBusiness schema explicitly details your business name, address, phone (NAP), operating hours, service area, and customer reviews to Google. Generating and embedding this JSON-LD block is one of the most effective ways to secure a higher placement in local Google Map Pack results.',
            )

    # ── Open Graph Tags ───────────────────────────────────────────────────

    def _check_og_tags(self, cat: CategoryResult, soup: BeautifulSoup):
        """Check for og:title, og:description, og:image meta tags."""
        pts, pri = _pts('og_tags')
        og_required = ['og:title', 'og:description', 'og:image']
        found = []
        missing = []

        for prop in og_required:
            tag = soup.find('meta', attrs={'property': prop})
            if tag and tag.get('content', '').strip():
                found.append(prop)
            else:
                missing.append(prop)

        if not missing:
            cat.add(
                name='Open Graph Tags', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=', '.join(found),
                detail='All required Open Graph tags (og:title, og:description, og:image) are properly configured in the HTML head.',
            )
        elif found:
            cat.add(
                name='Open Graph Tags', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'Missing: {", ".join(missing)}',
                detail=f'Partial Open Graph implementation detected. Missing tags: {", ".join(missing)}.',
                recommendation=f'📣 SOCIAL LINK PREVIEW RECOMMENDATION: Some Open Graph (OG) tags are missing from the page header. OG tags control how your website\'s link is displayed when shared on social media (Facebook, LinkedIn, etc.). Add the missing tags ({", ".join(missing)}) to guarantee that your social shares look highly professional and drive clicks.',
            )
        else:
            cat.add(
                name='Open Graph Tags', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(none)',
                detail='No Open Graph meta tags were found in the HTML head.',
                recommendation='📣 SOCIAL BRANDING ACTION: No Open Graph meta tags were found in the HTML source. In today\'s digital landscape, social media shares are a major source of referral traffic. Without OG tags, social shares will display arbitrary images and text. Add og:title, og:description, and og:image tags to the HTML head to take control of your social presentation.',
            )

    # ── Image Alt Text ────────────────────────────────────────────────────

    def _check_images(self, cat: CategoryResult, soup: BeautifulSoup):
        """Check that images have alt attributes."""
        pts, pri = _pts('image_alt_text')
        images = soup.find_all('img')
        if not images:
            cat.add(
                name='Image Alt Text', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='0 images', detail='No images present on the homepage to evaluate.',
            )
            return

        missing_alt = [img for img in images if not img.get('alt', '').strip()]
        total = len(images)
        missing = len(missing_alt)
        pct_with_alt = ((total - missing) / total) * 100

        if missing == 0:
            cat.add(
                name='Image Alt Text', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{total}/{total} have alt',
                detail='All homepage images have descriptive alt attributes configured, maximizing accessibility and image search indexing.',
            )
        elif pct_with_alt >= 50:
            cat.add(
                name='Image Alt Text', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{missing}/{total} missing alt',
                detail=f'{missing} out of {total} images are missing alternative text (alt attributes).',
                recommendation='🖼️ IMAGE ACCESSIBILITY RECOMMENDATION: Several images on the homepage are missing "alt" attributes. Alt text serves two critical purposes: it allows screen readers for visually impaired users to understand the image, and it enables search engines to index your images in Google Image Search. Audit all <img> tags and add descriptive, keyword-rich alt text to each.',
            )
        else:
            cat.add(
                name='Image Alt Text', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{missing}/{total} missing alt',
                detail=f'Crucial image alt text is missing on {missing} out of {total} images.',
                recommendation='🖼️ CRITICAL ACCESSIBILITY ACTION: The majority of images on the homepage are missing alt text. This is a significant accessibility violation and a missed opportunity to rank in image search results. You must immediately add descriptive, helpful alt text to all image tags, describing the service, location, or equipment shown (e.g., "Chem-Dry technician cleaning upholstery in [City]").',
            )

    # ── Image File Naming ─────────────────────────────────────────────────

    def _check_image_file_naming(self, cat: CategoryResult, soup: BeautifulSoup):
        """Audit all <img> tag filenames on the homepage for generic/unoptimized names."""
        pts, pri = _pts('image_file_naming')
        images = soup.find_all('img')
        
        # Filter out images without src
        img_srcs = [img.get('src') for img in images if img.get('src')]
        if not img_srcs:
            cat.add(
                name='Image File Naming', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='0 images',
                detail='No images present on the homepage to evaluate.',
            )
            return

        generic_keywords = {
            'spacer', 'logo', 'image', 'img', 'banner', 'bg', 'background', 'icon', 
            'button', 'pic', 'photo', 'header', 'footer', 'asset', 'thumbnail', 
            'placeholder', 'slider', 'slide', 'temp', 'default', 'graphic', 'avatar'
        }
        
        # Regex to detect hex hashes (8 to 64 chars) or pure numeric names
        hash_pattern = re.compile(r'^[a-fA-F0-9]{8,64}$|^\d+$')
        
        total_images = len(img_srcs)
        generic_count = 0
        generic_examples = []
        
        for src in img_srcs:
            # Extract filename without path and query params
            parsed_src = urlparse(src)
            path = parsed_src.path
            filename_with_ext = path.split('/')[-1] if '/' in path else path
            
            # Split filename and extension
            if '.' in filename_with_ext:
                filename = filename_with_ext.rsplit('.', 1)[0]
            else:
                filename = filename_with_ext
            
            filename_lower = filename.lower()
            
            # Check if filename matches generic list or regex hash
            is_generic = False
            
            # Clean filename by stripping common separators like hyphens/underscores to match generic words
            cleaned_filename = re.sub(r'[-_]', '', filename_lower)
            
            if cleaned_filename in generic_keywords or any(kw in filename_lower for kw in ['image', 'img', 'photo', 'pic', 'slider', 'banner']):
                is_generic = True
            elif hash_pattern.match(filename):
                is_generic = True
                
            if is_generic:
                generic_count += 1
                if filename_with_ext not in generic_examples:
                    generic_examples.append(filename_with_ext)

        generic_pct = (generic_count / total_images) * 100 if total_images > 0 else 0
        
        # Grading rubric:
        # - ≤ 30% generic: Perfect Pass (full points)
        # - 30% - 70% generic: Warning (50% points)
        # - > 70% generic: Fail (0 points)
        
        examples_str = ", ".join(generic_examples[:5])
        if generic_pct <= 30:
            cat.add(
                name='Image File Naming', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{generic_count}/{total_images} generic',
                detail=f'Only {generic_pct:.1f}% of homepage images use unoptimized or generic filenames, which is well within best practices.',
            )
        elif generic_pct <= 70:
            cat.add(
                name='Image File Naming', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{generic_count}/{total_images} generic ({generic_pct:.1f}%)',
                detail=f'{generic_count} out of {total_images} images on the homepage use generic or unoptimized filenames.',
                recommendation=(
                    f"🖼️ LOCAL IMAGE SEO OPPORTUNITY: Your homepage contains several images with generic names (e.g., {examples_str}). "
                    f"Search engine crawlers cannot read the visual content of your images directly; they rely heavily on the file "
                    f"name and alt text to understand the context. Unoptimized names like 'image1.jpg' or hash codes miss a major opportunity "
                    f"to index for local keywords. Rename these image files using descriptive, hyphen-separated keywords that reflect the "
                    f"location, brand, and service (for example, 'carpet-cleaning-forts-chemdry.jpg' instead of '{generic_examples[0] if generic_examples else 'image1.jpg'}')."
                ),
            )
        else:
            cat.add(
                name='Image File Naming', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{generic_count}/{total_images} generic ({generic_pct:.1f}%)',
                detail=f'A critical majority ({generic_pct:.1f}%) of homepage images use unoptimized or generic filenames.',
                recommendation=(
                    f"⚠️ CRITICAL IMAGE FILENAME AUDIT: Almost all images on your homepage use generic names or hash-like codes (e.g., {examples_str}). "
                    f"This is a major on-page SEO deficiency. Search engines actively index descriptive image filenames to understand "
                    f"relevance and rank your site for Google Image Search. You must immediately rename these image files to use highly specific, "
                    f"local-keyword-rich names (e.g., 'chemdry-carpet-cleaning-van-denver.png') before uploading them to your server. "
                    f"This significantly improves your website's overall topical indexation."
                ),
            )

    # ── Internal Links ────────────────────────────────────────────────────

    def _check_internal_links(self, cat: CategoryResult, soup: BeautifulSoup, final_url: str):
        """Count internal links on homepage — pass if ≥3."""
        pts, pri = _pts('internal_links')
        parsed_base = urlparse(final_url)
        base_domain = parsed_base.netloc.lower()

        internal_count = 0
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Resolve relative URLs
            full_url = urljoin(final_url, href)
            parsed = urlparse(full_url)
            link_domain = parsed.netloc.lower()

            # Check if it's internal (same domain or subdomain)
            if link_domain == base_domain or link_domain.endswith('.' + base_domain):
                # Exclude self-referencing anchors (#) and mailto/tel
                if parsed.scheme in ('http', 'https') and parsed.path not in ('', '/'):
                    internal_count += 1

        if internal_count >= 3:
            cat.add(
                name='Internal Links', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{internal_count} links',
                detail=f'Found {internal_count} internal links, establishing strong crawl paths for search crawlers.',
            )
        elif internal_count > 0:
            cat.add(
                name='Internal Links', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{internal_count} links',
                detail=f'Only {internal_count} internal links were found on the homepage, which is below the recommended threshold of 3.',
                recommendation='🔗 CRAWLABILITY RECOMMENDATION: The homepage has fewer than 3 internal links to other pages on your site. Search engine bots rely on internal links to crawl deeper into your website and distribute authority. Add descriptive text links pointing directly to your key service pages (e.g., Carpet Cleaning, Upholstery Cleaning, Pet Odor Removal) to improve indexation.',
            )
        else:
            cat.add(
                name='Internal Links', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='0 links',
                detail='No valid, crawlable internal links were found on the homepage.',
                recommendation='🔗 CRITICAL SITE INDEXATION ACTION: No internal links were found on your homepage. This creates a severe crawlability bottleneck, leaving your subpages orphaned and invisible to search crawlers. Add a navigation menu or text links linking directly to your core service pages, about page, and contact page. This is essential to guide bots and users through your site.',
            )

    # ── Footer NAP ────────────────────────────────────────────────────────

    def _check_footer_nap(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        """Check that the footer contains Name, Address, and Phone (NAP)."""
        pts, pri = _pts('footer_nap')
        footer = soup.find('footer')
        if not footer:
            # Fallback: look in the last ~25% of the page
            all_text = soup.get_text(' ', strip=True)
            footer_text = all_text[-(len(all_text) // 4):]
        else:
            footer_text = footer.get_text(' ', strip=True)

        nap_found = []
        nap_missing = []

        # Phone
        phone_digits = _normalize_phone(audit.phone)
        if phone_digits and phone_digits in _normalize_phone(footer_text):
            nap_found.append('Phone')
        elif phone_digits:
            nap_missing.append('Phone')

        # City/Address
        city = (audit.city or '').strip()
        if city and city.lower() in footer_text.lower():
            nap_found.append('City/Address')
        elif city:
            nap_missing.append('City/Address')

        # Brand/Name
        brand_term = 'chem-dry'
        if brand_term in footer_text.lower() or brand_term.replace('-', '') in footer_text.lower():
            nap_found.append('Name')
        else:
            nap_missing.append('Name')

        if not nap_missing:
            cat.add(
                name='Footer NAP', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=', '.join(nap_found),
                detail='A complete Name, Address, and Phone (NAP) block was found in the footer, solidifying local search credibility.',
            )
        elif len(nap_found) >= 1:
            cat.add(
                name='Footer NAP', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'Missing: {", ".join(nap_missing)}',
                detail=f'Incomplete footer NAP block. Missing elements: {", ".join(nap_missing)}.',
                recommendation=f'👣 CITATION COMPLETENESS ACTION: Your website footer contains incomplete Name, Address, and Phone (NAP) details. A local business\'s footer must display a complete and exact match of its NAP details to serve as a persistent local citation. Add the missing elements (Business Name, Address, and/or Phone) to the footer to build solid local search authority.',
            )
        else:
            cat.add(
                name='Footer NAP', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(none)',
                detail='No business NAP (Name, Address, Phone) information was detected in the footer text.',
                recommendation='👣 CRITICAL FOOTER CITATION ACTION: No Name, Address, or Phone (NAP) data was found in your homepage footer. In local SEO, a consistent footer NAP block is a core citation that search engines look for to verify your geographical location and business legitimacy. Add your official franchise name, full physical/service-area address, and primary phone number to the footer immediately.',
            )

    # ── City Page ─────────────────────────────────────────────────────────

    def _check_city_page(self, cat: CategoryResult, audit: AuditResult):
        """Check for a dedicated city/location page."""
        pts, pri = _pts('city_page')
        city = (audit.city or '').strip()
        if not city:
            cat.add(
                name='City Page', status='skip', priority=pri,
                points_earned=0, points_possible=0.0,
                value='(no city provided)',
                detail='City page check was skipped because no target city was provided in the reference parameters.',
            )
            return

        city_slug = city.lower().replace(' ', '-')
        candidate_paths = [
            f'/{city_slug}',
            f'/{city_slug}/',
            f'/locations/{city_slug}',
            f'/service-areas/{city_slug}',
            f'/areas-served/{city_slug}',
            f'/{city_slug}-{audit.state.lower() if audit.state else ""}',
        ]

        for path in candidate_paths:
            url = self.base_url + path
            ok, status = self._head_ok(url)
            if ok:
                cat.add(
                    name='City Page', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value=url,
                    detail=f'Found an active dedicated city landing page at {url}.',
                )
                return
            time.sleep(SCRAPE_DELAY)

        cat.add(
            name='City Page', status='fail', priority=pri,
            points_earned=0, points_possible=pts,
            value='(not found)',
            detail=f'No active landing page was found under common URL paths for city "{city}".',
            recommendation=f'📍 LOCAL TARGETING OPPORTUNITY: No dedicated local city page was found (such as /{city_slug}). Creating a dedicated service page for your primary city is a highly effective strategy to capture high-intent local search traffic. Develop a high-quality local page featuring localized service text, customer reviews from the area, a local phone number, and a map embed to capture regional customers.',
        )

    # ── HouseCall Pro ───────────────────────────────────────────────────────

    def _check_housecall_pro(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        """Check if the Chem-Dry franchisee is utilizing the brand-approved HouseCall Pro online booking platform."""
        pts, pri = _pts('housecall_pro')

        # Check if this is a Chem-Dry franchise
        brand_name = (audit.business_name or audit.name or '').lower()
        domain_name = (audit.domain or '').lower()
        is_chemdry = any(term in brand_name or term in domain_name for term in ('chemdry', 'chem-dry'))

        if not is_chemdry:
            # Skip for non-Chem-Dry brands with 0.0 possible points so they are not penalized
            cat.add(
                name='HouseCall Pro Integration', status='skip', priority=pri,
                points_earned=0.0, points_possible=0.0,
                value='(not applicable)',
                detail='HouseCall Pro booking check is skipped because this is not a Chem-Dry franchise (opt-in for other brands).',
            )
            return

        # Perform detection across scripts, links, and frames
        found = False
        booking_url = ''

        # 1. Check anchor tags
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'housecallpro.com' in href or 'housecall.io' in href:
                found = True
                booking_url = a['href']
                break

        # 2. Check iframes
        if not found:
            for iframe in soup.find_all('iframe', src=True):
                src = iframe['src'].lower()
                if 'housecallpro.com' in src or 'housecall.io' in src:
                    found = True
                    booking_url = iframe['src']
                    break

        # 3. Check scripts
        if not found:
            for script in soup.find_all('script'):
                if script.get('src'):
                    src = script['src'].lower()
                    if 'housecallpro' in src or 'housecall.io' in src:
                        found = True
                        break
                if script.string:
                    content = script.string.lower()
                    if 'housecallpro' in content or 'housecall.io' in content:
                        found = True
                        break

        # 4. Fallback: raw HTML string check
        if not found:
            raw_html_lower = str(soup).lower()
            if 'housecallpro.com' in raw_html_lower or 'housecall.io' in raw_html_lower:
                found = True

        if found:
            val_str = booking_url if booking_url else 'Detected'
            cat.add(
                name='HouseCall Pro Integration', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=val_str[:60],
                detail='Active HouseCall Pro online booking integration was successfully detected on the website.',
            )
        else:
            cat.add(
                name='HouseCall Pro Integration', status='fail', priority=pri,
                points_earned=0.0, points_possible=pts,
                value='Not Detected',
                detail='No active HouseCall Pro online booking integration was found on the homepage.',
                recommendation=(
                    "📞 HOUSECALL PRO INTEGRATION OPTIMIZATION: Your website does not appear to have an active HouseCall Pro booking widget or link. "
                    "HouseCall Pro is the official, brand-approved CRM and online booking platform for Chem-Dry. Integrating the HouseCall Pro booking "
                    "widget directly onto your website allows customers to view real-time availability, select services, and book jobs 24/7 without "
                    "needing to call. This significantly increases your digital conversion rates and streamlines scheduling. Please contact WMS Support "
                    "or log in to your HouseCall Pro dashboard to retrieve your online booking link and embed it as a prominent call-to-action button "
                    "(e.g., 'Book Online Now') on your homepage."
                ),
            )

    # ── Google Maps / Reviews Embed ────────────────────────────────────────

    def _check_maps_embed(self, cat: CategoryResult, soup: BeautifulSoup, audit: AuditResult):
        """Check for a Google Maps iframe, Maps link, or embedded review widget."""
        pts, pri = _pts('maps_embed')

        # 1. Google Maps iframe embed
        for iframe in soup.find_all('iframe', src=True):
            src = iframe['src'].lower()
            if 'maps.google.com' in src or 'google.com/maps' in src:
                cat.add(
                    name='Maps / Reviews Embed', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value='Google Maps iframe',
                    detail='An embedded Google Maps iframe was found on the homepage, providing a strong local trust and engagement signal.',
                )
                return

        # 2. Google Maps anchor link (not a share link)
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if ('maps.google.com' in href or 'google.com/maps' in href) and 'share' not in href:
                cat.add(
                    name='Maps / Reviews Embed', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value='Google Maps link',
                    detail='A Google Maps link was found on the homepage.',
                )
                return

        # 3. Embedded review widgets (Birdeye, Podium, GatherUp, Trustpilot, etc.)
        review_widget_patterns = [
            'birdeye', 'podium.com', 'gatherup', 'grade.us',
            'reviewwave', 'trustpilot', 'reviews.io', 'widewail',
        ]
        raw_html_lower = str(soup).lower()
        for pattern in review_widget_patterns:
            if pattern in raw_html_lower:
                cat.add(
                    name='Maps / Reviews Embed', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value=f'{pattern} widget',
                    detail=f'An embedded review widget ({pattern}) was detected on the homepage.',
                )
                return

        cat.add(
            name='Maps / Reviews Embed', status='fail', priority=pri,
            points_earned=0, points_possible=pts,
            value='(not found)',
            detail='No Google Maps embed or review widget was found on the homepage.',
            recommendation=(
                '📍 LOCAL TRUST SIGNAL OPPORTUNITY: Your homepage does not include a Google Maps embed or a review widget. '
                'Embedding a Google Map pinned to your business location provides a clear visual trust signal and reinforces your '
                'local presence to both visitors and search crawlers. Consider adding a Google Maps iframe via Google My Business '
                '"Share" → "Embed a map", or integrate a review widget (such as Birdeye or Podium) to display live Google reviews '
                'directly on the page — increasing credibility and local conversion rates.'
            ),
        )

    # ── Facebook Page Link ─────────────────────────────────────────────────

    def _check_facebook_page(self, cat: CategoryResult, soup: BeautifulSoup):
        """Check for a Facebook page link (excluding share/sharer buttons)."""
        pts, pri = _pts('facebook_page')

        # Patterns that indicate a share button rather than a page link
        _share_patterns = ('sharer', 'share', 'dialog/feed', 'intent/tweet',
                           'intent/share', '#', 'javascript:')

        for a in soup.find_all('a', href=True):
            href = a['href']
            href_lower = href.lower()
            if 'facebook.com' not in href_lower:
                continue
            # Skip share / sharer buttons
            if any(p in href_lower for p in _share_patterns):
                continue
            # Must be a real page path (facebook.com/<something>)
            parsed = urlparse(href)
            path = parsed.path.strip('/')
            if path:  # non-empty path → actual page, not bare domain
                cat.add(
                    name='Facebook Page Link', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value=href[:80],
                    detail='A Facebook page link was found on the homepage, connecting the site to the brand\'s social presence.',
                )
                return

        cat.add(
            name='Facebook Page Link', status='warn', priority=pri,
            points_earned=0, points_possible=pts,
            value='(not found)',
            detail='No Facebook page link was detected on the homepage.',
            recommendation=(
                '📘 SOCIAL PRESENCE RECOMMENDATION: No Facebook page link was found on the homepage. '
                'Linking to your active Facebook Business Page strengthens social trust signals and gives visitors a '
                'convenient path to read reviews and stay connected. Add a Facebook icon link in the header or footer '
                'pointing to your franchise\'s official Facebook page.'
            ),
        )

