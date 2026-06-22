"""
checkers/pagespeed.py
═══════════════════════════════════════════════════════════════════════════════
PageSpeed Insights Checker — calls the PSI API for BOTH mobile and desktop,
then evaluates Core Web Vitals, accessibility, and Lighthouse SEO scores.
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
from typing import Any, Dict, Optional, Tuple

import requests

from checkers import AuditResult, CategoryResult
from config import (
    CWV_CLS_GOOD,
    CWV_LCP_GOOD,
    CWV_TBT_GOOD,
    PAGESPEED_POINTS,
    PSI_API_KEY,
    PSI_API_URL,
    PSI_DELAY,
    PSI_TIMEOUT,
)

log = logging.getLogger('audit')

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pts(check_key: str) -> Tuple[float, str]:
    """Return (points_possible, priority) for a check key from config."""
    return PAGESPEED_POINTS.get(check_key, (0, 'low'))


def _safe_get(data: dict, *keys, default=None):
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


# ─── Checker ──────────────────────────────────────────────────────────────────

class PageSpeedChecker:
    """Fetch Google PageSpeed Insights for mobile & desktop strategies.

    Usage::

        checker = PageSpeedChecker(url='https://chemdry-example.com')
        result: CategoryResult = checker.run(audit)
    """

    def __init__(self, url: str):
        self.url = url.strip().rstrip('/')
        if not self.url.startswith(('http://', 'https://')):
            self.url = f'https://{self.url}'
        self.is_key_blocked = False
        self.key_was_blocked_warning = False
        self.error_reason = ""

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, audit: AuditResult) -> CategoryResult:
        """Execute all PageSpeed checks and return a populated CategoryResult."""
        cat = CategoryResult(name='PageSpeed Insights', key='pagespeed', icon='⚡')

        # Fetch both strategies
        mobile_data = self._call_psi('mobile')

        if self.is_key_blocked:
            log.warning("PSI API key is restricted. Adding explicit key-blocked errors to all PageSpeed checks.")
            checks_to_add = [
                ('Performance (Mobile)', 'perf_mobile'),
                ('Performance (Desktop)', 'perf_desktop'),
                ('LCP (Largest Contentful Paint)', 'lcp'),
                ('CLS (Cumulative Layout Shift)', 'cls'),
                ('TBT (Total Blocking Time)', 'inp_tbt'),
                ('Accessibility Score', 'accessibility'),
                ('SEO (Lighthouse)', 'seo_lighthouse'),
            ]
            for name, key in checks_to_add:
                pts, pri = _pts(key)
                cat.add(
                    name=name, status='error', priority=pri,
                    points_earned=0, points_possible=pts,
                    value='API error',
                    detail='API Key Restriction: PageSpeed Insights API is blocked by your API key settings.',
                    recommendation=self.error_reason,
                )
            return cat

        desktop_data = self._call_psi('desktop')

        # Performance scores (partial credit)
        self._check_perf_score(cat, mobile_data, strategy='mobile')
        self._check_perf_score(cat, desktop_data, strategy='desktop')

        # Core Web Vitals — prefer mobile data (Google's primary index)
        cwv_source = mobile_data or desktop_data
        self._check_lcp(cat, cwv_source)
        self._check_cls(cat, cwv_source)
        self._check_tbt(cat, cwv_source)

        # Accessibility & SEO — prefer mobile data
        self._check_accessibility(cat, cwv_source)
        self._check_seo_lighthouse(cat, cwv_source)

        # If key restriction was hit and recovered key-lessly, add a friendly advisory note
        if self.key_was_blocked_warning:
            log.info("Adding key restriction notice to CategoryResult summary.")
            # Note: This is an advisory that doesn't penalize the score but informs the user.
            cat.add(
                name='API Key Restriction (Advisory)', status='warn', priority='low',
                points_earned=0.0, points_possible=0.0,
                value='Key Restricted',
                detail='PageSpeed Insights API is blocked by your API Key settings, but the tool automatically recovered using key-less public mode.',
                recommendation='Your Google Cloud API Key is restricted. While the tool successfully ran key-less, you can white-list the "PageSpeed Insights API" under Credentials API Restrictions in the GCP Console to enable high-quota authenticated requests.'
            )

        return cat

    # ── PSI API Call ──────────────────────────────────────────────────────

    def _call_psi(self, strategy: str) -> Optional[Dict[str, Any]]:
        """Call the PageSpeed Insights API for a given strategy.

        Returns the full JSON response or None on failure.
        """
        params = {
            'url': self.url,
            'strategy': strategy,
            'category': ['performance', 'accessibility', 'seo'],
        }
        if PSI_API_KEY and not self.key_was_blocked_warning:
            params['key'] = PSI_API_KEY

        try:
            log.info('Calling PSI API for %s (%s)…', self.url, strategy)
            resp = requests.get(PSI_API_URL, params=params, timeout=PSI_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            log.info('PSI %s response received (HTTP %d)', strategy, resp.status_code)
            return data
        except requests.RequestException as exc:
            log.warning('PSI API error for %s (%s): %s', self.url, strategy, exc)
            if exc.response is not None:
                try:
                    if exc.response.status_code == 403:
                        err_text = exc.response.text
                        if 'API_KEY_SERVICE_BLOCKED' in err_text or 'blocked' in err_text.lower():
                            if PSI_API_KEY and 'key' in params:
                                log.warning("API key is restricted/blocked for PageSpeed Insights API. Retrying key-lessly...")
                                self.key_was_blocked_warning = True
                                # Retry without API key
                                params_no_key = params.copy()
                                params_no_key.pop('key', None)
                                resp = requests.get(PSI_API_URL, params=params_no_key, timeout=PSI_TIMEOUT)
                                resp.raise_for_status()
                                data = resp.json()
                                log.info('PSI %s response received using keyless fallback (HTTP %d)', strategy, resp.status_code)
                                return data
                            else:
                                self.is_key_blocked = True
                                self.error_reason = (
                                    "🔑 GOOGLE CLOUD PLATFORM (GCP) API KEY RESTRICTION ERROR: Your active API key is currently restricted, "
                                    "preventing the Digital Health Monitor tool from accessing the PageSpeed Insights service. "
                                    "When using restricted API keys for security, you MUST explicitly authorize every API service that the key "
                                    "is allowed to call.\n\n"
                                    "To resolve this restriction and allow the tool to gather performance metrics:\n"
                                    "1. Navigate to the Google Cloud Console (https://console.cloud.google.com/).\n"
                                    "2. Ensure you have selected your correct project in the top drop-down menu.\n"
                                    "3. Go to 'APIs & Services' -> 'Credentials' using the left sidebar navigation.\n"
                                    "4. Click the 'Edit API Key' (pencil icon) next to your configured API Key.\n"
                                    "5. Scroll down to the 'API restrictions' section at the bottom.\n"
                                    "6. If 'Restrict key' is selected, click the drop-down and check the box next to 'PageSpeed Insights API'. "
                                    "If you do not see it in the list, search for it first in the GCP Library and click 'Enable'.\n"
                                    "7. Click 'Save' to apply the changes. Allow 3 to 5 minutes for Google to propagate the changes globally, and then rerun this audit."
                                )
                except Exception as fallback_exc:
                    log.warning('PSI keyless fallback retry failed: %s', fallback_exc)
                    self.is_key_blocked = True
                    self.error_reason = (
                        "🔑 GOOGLE CLOUD PLATFORM (GCP) API KEY RESTRICTION ERROR: Your active API key is currently restricted, "
                        "preventing the Digital Health Monitor tool from accessing the PageSpeed Insights service. "
                        "The tool attempted to fallback to keyless anonymous access, but that request failed due to "
                        "rate-limiting (429 Rate Limit Exceeded) from the shared public IP pool.\n\n"
                        "To resolve this restriction and allow high-quota authenticated requests:\n"
                        "1. Navigate to the Google Cloud Console (https://console.cloud.google.com/).\n"
                        "2. Ensure you have selected your correct project in the top drop-down menu.\n"
                        "3. Go to 'APIs & Services' -> 'Credentials' using the left sidebar navigation.\n"
                        "4. Click the 'Edit API Key' (pencil icon) next to your configured API Key.\n"
                        "5. Scroll down to the 'API restrictions' section at the bottom.\n"
                        "6. If 'Restrict key' is selected, click the drop-down and check the box next to 'PageSpeed Insights API'. "
                        "If you do not see it in the list, search for it first in the GCP Library and click 'Enable'.\n"
                        "7. Click 'Save' to apply the changes. Allow 3 to 5 minutes for Google to propagate the changes globally, and then rerun this audit."
                    )
            return None

    # ── Individual Checks ─────────────────────────────────────────────────

    def _check_perf_score(self, cat: CategoryResult, data: Optional[dict],
                          strategy: str):
        """Performance score with partial credit (score/100 × points)."""
        if strategy == 'mobile':
            key = 'perf_mobile'
            name = 'Performance (Mobile)'
        else:
            key = 'perf_desktop'
            name = 'Performance (Desktop)'

        pts, pri = _pts(key)

        if data is None:
            cat.add(
                name=name, status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail=f'Could not retrieve PageSpeed data for {strategy}.',
                recommendation='Check internet connectivity or API rate limits and retry.',
            )
            return

        score_raw = _safe_get(
            data, 'lighthouseResult', 'categories', 'performance', 'score',
            default=None,
        )
        if score_raw is None:
            cat.add(
                name=name, status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no score)',
                detail=f'Performance score not found in {strategy} response.',
                recommendation='Verify the URL is publicly accessible and returns valid HTML.',
            )
            return

        score = round(score_raw * 100)
        earned = round((score / 100) * pts, 2)

        if score >= 90:
            status = 'pass'
        elif score >= 50:
            status = 'warn'
        else:
            status = 'fail'

        rec = ''
        if status == 'fail':
            rec = (
                f"Your {strategy.title()} performance score is currently {score}/100, which is critically low and severely harms your search engine rankings and conversion rates. "
                "Search engines like Google penalize slow-loading sites, especially on mobile devices where network speeds are slower. "
                "To resolve this, you must prioritize optimizing your site's assets: "
                "(1) Optimize and compress all images using next-gen formats like WebP or AVIF; "
                "(2) Defer or minify unused JavaScript and CSS files that block the browser from rendering the page quickly; "
                "(3) Leverage browser caching and utilize a Content Delivery Network (CDN) to serve assets faster."
            )
        elif status == 'warn':
            rec = (
                f"Your {strategy.title()} performance score is {score}/100. While your site is functional, it has noticeable latency "
                "that could cause visitors to bounce before the page fully loads. "
                "We strongly recommend implementing the following optimizations to achieve an excellent score: "
                "(1) Defer non-essential scripts (like tracking codes or chatbots) so they only load after the main content; "
                "(2) Set explicit width and height attributes on all images and containers to prevent layout shifts; "
                "(3) Utilize modern lazy-loading for all below-the-fold images to save initial bandwidth."
            )

        cat.add(
            name=name, status=status, priority=pri,
            points_earned=earned, points_possible=pts,
            value=f'{score}/100',
            detail=f'{strategy.title()} performance score: {score}/100.',
            recommendation=rec,
        )

    def _check_lcp(self, cat: CategoryResult, data: Optional[dict]):
        """Largest Contentful Paint — pass/fail against CWV_LCP_GOOD."""
        pts, pri = _pts('lcp')

        if data is None:
            cat.add(
                name='LCP (Largest Contentful Paint)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail='Could not retrieve LCP data.',
                recommendation='Retry the PageSpeed Insights check.',
            )
            return

        # Try lab data first, then field data
        lcp_ms = _safe_get(
            data, 'lighthouseResult', 'audits', 'largest-contentful-paint',
            'numericValue', default=None,
        )

        if lcp_ms is None:
            # Try CrUX field data
            lcp_ms = _safe_get(
                data, 'loadingExperience', 'metrics',
                'LARGEST_CONTENTFUL_PAINT_MS', 'percentile', default=None,
            )

        if lcp_ms is None:
            cat.add(
                name='LCP (Largest Contentful Paint)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no data)',
                detail='LCP metric not found in response.',
                recommendation='The site may not have enough traffic for field data. Check lab data in Chrome DevTools.',
            )
            return

        lcp_sec = round(lcp_ms / 1000, 2)

        if lcp_sec <= CWV_LCP_GOOD:
            cat.add(
                name='LCP (Largest Contentful Paint)', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{lcp_sec}s',
                detail=f'LCP is {lcp_sec}s (good ≤ {CWV_LCP_GOOD}s).',
            )
        else:
            cat.add(
                name='LCP (Largest Contentful Paint)', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{lcp_sec}s',
                detail=f'LCP is {lcp_sec}s (threshold: ≤ {CWV_LCP_GOOD}s).',
                recommendation=(
                    f"Your Largest Contentful Paint (LCP) is {lcp_sec} seconds, which exceeds the recommended threshold of {CWV_LCP_GOOD}s. "
                    "LCP measures when the main, largest piece of content on your screen (usually a hero banner, large heading, or primary image) becomes visible. A slow LCP makes the page feel laggy and unresponsive to users. "
                    "To speed up LCP: "
                    "(1) Preload your primary hero image or main banner image in the HTML header (using <link rel='preload'>) so it starts downloading immediately; "
                    "(2) Eliminate or defer render-blocking JavaScript and CSS files that delay page construction; "
                    "(3) Optimize server response times and database queries so the server sends the HTML document faster; "
                    "(4) Ensure your web server has Gzip or Brotli compression enabled and utilizes modern image formats like WebP."
                ),
            )

    def _check_cls(self, cat: CategoryResult, data: Optional[dict]):
        """Cumulative Layout Shift — pass/fail against CWV_CLS_GOOD."""
        pts, pri = _pts('cls')

        if data is None:
            cat.add(
                name='CLS (Cumulative Layout Shift)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail='Could not retrieve CLS data.',
                recommendation='Retry the PageSpeed Insights check.',
            )
            return

        cls_val = _safe_get(
            data, 'lighthouseResult', 'audits', 'cumulative-layout-shift',
            'numericValue', default=None,
        )

        if cls_val is None:
            cls_val = _safe_get(
                data, 'loadingExperience', 'metrics',
                'CUMULATIVE_LAYOUT_SHIFT_SCORE', 'percentile', default=None,
            )
            if cls_val is not None:
                cls_val = cls_val / 100  # CrUX returns as hundredths

        if cls_val is None:
            cat.add(
                name='CLS (Cumulative Layout Shift)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no data)',
                detail='CLS metric not found in response.',
                recommendation='Check for layout shift issues manually using Chrome DevTools.',
            )
            return

        cls_val = round(cls_val, 3)

        if cls_val <= CWV_CLS_GOOD:
            cat.add(
                name='CLS (Cumulative Layout Shift)', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=str(cls_val),
                detail=f'CLS is {cls_val} (good ≤ {CWV_CLS_GOOD}).',
            )
        else:
            cat.add(
                name='CLS (Cumulative Layout Shift)', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=str(cls_val),
                detail=f'CLS is {cls_val} (threshold: ≤ {CWV_CLS_GOOD}).',
                recommendation=(
                    f"Your Cumulative Layout Shift (CLS) score is {cls_val}, which is higher than Google's good threshold of {CWV_CLS_GOOD}. "
                    "CLS measures visual stability. A high CLS means elements (like text, images, or buttons) are jumping around on the page while it loads, which frustrates visitors "
                    "who might accidentally click the wrong link or button. "
                    "To fix CLS: "
                    "(1) Ensure every image, video, and iframe has explicit width and height dimensions defined in the HTML/CSS so the browser reserves the correct space beforehand; "
                    "(2) Never inject dynamic content (like promo banners, alerts, or newsletter signups) above existing content after the page has started rendering; "
                    "(3) Use CSS aspect-ratio properties and reserve slots for slow-loading third-party widgets like Google Maps or embedded reviews."
                ),
            )

    def _check_tbt(self, cat: CategoryResult, data: Optional[dict]):
        """Total Blocking Time (proxy for INP) — pass/fail against CWV_TBT_GOOD."""
        pts, pri = _pts('inp_tbt')

        if data is None:
            cat.add(
                name='TBT (Total Blocking Time)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail='Could not retrieve TBT data.',
                recommendation='Retry the PageSpeed Insights check.',
            )
            return

        tbt_ms = _safe_get(
            data, 'lighthouseResult', 'audits', 'total-blocking-time',
            'numericValue', default=None,
        )

        if tbt_ms is None:
            cat.add(
                name='TBT (Total Blocking Time)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no data)',
                detail='TBT metric not found in response.',
                recommendation='Check for long tasks manually using Chrome DevTools Performance panel.',
            )
            return

        tbt_ms = round(tbt_ms)

        if tbt_ms <= CWV_TBT_GOOD:
            cat.add(
                name='TBT (Total Blocking Time)', status='pass', priority=pri,
                points_earned=pts, points_possible=pts,
                value=f'{tbt_ms}ms',
                detail=f'TBT is {tbt_ms}ms (good ≤ {CWV_TBT_GOOD}ms).',
            )
        else:
            cat.add(
                name='TBT (Total Blocking Time)', status='fail', priority=pri,
                points_earned=0, points_possible=pts,
                value=f'{tbt_ms}ms',
                detail=f'TBT is {tbt_ms}ms (threshold: ≤ {CWV_TBT_GOOD}ms).',
                recommendation=(
                    f"Your Total Blocking Time (TBT) is {tbt_ms}ms, which exceeds the recommended limit of {CWV_TBT_GOOD}ms. "
                    "TBT acts as a direct proxy for Google's Interaction to Next Paint (INP) metric, measuring how long the page is unresponsive to user inputs (like clicks or keyboard taps) during load. "
                    "To resolve this: "
                    "(1) Split long-running JavaScript tasks (anything over 50ms) into smaller chunks using setTimeout or requestIdleCallback; "
                    "(2) Remove unused or duplicate JavaScript libraries from your bundle; "
                    "(3) Audit and defer heavy third-party tracking scripts (such as heatmaps, analytics, or complex chat widgets) until after the page is fully interactive."
                ),
            )

    def _check_accessibility(self, cat: CategoryResult, data: Optional[dict]):
        """Lighthouse Accessibility score — partial credit."""
        pts, pri = _pts('accessibility')

        if data is None:
            cat.add(
                name='Accessibility Score', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail='Could not retrieve accessibility data.',
                recommendation='Retry the PageSpeed Insights check.',
            )
            return

        score_raw = _safe_get(
            data, 'lighthouseResult', 'categories', 'accessibility', 'score',
            default=None,
        )

        if score_raw is None:
            cat.add(
                name='Accessibility Score', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no score)',
                detail='Accessibility score not found in response.',
                recommendation='Ensure the accessibility category is included in the PSI request.',
            )
            return

        score = round(score_raw * 100)
        earned = round((score / 100) * pts, 2)

        if score >= 90:
            status = 'pass'
        elif score >= 70:
            status = 'warn'
        else:
            status = 'fail'

        rec = ''
        if status == 'fail':
            rec = (
                f"Your accessibility score is {score}/100, indicating major barriers for users with visual, motor, or cognitive impairments. "
                "Maintaining an accessible website is not only a search ranking factor and brand best practice, but also crucial for legal compliance (ADA). "
                "To fix this immediately: "
                "(1) Ensure all images have descriptive 'alt' attributes so screen readers can describe them; "
                "(2) Increase color contrast between all text and its background (minimum 4.5:1 ratio for body text); "
                "(3) Add proper 'aria-label' attributes to any icon-only buttons or link controls; "
                "(4) Ensure your website is fully navigable using only a keyboard (Tab key navigation)."
            )
        elif status == 'warn':
            rec = (
                f"Your accessibility score is {score}/100. Your site is mostly usable but contains minor compliance issues that should be addressed "
                "to provide a seamless experience for all visitors: "
                "(1) Review contrast ratios on form labels and footer links; "
                "(2) Ensure heading elements (H1, H2, H3) are nested in strict logical order; "
                "(3) Add form field labels that are explicitly associated with their input elements."
            )

        cat.add(
            name='Accessibility Score', status=status, priority=pri,
            points_earned=earned, points_possible=pts,
            value=f'{score}/100',
            detail=f'Lighthouse accessibility score: {score}/100.',
            recommendation=rec,
        )

    def _check_seo_lighthouse(self, cat: CategoryResult, data: Optional[dict]):
        """Lighthouse SEO score — partial credit."""
        pts, pri = _pts('seo_lighthouse')

        if data is None:
            cat.add(
                name='SEO (Lighthouse)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='API error',
                detail='Could not retrieve Lighthouse SEO data.',
                recommendation='Retry the PageSpeed Insights check.',
            )
            return

        score_raw = _safe_get(
            data, 'lighthouseResult', 'categories', 'seo', 'score',
            default=None,
        )

        if score_raw is None:
            cat.add(
                name='SEO (Lighthouse)', status='error', priority=pri,
                points_earned=0, points_possible=pts,
                value='(no score)',
                detail='Lighthouse SEO score not found in response.',
                recommendation='Ensure the SEO category is included in the PSI request.',
            )
            return

        score = round(score_raw * 100)
        earned = round((score / 100) * pts, 2)

        if score >= 90:
            status = 'pass'
        elif score >= 70:
            status = 'warn'
        else:
            status = 'fail'

        rec = ''
        if status == 'fail':
            rec = (
                f"Your website has a low Lighthouse SEO score of {score}/100. This indicates fundamental technical issues that are actively preventing search engines "
                "from crawling, indexing, and ranking your homepage correctly. "
                "To fix this: "
                "(1) Ensure all hyperlinks have crawlable anchor tags with valid 'href' attributes (do not use JavaScript-based navigation); "
                "(2) Provide search engines with clear indexing instructions by fixing any syntax errors in your robots.txt or sitemap.xml; "
                "(3) Make sure your page font sizes are legible on mobile devices (minimum 12px) and that interactive buttons aren't placed too close together."
            )
        elif status == 'warn':
            rec = (
                f"Your website has a solid Lighthouse SEO score of {score}/100. However, there are minor optimization opportunities "
                "to ensure absolute search engine compliance: "
                "(1) Verify that all page links contain descriptive anchor text (avoid generic terms like 'click here' or 'read more'); "
                "(2) Check that all structured data schemas are fully valid and free of parsing warnings."
            )

        cat.add(
            name='SEO (Lighthouse)', status=status, priority=pri,
            points_earned=earned, points_possible=pts,
            value=f'{score}/100',
            detail=f'Lighthouse SEO score: {score}/100.',
            recommendation=rec,
        )
