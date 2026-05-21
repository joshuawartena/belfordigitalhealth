"""
config.py
═══════════════════════════════════════════════════════════════════════════════
Digital Health Monitor — Configuration
═══════════════════════════════════════════════════════════════════════════════

All scoring thresholds, API keys, and weights live here.
Edit this file to tune the rubric for your franchise group.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / '.env')

# ── API Keys ──────────────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')  # Required for GBP (Places API)
# PSI works without a key (rate-limited to ~25k/day), but a key removes limits
# Falls back to GOOGLE_API_KEY if PSI_API_KEY isn't set separately
PSI_API_KEY = os.getenv('PSI_API_KEY', '') or os.getenv('GOOGLE_API_KEY', '')

# ── Scoring Weights (must sum to 1.0) ────────────────────────────────────────
WEIGHTS = {
    'website_seo': 0.40,
    'gbp':         0.40,
    'pagespeed':   0.20,
}

# ── Grade Thresholds ─────────────────────────────────────────────────────────
GRADE_THRESHOLDS = [
    (90, 'A', '#22c55e', 'Excellent'),
    (75, 'B', '#84cc16', 'Good — minor improvements needed'),
    (60, 'C', '#f59e0b', 'Needs attention'),
    (40, 'D', '#f97316', 'Significant issues'),
    ( 0, 'F', '#ef4444', 'Critical — immediate action required'),
]

# ── Website SEO Check Points ─────────────────────────────────────────────────
# Each check has (points_possible, priority)
WEBSITE_SEO_POINTS = {
    'title_tag':            (5, 'high'),
    'title_length':         (3, 'medium'),
    'title_city':           (3, 'medium'),
    'title_brand':          (2, 'medium'),
    'meta_description':     (5, 'high'),
    'meta_desc_length':     (3, 'medium'),
    'meta_desc_quality':    (2, 'medium'),
    'h1_tag':               (5, 'high'),
    'h1_keyword':           (3, 'medium'),
    'heading_hierarchy':    (2, 'medium'),
    'canonical_tag':        (4, 'medium'),
    'viewport_meta':        (3, 'medium'),
    'ssl_https':            (5, 'high'),
    'robots_txt':           (2, 'medium'),
    'xml_sitemap':          (3, 'medium'),
    'schema_jsonld':        (5, 'high'),
    'local_business_schema':(5, 'high'),
    'og_tags':              (3, 'low'),
    'image_alt_text':       (4, 'medium'),
    'image_file_naming':    (3, 'medium'),
    'internal_links':       (3, 'low'),
    'footer_nap':           (5, 'high'),
    'city_page':            (5, 'high'),
    'housecall_pro':        (4, 'medium'),
}

TITLE_MIN_CHARS = 50
TITLE_MAX_CHARS = 60
META_MIN_CHARS = 120
META_MAX_CHARS = 160

# ── PageSpeed Insights Points ────────────────────────────────────────────────
PAGESPEED_POINTS = {
    'perf_mobile':     (10, 'high'),
    'perf_desktop':    (8, 'medium'),
    'lcp':             (5, 'high'),
    'cls':             (4, 'medium'),
    'inp_tbt':         (3, 'medium'),
    'accessibility':   (5, 'medium'),
    'seo_lighthouse':  (5, 'medium'),
}

PSI_PERF_MOBILE_PASS = 50
PSI_PERF_MOBILE_GOOD = 70
PSI_PERF_DESKTOP_PASS = 70
PSI_PERF_DESKTOP_GOOD = 90
PSI_ACCESSIBILITY_PASS = 80
PSI_SEO_PASS = 90

CWV_LCP_GOOD = 2.5       # seconds
CWV_LCP_NEEDS_IMPROVE = 4.0
CWV_CLS_GOOD = 0.1
CWV_TBT_GOOD = 200       # ms (proxy for INP)

# ── Google Business Profile Points ───────────────────────────────────────────
GBP_POINTS = {
    'listing_found':       (5, 'critical'),
    'name_match':          (3, 'high'),
    'phone_present':       (4, 'high'),
    'website_set':         (4, 'high'),
    'address_complete':    (3, 'high'),
    'hours_set':           (5, 'high'),
    'rating':              (5, 'high'),
    'review_count':        (5, 'high'),
    'photos':              (4, 'medium'),
    'category_set':        (3, 'medium'),
    'category_match':      (5, 'critical'),
    'nap_consistency':     (4, 'critical'),
}

GBP_RATING_GOOD = 4.0
GBP_REVIEWS_GOOD = 10
GBP_PHOTOS_MIN = 3

# Expected primary GBP categories by brand keyword (uses Google Places API primaryType values)
# The checker auto-detects the brand from domain/business_name and looks up the expected type.
# CSV 'expected_category' column can override this per-franchisee if needed.
GBP_EXPECTED_CATEGORIES = {
    'chem-dry':   'carpet_cleaning',
    'chemdry':    'carpet_cleaning',
    'n-hance':    'flooring_contractor',
    'nhance':     'flooring_contractor',
    'hoodz':     'commercial_kitchen_exhaust_hood_cleaning',
    'ductz':     'air_duct_cleaning',
    'redbox':    'dumpster_rental',
    'belfor':    'fire_damage_restoration_service',
}

# ── HTTP Settings ────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 15
PSI_TIMEOUT = 60
SCRAPE_DELAY = 0.5
PSI_DELAY = 1.0
USER_AGENT = (
    'Mozilla/5.0 (compatible; DigitalHealthMonitor/2.0; '
    '+https://belforfranchisegroup.com)'
)
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ── PSI API ──────────────────────────────────────────────────────────────────
PSI_API_URL = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'

# ── Places API (New) ─────────────────────────────────────────────────────────
PLACES_TEXT_SEARCH_URL = 'https://places.googleapis.com/v1/places:searchText'
PLACES_DETAILS_URL = 'https://places.googleapis.com/v1/places/'
PLACES_FIELD_MASK = ','.join([
    'places.id',
    'places.displayName',
    'places.formattedAddress',
    'places.nationalPhoneNumber',
    'places.internationalPhoneNumber',
    'places.websiteUri',
    'places.regularOpeningHours',
    'places.rating',
    'places.userRatingCount',
    'places.photos',
    'places.primaryType',
    'places.primaryTypeDisplayName',
    'places.businessStatus',
    'places.reviews',
])
PLACE_DETAILS_FIELD_MASK = ','.join([
    'id',
    'displayName',
    'formattedAddress',
    'nationalPhoneNumber',
    'internationalPhoneNumber',
    'websiteUri',
    'regularOpeningHours',
    'rating',
    'userRatingCount',
    'photos',
    'primaryType',
    'primaryTypeDisplayName',
    'businessStatus',
    'reviews',
])
