"""
checkers/gbp.py
═══════════════════════════════════════════════════════════════════════════════
Google Business Profile Checker — uses the Google Places API (New) to fetch
and evaluate a franchise's GBP listing.

Supports 3 input methods (checked in order):
  1. audit.place_id — use directly
  2. audit.gbp_url — extract place_id from share URL
  3. audit.business_name + audit.city — text search fallback
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

from checkers import AuditResult, CategoryResult
from config import (
    GBP_EXPECTED_CATEGORIES,
    GBP_PHOTOS_MIN,
    GBP_POINTS,
    GBP_RATING_GOOD,
    GBP_REVIEWS_GOOD,
    GOOGLE_API_KEY,
    PLACE_DETAILS_FIELD_MASK,
    PLACES_DETAILS_URL,
    PLACES_FIELD_MASK,
    PLACES_TEXT_SEARCH_URL,
    REQUEST_TIMEOUT,
)

log = logging.getLogger('audit')

_CLEANING_API_TYPES: dict = {
    'carpet_cleaning_service': 'Carpet Cleaning Service',
    'laundry': 'Laundry (raw API type)',
    'laundry_service': 'Laundry Service (raw API type)',
    'dry_cleaning': 'Dry Cleaning',
    'house_cleaning_service': 'House Cleaning Service',
    'janitorial_service': 'Janitorial Service',
    'upholstery_cleaning_service': 'Upholstery Cleaning Service',
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pts(check_key: str) -> Tuple[float, str]:
    """Return (points_possible, priority) for a check key from config."""
    return GBP_POINTS.get(check_key, (0, 'low'))


def _normalize_phone(raw: str) -> str:
    """Strip a phone string down to digits only for comparison."""
    return re.sub(r'\D', '', raw or '')


# ─── Checker ──────────────────────────────────────────────────────────────────

class GBPChecker:
    """Verify and evaluate a franchise's Google Business Profile.

    Usage::

        checker = GBPChecker()
        result: CategoryResult = checker.run(audit)
    """

    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self.session = requests.Session()

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, audit: AuditResult) -> CategoryResult:
        """Execute all GBP checks and return a populated CategoryResult."""
        cat = CategoryResult(name='Google Business Profile', key='gbp', icon='📍')

        # Guard: API key required
        if not self.api_key:
            cat.add(
                name='API Key Required', status='skip', priority='critical',
                detail=(
                    'Google API key is not configured. Set GOOGLE_API_KEY in '
                    'your .env file to enable Google Business Profile checks.'
                ),
            )
            log.warning('GBP checks skipped — GOOGLE_API_KEY not set.')
            return cat

        # Resolve place data
        place_data, place_id = self._resolve_place(audit)

        # Check: listing found
        pts, pri = _pts('listing_found')
        if place_data is None:
            cat.add(
                name='Listing Found', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(not found)',
                detail='Could not locate a Google Business Profile listing.',
                recommendation=(
                    'Verify the business is claimed on Google Business Profile. '
                    'If the listing exists, provide a place_id or Google Maps share URL.'
                ),
            )
            return cat  # Can't run remaining checks without place data

        cat.add(
            name='Listing Found', status='pass', priority=pri,
            points_earned=pts, points_possible=pts,
            value=place_id,
            detail=f'GBP listing found (place_id: {place_id}).',
        )

        # Store place_id on audit for downstream use
        if not audit.place_id:
            audit.place_id = place_id

        # Run all field checks
        self._check_name_match(cat, place_data, audit)
        self._check_phone(cat, place_data)
        self._check_website(cat, place_data)
        self._check_address(cat, place_data)
        self._check_hours(cat, place_data)
        self._check_rating(cat, place_data)
        self._check_review_count(cat, place_data)
        self._check_photos(cat, place_data)
        self._check_category(cat, place_data)
        self._check_category_match(cat, place_data, audit)
        self._check_nap_consistency(cat, place_data, audit)

        return cat

    # ── Place Resolution ──────────────────────────────────────────────────

    def _resolve_place(self, audit: AuditResult) -> Tuple[Optional[Dict[str, Any]], str]:
        """Try to resolve place data from the three input methods.

        Returns (place_data_dict, place_id) or (None, '') on failure.
        """
        # Method 1: Direct place_id
        if audit.place_id:
            log.info('Resolving GBP via place_id: %s', audit.place_id)
            data = self._fetch_place_details(audit.place_id)
            if data:
                return data, audit.place_id

        # Method 2: GBP share URL → extract place_id
        if audit.gbp_url:
            log.info('Resolving GBP via share URL: %s', audit.gbp_url)
            extracted_id = self._extract_place_id_from_url(audit.gbp_url)
            if extracted_id:
                data = self._fetch_place_details(extracted_id)
                if data:
                    return data, extracted_id

            # If standard URL extraction failed, try scraping Maps search using the query parsed from the redirected URL
            try:
                # Tracing the redirected URL to get the 'q' parameter
                resp = self.session.get(
                    audit.gbp_url, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                    headers={'User-Agent': 'Mozilla/5.0'},
                )
                final_url = resp.url
                parsed = urlparse(final_url)
                params = parse_qs(parsed.query)
                if 'q' in params:
                    q_query = params['q'][0]
                    log.info("Redirected URL 'q' parameter found: '%s'. Trying Maps search fallback...", q_query)
                    scraped_id = self._scrape_maps_place_id(q_query)
                    if scraped_id:
                        data = self._fetch_place_details(scraped_id)
                        if data:
                            return data, scraped_id
            except Exception as e:
                log.warning("Share URL redirect trace/scraping fallback failed: %s", e)

        # Method 3: Text search by business name + city
        if audit.business_name and audit.city:
            query = f'{audit.business_name} {audit.city}'
            if audit.state:
                query += f' {audit.state}'
            log.info('Resolving GBP via text search: "%s"', query)
            data, pid = self._text_search(query)
            if data:
                return data, pid

            # SAB Text Search Fallback: standard Places API returns 0 results for SABs.
            # Call Google Maps search scraper fallback!
            log.info("Standard Places API Text Search returned 0 results. Triggering Maps search scraper fallback for: '%s'", query)
            scraped_id = self._scrape_maps_place_id(query)
            if scraped_id:
                data = self._fetch_place_details(scraped_id)
                if data:
                    return data, scraped_id

        log.warning('All GBP resolution methods exhausted — no listing found.')
        return None, ''

    def _scrape_maps_place_id(self, query: str) -> Optional[str]:
        """Query Google Maps search API (/search?tbm=map) to locate active Place ID."""
        url = "https://www.google.com/search"
        params = {
            "tbm": "map",
            "authuser": "0",
            "hl": "en",
            "gl": "us",
            "q": query,
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.google.com/maps/"
        }
        try:
            log.info("Querying Google Maps search API fallback for: '%s'", query)
            resp = self.session.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                text = resp.text
                if text.startswith(")]}'"):
                    text = text[4:]
                
                # Search for Place ID patterns (ChIJ followed by 23 characters)
                pids = re.findall(r'(ChIJ[A-Za-z0-9_-]{23})', text)
                if pids:
                    # De-duplicate while preserving order
                    unique_pids = []
                    for pid in pids:
                        if pid not in unique_pids:
                            unique_pids.append(pid)
                    log.info("Maps search fallback resolved Place IDs: %s", unique_pids)
                    return unique_pids[0]
        except Exception as e:
            log.warning("Google Maps search fallback failed: %s", e)
        return None

    def _fetch_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Fetch place details using Places API (New) Details endpoint."""
        url = f'{PLACES_DETAILS_URL}{place_id}'
        headers = {
            'X-Goog-Api-Key': self.api_key,
            'X-Goog-FieldMask': PLACE_DETAILS_FIELD_MASK,
        }
        try:
            resp = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            log.info('Place details fetched for %s', place_id)
            return data
        except requests.RequestException as exc:
            log.warning('Place Details API error for %s: %s', place_id, exc)
            return None

    def _text_search(self, query: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Search for a place via Places API (New) Text Search endpoint."""
        headers = {
            'X-Goog-Api-Key': self.api_key,
            'X-Goog-FieldMask': PLACES_FIELD_MASK,
            'Content-Type': 'application/json',
        }
        body = {'textQuery': query}
        try:
            resp = self.session.post(
                PLACES_TEXT_SEARCH_URL, json=body, headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            places = data.get('places', [])
            if not places:
                log.info('Text search returned no results for "%s"', query)
                return None, ''
            top = places[0]
            place_id = top.get('id', '')
            log.info('Text search resolved to place_id: %s', place_id)
            return top, place_id
        except requests.RequestException as exc:
            log.warning('Text Search API error for "%s": %s', query, exc)
            return None, ''

    def _extract_place_id_from_url(self, gbp_url: str) -> Optional[str]:
        """Extract place_id from a Google Maps/Business share URL.

        Handles URLs like:
          - https://www.google.com/maps/place/...?...
          - https://maps.app.goo.gl/...  (short link — follows redirects)
          - https://search.google.com/local/...?placeid=ChIJ...
        """
        try:
            # Follow redirects to resolve short links
            resp = self.session.get(
                gbp_url, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0'},
            )
            final_url = resp.url
            log.info('GBP URL resolved to: %s', final_url)
        except requests.RequestException as exc:
            log.warning('Could not follow GBP URL %s: %s', gbp_url, exc)
            final_url = gbp_url

        # Try query param: ?placeid=... or ?place_id=...
        parsed = urlparse(final_url)
        params = parse_qs(parsed.query)
        for key in ('placeid', 'place_id'):
            if key in params:
                return params[key][0]

        # Try to extract from /maps/place/ path with data param
        # Pattern: !1s0x...:0x... or /data=!...!1sChIJ...
        data_match = re.search(r'!1s(ChIJ[A-Za-z0-9_-]+)', final_url)
        if data_match:
            return data_match.group(1)

        # Try extracting from page content as last resort
        try:
            page_text = resp.text if resp else ''
            # Look for place_id patterns in page source
            place_match = re.search(r'"place_id"\s*:\s*"(ChIJ[A-Za-z0-9_-]+)"', page_text)
            if place_match:
                return place_match.group(1)
            # Also try the data attribute pattern
            place_match = re.search(r'ChIJ[A-Za-z0-9_-]{20,}', page_text)
            if place_match:
                return place_match.group(0)
        except Exception:
            pass

        log.warning('Could not extract place_id from URL: %s', gbp_url)
        return None

    # ── Individual Checks ─────────────────────────────────────────────────

    def _check_name_match(self, cat: CategoryResult, place: dict, audit: AuditResult):
        """Check that the GBP display name matches the exact business name provided."""
        pts, pri = _pts('name_match')
        display_name = ''
        name_obj = place.get('displayName')
        if isinstance(name_obj, dict):
            display_name = name_obj.get('text', '')
        elif isinstance(name_obj, str):
            display_name = name_obj

        # Use the full business name (or franchise name) for exact comparison
        expected_name = (audit.business_name or audit.name or '').strip()

        if not expected_name:
            cat.add(
                name='Name Match', status='skip', priority=pri,
                points_earned=0, points_possible=0,
                value=display_name,
                detail='No reference business name provided to compare against.',
            )
            return

        # Normalize both names for comparison: lowercase and strip punctuation
        def normalize(s: str) -> str:
            return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()

        norm_display = normalize(display_name)
        norm_expected = normalize(expected_name)

        # Exact match (after normalization)
        if norm_display == norm_expected:
            cat.add(
                name='Name Match', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=display_name,
                detail=f'GBP name "{display_name}" matches the expected name "{expected_name}".',
            )
        # Close match — one contains the other (e.g. "Forks Chem-Dry" vs "Forks Chem-Dry Carpet Cleaning")
        elif norm_expected in norm_display or norm_display in norm_expected:
            cat.add(
                name='Name Match', status='warn', priority=pri,
                points_earned=round(pts * 0.75, 1), points_possible=pts,
                value=display_name,
                detail=f'GBP name "{display_name}" is a close match but not exact to "{expected_name}".',
                recommendation=(
                    f"🏷️ BUSINESS NAME ALIGNMENT: Your GBP display name is '{display_name}' but the expected "
                    f"franchise name is '{expected_name}'. While these are similar, an exact match is important "
                    "for NAP consistency across all citations. Update the GBP display name to exactly match "
                    f"'{expected_name}' in the GBP dashboard unless there is a specific branding exception "
                    "approved by your franchise organization."
                ),
            )
        else:
            cat.add(
                name='Name Match', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=display_name,
                detail=f'GBP name "{display_name}" does not match expected name "{expected_name}".',
                recommendation=(
                    f"🏷️ CRITICAL NAME MISMATCH: The display name on your Google Business Profile is "
                    f"'{display_name}', but the expected franchise name is '{expected_name}'. An incorrect "
                    "GBP name is a critical local authority and trust issue - it leads to customer confusion, "
                    "damages NAP citation consistency, and can violate national brand guidelines. Update the "
                    f"business display name in the GBP dashboard to exactly match '{expected_name}' in "
                    "compliance with your franchise agreement."
                ),
            )

    def _check_phone(self, cat: CategoryResult, place: dict):
        """Check that a phone number is present."""
        pts, pri = _pts('phone_present')
        phone = place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber', '')

        if phone:
            cat.add(
                name='Phone Present', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=phone,
                detail='Phone number is set on GBP.',
            )
        else:
            cat.add(
                name='Phone Present', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No phone number found on GBP listing.',
                recommendation=(
                    "📞 GBP CONTACT OPTIMIZATION: Your listing is missing a primary phone number. This is a critical barrier "
                    "for customer conversion, preventing searchers from making direct inquiries via mobile 'Call' buttons. "
                    "Add your primary business phone number as the primary contact number on your Google Business Profile immediately. "
                    "If you use call-tracking, ensure it is set as the primary number and add your main office landline as an "
                    "'Additional Phone' under contact details."
                ),
            )

    def _check_website(self, cat: CategoryResult, place: dict):
        """Check that a website URL is set."""
        pts, pri = _pts('website_set')
        website = place.get('websiteUri', '')

        if website:
            cat.add(
                name='Website Set', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=website,
                detail='Website URL is set on GBP.',
            )
        else:
            cat.add(
                name='Website Set', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No website URL found on GBP listing.',
                recommendation=(
                    "🌐 LOCAL-TO-ORGANIC CONNECTION: No website URL is configured on your Google Business Profile. Google relies "
                    "on the linked website to understand your local relevance and match your profile to organic searches. Furthermore, "
                    "customers looking at your listing cannot click through to read about your services or book a cleaning. Add your "
                    "primary, secure franchise homepage URL to the website field in your GBP dashboard to immediately bridge local and "
                    "organic authority."
                ),
            )

    def _check_address(self, cat: CategoryResult, place: dict):
        """Check for a complete formatted address, with native support for Service Area Businesses (SABs)."""
        pts, pri = _pts('address_complete')
        address = place.get('formattedAddress', '')
        primary_type = place.get('primaryType', '') or ''
        primary_type = primary_type.lower()

        # Identify service-oriented categories that typically hide storefront addresses
        is_service_category = any(cat_type in primary_type for cat_type in [
            'clean', 'carpet', 'house', 'home', 'plumb', 'repair', 'laundry', 'service', 'contractor'
        ])

        # Check if address contains a physical street number (e.g. starts with digits followed by letters)
        has_street_address = False
        if address:
            has_street_address = bool(re.search(r'\b\d+\s+[A-Za-z0-9]', address))

        if (not address or not has_street_address) and is_service_category:
            # Perfect pass for a correctly configured Service Area Business (SAB)!
            cat.add(
                name='Address Complete', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Service Area Business (SAB)',
                detail=(
                    'This Google Business Profile is properly configured as a Service Area Business (SAB). '
                    'Its street address is hidden from the public to protect residential privacy, and its territory '
                    'is defined by service area boundaries, which is the exact brand-compliant setup for mobile/on-site service franchisees.'
                ),
            )
        elif address and len(address) > 10:
            cat.add(
                name='Address Complete', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=address[:60],
                detail='Formatted address is set on GBP.',
            )
        elif address:
            cat.add(
                name='Address Complete', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=address,
                detail='Address appears incomplete.',
                recommendation=(
                    "📍 ADDRESS DETAIL VERIFICATION: The address on your Google Business Profile appears incomplete. If you are a "
                    "Service Area Business (SAB) operating from a home office, having a hidden address is correct, but the target "
                    "city, state, and service boundaries must be fully defined. If you operate a physical retail location, ensure "
                    "the full street address, suite number, city, state, and ZIP code are completely filled in to prevent directional "
                    "errors on Google Maps."
                ),
            )
        else:
            cat.add(
                name='Address Complete', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No address found on GBP listing.',
                recommendation=(
                    "📍 CRITICAL ADDRESS VISIBILITY: No address or service boundary area is configured on your Google Business Profile. "
                    "Google's local search algorithms cannot map or display your business without geographic bounds. If you operate "
                    "a retail storefront, you must add your complete street address. If you are a Service Area Business (SAB) cleaning "
                    "carpets on-site at customer homes, do not list a public street address; instead, define your exact target counties, "
                    "cities, and service area radiuses in the GBP dashboard to signal your territory to local searches."
                ),
            )

    def _check_hours(self, cat: CategoryResult, place: dict):
        """Check that business hours are set."""
        pts, pri = _pts('hours_set')
        hours = place.get('regularOpeningHours')

        if hours:
            # Check if hours actually contain period data
            periods = hours.get('periods', []) if isinstance(hours, dict) else []
            if periods:
                cat.add(
                    name='Hours Set', status='pass', priority=pri,
                    points_earned=pts, points_possible=pts,
                    value=f'{len(periods)} period(s)',
                    detail='Business hours are configured on GBP.',
                )
            else:
                cat.add(
                    name='Hours Set', status='warn', priority=pri,
                    points_earned=pts * 0.5, points_possible=pts,
                    value='(partial)',
                    detail='Opening hours object exists but no periods defined.',
                    recommendation=(
                        "🕒 OPERATIONAL HOURS SPECIFICATION: While your hours are initialized, specific operational hours are "
                        "incomplete or missing periods for certain days. Inaccurate hours frustrate potential customers who might try "
                        "to call or visit, and search engines penalize listings with incomplete metadata. Review your calendar in the "
                        "GBP dashboard and set precise opening and closing times for each day of the week, including holiday hours, "
                        "to maximize trust and map visibility."
                    ),
                )
        else:
            cat.add(
                name='Hours Set', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No business hours found on GBP listing.',
                recommendation=(
                    "🕒 CRITICAL AVAILABILITY ACCURACY: No operating hours are set on your Google Business Profile. Google actively "
                    "penalizes listings without defined hours, showing a 'Hours might differ' or warning label to users, which drastically "
                    "reduces call volume and trust. Add your precise daily operational hours (e.g., Mon-Fri 8:00 AM - 5:00 PM) in your "
                    "GBP settings immediately so clients know when your booking office is open and available."
                ),
            )

    def _check_rating(self, cat: CategoryResult, place: dict):
        """Check that rating meets the threshold."""
        pts, pri = _pts('rating')
        rating = place.get('rating')

        if rating is None:
            cat.add(
                name='Rating', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no rating)',
                detail='No rating found on GBP listing.',
                recommendation=(
                    "⭐ ESTABLISH TRUST BARRIER: Your Google Business Profile has no active star rating. In the service industry, "
                    "a star rating is the single most powerful conversion factor. Over 90% of customers consult online reviews before "
                    "selecting a local cleaning service. Implement a proactive post-job review request system immediately. Ask every "
                    "satisfied client to leave a star rating and descriptive feedback using your direct GBP review link to jumpstart "
                    "your local prominence."
                ),
            )
            return

        rating = float(rating)
        if rating >= GBP_RATING_GOOD:
            cat.add(
                name='Rating', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{rating}⭐',
                detail=f'Rating is {rating} (target ≥ {GBP_RATING_GOOD}).',
            )
        else:
            cat.add(
                name='Rating', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{rating}⭐',
                detail=f'Rating is {rating} (below target of {GBP_RATING_GOOD}).',
                recommendation=(
                    f"⭐ REPUTATION IMPROVEMENT OPPORTUNITY: Your current average rating of {rating} stars is below the local "
                    f"franchise goal of {GBP_RATING_GOOD} stars. High ratings directly correlate with improved Map Pack rankings "
                    "and customer booking rates. Elevate your score by: (1) Responding professionally and constructively to all "
                    "low-star reviews to demonstrate excellent client service; (2) Consistently asking highly satisfied clients "
                    "for positive reviews; (3) Addressing common complaints regarding service or promptness."
                ),
            )

    def _check_review_count(self, cat: CategoryResult, place: dict):
        """Check that review count meets the threshold."""
        pts, pri = _pts('review_count')
        count = place.get('userRatingCount')

        if count is None:
            cat.add(
                name='Review Count', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='0 reviews',
                detail='No reviews found.',
                recommendation=(
                    f"💬 REVIEW BUILDING CAMPAIGN: Your Google Business Profile has zero customer reviews. Listings with zero "
                    f"reviews rarely appear in the top 3 Map Pack results and convert at a fraction of established competitors. "
                    f"Launch a review acquisition campaign: send direct follow-up texts or emails with a direct link to your "
                    f"GBP review dashboard immediately after completing service, targeting your best clients first to build momentum."
                ),
            )
            return

        count = int(count)
        if count >= GBP_REVIEWS_GOOD:
            cat.add(
                name='Review Count', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{count} reviews',
                detail=f'{count} reviews (target ≥ {GBP_REVIEWS_GOOD}).',
            )
        else:
            cat.add(
                name='Review Count', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{count} reviews',
                detail=f'Only {count} reviews (below target of {GBP_REVIEWS_GOOD}).',
                recommendation=(
                    f"💬 REVIEW VELOCITY ENHANCEMENT: Your profile has only {count} reviews, which is below the recommended local "
                    f"target of {GBP_REVIEWS_GOOD} reviews. Competitors in your city with higher review counts will capture the "
                    "lion's share of lead volume. Equip your cleaning technicians with print cards containing QR codes leading "
                    "directly to your GBP review page, and incentivize them based on positive reviews that mention their name. "
                    "This builds a consistent review pipeline that local search engines reward."
                ),
            )

    def _check_photos(self, cat: CategoryResult, place: dict):
        """Check that enough photos are uploaded."""
        pts, pri = _pts('photos')
        photos = place.get('photos', [])
        count = len(photos) if isinstance(photos, list) else 0

        if count >= GBP_PHOTOS_MIN:
            cat.add(
                name='Photos', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{count} photos',
                detail=f'{count} photos found (minimum {GBP_PHOTOS_MIN}).',
            )
        elif count > 0:
            cat.add(
                name='Photos', status='warn', priority=pri,
                points_earned=pts * 0.5, points_possible=pts,
                value=f'{count} photos',
                detail=f'Only {count} photo(s) (minimum {GBP_PHOTOS_MIN} recommended).',
                recommendation=(
                    f"📸 VISUAL ENGAGEMENT EXPANSION: Your profile contains only {count} photo(s), which is below the recommended "
                    f"threshold of {GBP_PHOTOS_MIN}. Visual content drives engagement: profiles with abundant photos receive 35% "
                    "more clicks and 42% more driving direction requests. Upload high-resolution, geo-tagged photos of branded "
                    "cleaning vans, staff members in uniform, clean equipment, and dramatic 'before and after' carpet results "
                    "to visually validate your expertise."
                ),
            )
        else:
            cat.add(
                name='Photos', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='0 photos',
                detail='No photos found on GBP listing.',
                recommendation=(
                    f"📸 CRITICAL VISUAL IDENTITY ACTION: Your Google Business Profile has zero photos. A profile without images "
                    "looks unverified, inactive, or abandoned, severely damaging customer confidence and conversion rates. "
                    f"Immediately upload at least {GBP_PHOTOS_MIN} high-quality photos: include a clear exterior/interior view "
                    f"(or branded trucks/vans if an SAB), uniform-clad staff members, professional-grade cleaning equipment, and "
                    f"high-contrast before-and-after project shots to build visual authority."
                ),
            )

    def _check_category(self, cat: CategoryResult, place: dict):
        """Check that a primary business category is set."""
        pts, pri = _pts('category_set')
        primary_type = place.get('primaryType', '')
        display_name = ''
        type_display = place.get('primaryTypeDisplayName')
        if isinstance(type_display, dict):
            display_name = type_display.get('text', '')
        elif isinstance(type_display, str):
            display_name = type_display

        label = display_name or primary_type

        if primary_type:
            cat.add(
                name='Primary Category', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=label,
                detail=f'Primary category is set: "{detail_label}".',
            )
        else:
            cat.add(
                name='Primary Category', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(missing)',
                detail='No primary business category set.',
                recommendation=(
                    "🏷️ PRIMARY CATEGORY RELEVANCE: Your Google Business Profile is missing its primary category. Google's "
                    "ranking engine relies on the primary category above all other signals to understand what queries your listing "
                    "should match. Setting an inaccurate or blank category will completely hide your listing from local searches. "
                    "Set the primary category in your GBP dashboard to 'Carpet Cleaning Service' (or the exact approved primary "
                    "category aligned with Chem-Dry brand standards) to instantly align with high-intent customer queries."
                ),
            )

    def _check_category_match(self, cat: CategoryResult, place: dict, audit: AuditResult):
        """Check that the GBP primary category matches the expected category for this brand.

        Resolution order:
          1. CSV override: audit.expected_category (if provided)
          2. Auto-detect: match brand keywords in domain/business_name against GBP_EXPECTED_CATEGORIES
        """
        pts, pri = _pts('category_match')

        # 1. Determine expected category — CSV override first, then auto-detect from brand
        expected = (audit.expected_category or '').strip()
        detected_brand = ''

        if not expected:
            # Auto-detect brand from domain and business name
            search_text = f"{audit.domain} {audit.business_name} {audit.name}".lower()
            for brand_keyword, expected_type in GBP_EXPECTED_CATEGORIES.items():
                if brand_keyword in search_text:
                    expected = expected_type
                    detected_brand = brand_keyword
                    log.info('Auto-detected brand "%s" → expected GBP category: %s', brand_keyword, expected_type)
                    break

        if not expected:
            # Could not determine expected category — skip without penalty
            cat.add(
                name='Category Match', status='skip', priority=pri,
                points_earned=0, points_possible=0,
                value='(brand not recognized)',
                detail=(
                    'Could not auto-detect the franchise brand to determine expected category. '
                    'Add the brand to GBP_EXPECTED_CATEGORIES in config.py, or provide an '
                    'expected_category column in the CSV.'
                ),
            )
            return

        # 2. Get the GBP primary category from API response
        primary_type = place.get('primaryType', '')
        display_name = ''
        type_display = place.get('primaryTypeDisplayName')
        if isinstance(type_display, dict):
            display_name = type_display.get('text', '')
        elif isinstance(type_display, str):
            display_name = type_display

        friendly = display_name or _CLEANING_API_TYPES.get(primary_type, '')
        label = friendly or primary_type
        detail_label = f'{label} (raw type: {primary_type})' if primary_type and label != primary_type else label

        if not primary_type:
            cat.add(
                name='Category Match', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no category set)',
                detail=f'No primary category is set on the GBP, but expected "{expected}".',
                recommendation=(
                    f"\ud83d\udea8 CRITICAL CATEGORY MISSING: Your Google Business Profile has no primary category set. "
                    f"The expected category for this brand is '{expected}'. Set your primary category immediately "
                    "in the GBP dashboard - this is the single most important ranking factor for local map visibility."
                ),
            )
            return

        # 3. Compare primaryType (API machine value) against expected
        norm_expected = expected.lower().strip()
        norm_type = primary_type.lower().strip()

        if norm_type == norm_expected:
            cat.add(
                name='Category Match', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=label,
                detail=(
                    f'GBP primary category "{label}" (type: {primary_type}) matches the expected '
                    f'category for {detected_brand or "this brand"}.'
                ),
            )
        elif norm_expected in norm_type or norm_type in norm_expected:
            # Partial match
            cat.add(
                name='Category Match', status='warn', priority=pri,
                points_earned=round(pts * 0.5, 1), points_possible=pts,
                value=label,
                detail=(
                    f'GBP primary category "{label}" (type: {primary_type}) is a partial match '
                    f'to expected "{expected}".'
                ),
                recommendation=(
                    f"\ud83c\udff7\ufe0f CATEGORY REFINEMENT: Your GBP primary category is '{label}' (type: {primary_type}), "
                    f"which partially matches the expected '{expected}'. Verify that the exact category is "
                    "available in Google's category list and update if so - precision in category selection "
                    "directly impacts which search queries your listing appears for."
                ),
            )
        else:
            cat.add(
                name='Category Match', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=label,
                detail=(
                    f'GBP primary category "{label}" (type: {primary_type}) does NOT match '
                    f'expected "{expected}" for {detected_brand or "this brand"}.'
                ),
                recommendation=(
                    f"\ud83d\udea8 CRITICAL CATEGORY MISMATCH: Your GBP primary category is '{label}', but the expected "
                    f"category for this franchise brand is '{expected}'. This is a major red flag - an incorrect "
                    "primary category means Google is showing your listing for the WRONG types of searches. "
                    f"Log in to your GBP dashboard immediately and change the primary category to match "
                    f"'{expected}'. You may keep '{label}' as a secondary category if relevant."
                ),
            )

        # Get the GBP primary category display name
        display_name = ''
        type_display = place.get('primaryTypeDisplayName')
        if isinstance(type_display, dict):
            display_name = type_display.get('text', '')
        elif isinstance(type_display, str):
            display_name = type_display

        primary_type = place.get('primaryType', '')
        label = display_name or primary_type

        if not label:
            cat.add(
                name='Category Match', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no category set)',
                detail=f'No primary category is set on the GBP, but expected "{expected}".',
                recommendation=(
                    f"🚨 CRITICAL CATEGORY MISSING: Your Google Business Profile has no primary category set, but "
                    f"the expected category is '{expected}'. Set your primary category immediately in the GBP "
                    "dashboard — this is the single most important ranking factor for local map visibility."
                ),
            )
            return

        # Compare: case-insensitive, flexible matching
        norm_expected = expected.lower().strip()
        norm_label = label.lower().strip()

        if norm_expected == norm_label:
            cat.add(
                name='Category Match', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=label,
                detail=f'GBP primary category "{label}" matches expected category "{expected}".',
            )
        elif norm_expected in norm_label or norm_label in norm_expected:
            # Partial match (e.g. "Carpet Cleaning" vs "Carpet Cleaning Service")
            cat.add(
                name='Category Match', status='warn', priority=pri,
                points_earned=round(pts * 0.5, 1), points_possible=pts,
                value=label,
                detail=f'GBP primary category "{label}" is a partial match to expected "{expected}".',
                recommendation=(
                    f"🏷️ CATEGORY REFINEMENT: Your GBP primary category is '{label}', which partially matches "
                    f"the expected '{expected}'. Verify that the exact category '{expected}' is available in "
                    "Google's category list and update if so — precision in category selection directly impacts "
                    "which search queries your listing appears for."
                ),
            )
        else:
            cat.add(
                name='Category Match', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=label,
                detail=f'GBP primary category "{label}" does NOT match expected "{expected}".',
                recommendation=(
                    f"🚨 CRITICAL CATEGORY MISMATCH: Your GBP primary category is '{label}', but the expected "
                    f"category for this franchise is '{expected}'. This is a major red flag — an incorrect primary "
                    "category means Google is showing your listing for the WRONG types of searches. For example, "
                    f"people searching for '{expected.lower()}' services will not find you in the Map Pack. "
                    f"Log in to your GBP dashboard immediately and change the primary category to '{expected}'. "
                    "You may keep the current category as a secondary category if relevant."
                ),
            )

    def _check_nap_consistency(self, cat: CategoryResult, place: dict, audit: AuditResult):
        """Check that Name, Address, and Phone (NAP) are consistent between GBP and the audit reference sheet."""
        pts, pri = _pts('nap_consistency')

        # 1. Fetch GBP data fields
        gbp_name = ""
        name_obj = place.get('displayName')
        if isinstance(name_obj, dict):
            gbp_name = name_obj.get('text', '')
        elif isinstance(name_obj, str):
            gbp_name = name_obj

        gbp_address = place.get('formattedAddress', '')
        gbp_phone = place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber', '')

        # 2. Track matching status
        mismatches = []
        matches = []
        skipped = []

        # --- Name Check ---
        ref_name = audit.business_name or audit.name
        if ref_name:
            def clean_name(s: str) -> str:
                return re.sub(r'[^a-z0-9]', '', s.lower())

            cleaned_gbp = clean_name(gbp_name)
            cleaned_ref = clean_name(ref_name)

            if cleaned_ref in cleaned_gbp or cleaned_gbp in cleaned_ref:
                matches.append("Name matched")
            else:
                mismatches.append(f"Name mismatch (GBP: '{gbp_name}' vs Reference: '{ref_name}')")
        else:
            skipped.append("Name skipped")

        # --- Phone Check ---
        ref_phone_raw = audit.phone
        ref_phones = []
        if ref_phone_raw:
            parts = re.split(r'[/,|]', ref_phone_raw)
            ref_phones = [_normalize_phone(p) for p in parts if _normalize_phone(p)]

        phone_matched = False
        phone_missing = False
        gbp_digits = _normalize_phone(gbp_phone)
        
        if ref_phones:
            if not gbp_digits:
                mismatches.append("Phone missing on GBP")
                phone_missing = True
            else:
                for ref_p in ref_phones:
                    if gbp_digits == ref_p or gbp_digits.endswith(ref_p[-10:]):
                        phone_matched = True
                        break
                
                if phone_matched:
                    matches.append("Phone matched")
                else:
                    mismatches.append(f"Phone mismatch (GBP: '{gbp_phone}' vs Reference: '{ref_phone_raw}')")
        else:
            skipped.append("Phone skipped")

        # --- Address Check ---
        ref_street = audit.address.strip() if audit.address else ""
        ref_city = audit.city.strip() if audit.city else ""
        ref_state = audit.state.strip() if audit.state else ""
        ref_zip = audit.zip_code.strip() if audit.zip_code else ""

        has_ref_address = any([ref_street, ref_city, ref_state, ref_zip])

        if has_ref_address:
            # Check if this is a Service Area Business (SAB)
            primary_type = place.get('primaryType', '') or ''
            primary_type = primary_type.lower()
            is_service_category = any(cat_type in primary_type for cat_type in [
                'clean', 'carpet', 'house', 'home', 'plumb', 'repair', 'laundry', 'service', 'contractor'
            ])
            has_street_address = False
            if gbp_address:
                has_street_address = bool(re.search(r'\b\d+\s+[A-Za-z0-9]', gbp_address))
            is_sab = not gbp_address or (not has_street_address and is_service_category)

            if is_sab:
                if not gbp_address:
                    matches.append("Address matched (SAB Hidden Address)")
                else:
                    addr_lower = gbp_address.lower()
                    addr_mismatches = []
                    # Check city
                    if ref_city and ref_city.lower() not in addr_lower:
                        addr_mismatches.append(f"City '{ref_city}' mismatch")
                    # Check state
                    if ref_state and ref_state.lower() not in addr_lower:
                        addr_mismatches.append(f"State '{ref_state}' mismatch")
                    
                    if not addr_mismatches:
                        matches.append("Address matched (SAB Service Territory)")
                    else:
                        mismatches.append(f"Address mismatch ({', '.join(addr_mismatches)})")
            else:
                if not gbp_address:
                    mismatches.append("Address missing on GBP")
                else:
                    addr_lower = gbp_address.lower()
                    addr_mismatches = []

                    # Check street number/name if provided
                    if ref_street:
                        street_num_match = re.match(r'^(\d+)', ref_street)
                        if street_num_match:
                            num = street_num_match.group(1)
                            if num not in addr_lower:
                                addr_mismatches.append(f"Street number '{num}' mismatch")
                        
                        # Check first significant word of the street
                        words = [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', ref_street).split() if len(w) > 2]
                        if words:
                            first_sig_word = words[0].lower()
                            if first_sig_word not in ['ave', 'street', 'road', 'suite', 'unit'] and first_sig_word not in addr_lower:
                                addr_mismatches.append(f"Street name '{words[0]}' mismatch")

                    # Check city
                    if ref_city and ref_city.lower() not in addr_lower:
                        addr_mismatches.append(f"City '{ref_city}' mismatch")

                    # Check state
                    if ref_state and ref_state.lower() not in addr_lower:
                        addr_mismatches.append(f"State '{ref_state}' mismatch")

                    # Check zip
                    if ref_zip and ref_zip not in addr_lower:
                        addr_mismatches.append(f"ZIP code '{ref_zip}' mismatch")

                    if not addr_mismatches:
                        matches.append("Address matched")
                    else:
                        mismatches.append(f"Address mismatch ({', '.join(addr_mismatches)})")
        else:
            skipped.append("Address skipped")

        # 3. Determine status and points based on results
        total_elements = (1 if ref_name else 0) + (1 if ref_phones else 0) + (1 if has_ref_address else 0)

        # Detect if a phone mismatch exists
        has_phone_mismatch = any("Phone mismatch" in m for m in mismatches)

        # Generate custom recommendation for Call-Tracking if mismatch is phone-related
        if has_phone_mismatch:
            phone_rec = (
                "⚠️ IMPORTANT NOTE ON CALL-TRACKING: Many franchise owners use a local tracking number "
                "(such as CallRail) as their primary GBP number to measure incoming lead sources, while keeping "
                "their main office number on the website. If this is the case, it is a standard practice and is acceptable, "
                "BUT you must log in to your Google Business Profile dashboard and ensure your main office number "
                f"({ref_phone_raw}) is added as an 'Additional Phone' under the Contact options. This ensures search engines "
                "can still crawl and associate both numbers, preserving your local citation authority behind the scenes. "
                "If you are not using call-tracking, please update your GBP primary number to match your records."
            )
        else:
            phone_rec = (
                "Address any mismatched details immediately. Make sure your Business Name, Address, and Phone (NAP) "
                "are completely identical across your website, Google Business Profile, and all local directory citations. "
                "Google's ranking algorithms rely heavily on NAP consistency to verify your business's legitimacy and local search authority."
            )

        if total_elements == 0:
            cat.add(
                name='NAP Consistency', status='skip', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no reference NAP)',
                detail='No reference NAP data provided in the CSV/parameters to compare.',
            )
            return

        if not mismatches:
            cat.add(
                name='NAP Consistency', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value='Name, Address, & Phone Match',
                detail=f'Consistent NAP found. Matches: {", ".join(matches)}.',
            )
        else:
            # If the name and address matched, but the phone mismatched, downgrade to a warning status 'warn' (giving partial credit) rather than a critical 'fail'
            only_phone_mismatch = has_phone_mismatch and len(mismatches) == 1 and not phone_missing
            
            if only_phone_mismatch:
                earned = round(pts * 0.75, 1)  # Give 75% credit for a phone mismatch due to likely tracking number
                cat.add(
                    name='NAP Consistency', status='warn', priority=pri,
                    points_earned=earned, points_possible=pts,
                    value='Phone Tracking / Mismatch',
                    detail=f'Phone mismatch detected: GBP primary number is {gbp_phone} vs Reference {ref_phone_raw}. Name and Address are fully consistent.',
                    recommendation=phone_rec,
                )
            elif len(mismatches) < total_elements:
                earned = round(pts * 0.5, 1)
                cat.add(
                    name='NAP Consistency', status='warn', priority=pri,
                    points_earned=earned, points_possible=pts,
                    value='Partial NAP Mismatch',
                    detail=f'Mismatches detected: {"; ".join(mismatches)}.',
                    recommendation=f"Make sure your Name and Address match exactly. {phone_rec if has_phone_mismatch else ''}",
                )
            else:
                cat.add(
                    name='NAP Consistency', status='fail', priority=pri,
                    points_earned=0, points_possible=pts,
                    value='NAP Mismatch',
                    detail=f'Critical NAP mismatches: {"; ".join(mismatches)}.',
                    recommendation=f"Critical: Correct the mismatched details on your Google Business Profile immediately. Inconsistent citations severely harm your local map placement. {phone_rec if has_phone_mismatch else ''}",
                )
