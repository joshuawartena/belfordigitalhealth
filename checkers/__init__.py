"""
checkers/__init__.py
═══════════════════════════════════════════════════════════════════════════════
Shared data structures for the Digital Health Monitor.
═══════════════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class CheckResult:
    """A single audit check result."""
    name: str                        # e.g., "Title Tag"
    category: str                    # 'website_seo', 'pagespeed', 'gbp'
    status: str                      # 'pass', 'warn', 'fail', 'error', 'skip'
    priority: str                    # 'critical', 'high', 'medium', 'low'
    points_earned: float = 0.0
    points_possible: float = 0.0
    value: str = ''                  # The actual value found
    detail: str = ''                 # Human-readable detail
    recommendation: str = ''         # Actionable fix recommendation

    @property
    def icon(self) -> str:
        return {
            'pass': '✅', 'warn': '⚠️', 'fail': '❌',
            'error': '🔴', 'skip': '⏭️',
        }.get(self.status, '❓')

    @property
    def status_color(self) -> str:
        return {
            'pass': '#22c55e', 'warn': '#f59e0b', 'fail': '#ef4444',
            'error': '#dc2626', 'skip': '#94a3b8',
        }.get(self.status, '#64748b')


@dataclass
class CategoryResult:
    """Results for one audit category (e.g., Website SEO)."""
    name: str                        # Display name: "Website SEO"
    key: str                         # Config key: 'website_seo'
    icon: str = ''                   # Emoji icon for display
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: str, priority: str,
            points_earned: float = 0.0, points_possible: float = 0.0,
            value: str = '', detail: str = '', recommendation: str = ''):
        self.checks.append(CheckResult(
            name=name, category=self.key, status=status, priority=priority,
            points_earned=points_earned, points_possible=points_possible,
            value=value, detail=detail, recommendation=recommendation,
        ))

    @property
    def earned(self) -> float:
        return sum(c.points_earned for c in self.checks)

    @property
    def possible(self) -> float:
        return sum(c.points_possible for c in self.checks)

    @property
    def score(self) -> float:
        """Normalized 0–100 score."""
        if self.possible == 0:
            return 0.0
        return round((self.earned / self.possible) * 100, 1)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status == 'pass')

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == 'fail')

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == 'warn')

    def top_recommendations(self, limit: int = 5) -> List[CheckResult]:
        """Return top failing/warning checks sorted by priority."""
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        actionable = [c for c in self.checks
                      if c.status in ('fail', 'warn') and c.recommendation]
        return sorted(actionable,
                      key=lambda c: priority_order.get(c.priority, 99))[:limit]


@dataclass
class AuditResult:
    """Complete audit result for one franchisee."""
    # ── Identity ──
    name: str = ''
    domain: str = ''
    url: str = ''
    city: str = ''
    state: str = ''
    phone: str = ''
    address: str = ''
    zip_code: str = ''
    owner: str = ''

    # ── GBP input ──
    place_id: str = ''
    gbp_url: str = ''
    business_name: str = ''   # for text search fallback
    expected_category: str = ''  # expected GBP primary category (e.g., 'Carpet Cleaning Service')

    # ── Metadata ──
    audited_at: str = ''
    http_status: int = 0
    error: str = ''

    # ── Category results (set by checkers) ──
    website_seo: Optional[CategoryResult] = None
    pagespeed: Optional[CategoryResult] = None
    gbp: Optional[CategoryResult] = None

    # ── Overall scoring (set by scoring engine) ──
    total_score: float = 0.0
    grade: str = ''
    grade_label: str = ''
    grade_color: str = ''

    @property
    def categories(self) -> List[CategoryResult]:
        """Return all non-None category results."""
        return [c for c in [self.website_seo, self.pagespeed, self.gbp] if c]

    @property
    def all_checks(self) -> List[CheckResult]:
        """Flat list of all check results across categories."""
        results = []
        for cat in self.categories:
            results.extend(cat.checks)
        return results

    @property
    def total_pass(self) -> int:
        return sum(c.pass_count for c in self.categories)

    @property
    def total_fail(self) -> int:
        return sum(c.fail_count for c in self.categories)

    @property
    def total_warn(self) -> int:
        return sum(c.warn_count for c in self.categories)

    def top_recommendations(self, limit: int = 10) -> List[CheckResult]:
        """Top actionable recommendations across all categories."""
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        actionable = [c for c in self.all_checks
                      if c.status in ('fail', 'warn') and c.recommendation]
        return sorted(actionable,
                      key=lambda c: priority_order.get(c.priority, 99))[:limit]
