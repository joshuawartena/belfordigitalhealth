"""
scoring.py
═══════════════════════════════════════════════════════════════════════════════
Digital Health Monitor — Weighted Scoring Engine
═══════════════════════════════════════════════════════════════════════════════

Computes weighted total scores from individual category results, assigns
letter grades based on configurable thresholds, and provides a rich console
summary for network-wide batch audits.
"""

import logging
from collections import Counter
from typing import List

import config
from checkers import AuditResult

logger = logging.getLogger(__name__)

# ── ANSI Colors for console output ───────────────────────────────────────────
_BOLD = '\033[1m'
_DIM = '\033[2m'
_RESET = '\033[0m'
_GREEN = '\033[92m'
_YELLOW = '\033[93m'
_RED = '\033[91m'
_CYAN = '\033[96m'
_MAGENTA = '\033[95m'
_WHITE = '\033[97m'

# Bar chart characters
_BAR_FILLED = '█'
_BAR_EMPTY = '░'


def calculate_scores(audit: AuditResult) -> AuditResult:
    """Compute the weighted total score and assign a letter grade.

    For each active category (website_seo, pagespeed, gbp), the category's
    ``.score`` property already produces a 0–100 value (earned / possible * 100).
    This function combines them using the weights defined in ``config.WEIGHTS``
    and assigns a grade via ``config.GRADE_THRESHOLDS``.

    Args:
        audit: An AuditResult whose category results have already been
               populated by the individual checkers.

    Returns:
        The same AuditResult instance, mutated with ``total_score``, ``grade``,
        ``grade_color``, and ``grade_label`` fields set.
    """
    # ── Step 1: Weighted total ────────────────────────────────────────────
    total = 0.0
    total_weight = 0.0

    for key in ('website_seo', 'pagespeed', 'gbp'):
        cat = getattr(audit, key, None)
        if cat is not None and cat.possible > 0:
            # Detect fatal API/system errors (where all checks inside a category returned 'error')
            # and dynamically exclude them so they do not unfairly penalize the audit grade
            all_errors = len(cat.checks) > 0 and all(c.status == 'error' for c in cat.checks)
            if all_errors:
                logger.warning(
                    "Category '%s' encountered fatal API/system errors and will be "
                    "dynamically excluded from the overall scoring normalization.",
                    key
                )
                continue

            weight = config.WEIGHTS.get(key, 0.0)
            total += cat.score * weight
            total_weight += weight
            logger.debug(
                "Category %-12s  score=%5.1f  weight=%.2f  contribution=%5.1f",
                key, cat.score, weight, cat.score * weight,
            )

    # Normalize if some categories were skipped (e.g. --no-gbp)
    if total_weight > 0:
        audit.total_score = round(total / total_weight, 1)
    else:
        audit.total_score = 0.0
        logger.warning("No category results available for %s", audit.domain)

    # ── Step 2: Grade assignment ──────────────────────────────────────────
    for threshold, grade, color, label in config.GRADE_THRESHOLDS:
        if audit.total_score >= threshold:
            audit.grade = grade
            audit.grade_color = color
            audit.grade_label = label
            break

    logger.info(
        "Scored %s → %.1f (%s — %s)",
        audit.domain, audit.total_score, audit.grade, audit.grade_label,
    )

    return audit


# ─────────────────────────────────────────────────────────────────────────────
# Console Summary
# ─────────────────────────────────────────────────────────────────────────────

def _bar(value: float, max_value: float, width: int = 30) -> str:
    """Render a proportional bar chart string."""
    if max_value <= 0:
        return _BAR_EMPTY * width
    filled = int(round(value / max_value * width))
    return _BAR_FILLED * filled + _BAR_EMPTY * (width - filled)


def _grade_ansi(grade: str) -> str:
    """Return an ANSI-colored grade string."""
    if grade == 'A':
        return f"{_GREEN}{_BOLD}{grade}{_RESET}"
    elif grade == 'B':
        return f"{_GREEN}{grade}{_RESET}"
    elif grade == 'C':
        return f"{_YELLOW}{grade}{_RESET}"
    elif grade == 'D':
        return f"{_YELLOW}{_BOLD}{grade}{_RESET}"
    else:
        return f"{_RED}{_BOLD}{grade}{_RESET}"


def _score_ansi(score: float) -> str:
    """Return an ANSI-colored score string."""
    if score >= 90:
        return f"{_GREEN}{score:5.1f}{_RESET}"
    elif score >= 75:
        return f"{_GREEN}{score:5.1f}{_RESET}"
    elif score >= 60:
        return f"{_YELLOW}{score:5.1f}{_RESET}"
    elif score >= 40:
        return f"{_YELLOW}{score:5.1f}{_RESET}"
    else:
        return f"{_RED}{score:5.1f}{_RESET}"


def print_console_summary(audits: List[AuditResult]) -> None:
    """Print a comprehensive network summary to the console.

    Displays:
      - Total sites audited
      - Average total score and grade distribution
      - Average per-category scores
      - Top 10 most common failures across the network
      - Any sites that encountered errors

    Args:
      - audits: List of scored AuditResult objects.
    """
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    if not audits:
        print(f"\n{_YELLOW}No audits to summarize.{_RESET}")
        return

    # Filter out audits that had fatal errors (no score calculated)
    scored = [a for a in audits if a.total_score > 0 or a.grade]
    errored = [a for a in audits if a.error]

    # ── Header ────────────────────────────────────────────────────────────
    print()
    print(f"{_BOLD}{_CYAN}{'═' * 70}{_RESET}")
    print(f"{_BOLD}{_CYAN}  📊  DIGITAL HEALTH MONITOR — NETWORK SUMMARY{_RESET}")
    print(f"{_BOLD}{_CYAN}{'═' * 70}{_RESET}")
    print()

    # ── Sites Audited ─────────────────────────────────────────────────────
    print(f"  {_BOLD}Sites Audited:{_RESET}  {len(audits)}")
    if errored:
        print(f"  {_RED}Sites with Errors:{_RESET}  {len(errored)}")
    print()

    # ── Average Total Score ───────────────────────────────────────────────
    if scored:
        avg_score = sum(a.total_score for a in scored) / len(scored)
        print(f"  {_BOLD}Average Score:{_RESET}  {_score_ansi(avg_score)}")
        print(f"  {_DIM}{_bar(avg_score, 100, 40)}{_RESET}")
        print()

    # ── Grade Distribution ────────────────────────────────────────────────
    grade_counts = Counter(a.grade for a in scored if a.grade)
    if grade_counts:
        print(f"  {_BOLD}Grade Distribution:{_RESET}")
        max_count = max(grade_counts.values()) if grade_counts else 1
        for grade_letter in ('A', 'B', 'C', 'D', 'F'):
            count = grade_counts.get(grade_letter, 0)
            bar = _bar(count, max_count, 25)
            pct = (count / len(scored) * 100) if scored else 0
            print(
                f"    {_grade_ansi(grade_letter)}  "
                f"{bar}  {count:3d}  ({pct:4.1f}%)"
            )
        print()

    # ── Per-Category Averages ─────────────────────────────────────────────
    category_keys = [
        ('website_seo', '🌐 Website SEO'),
        ('pagespeed', '⚡ PageSpeed'),
        ('gbp', '📍 Google Business'),
    ]

    print(f"  {_BOLD}Category Averages:{_RESET}")
    for key, label in category_keys:
        cat_scores = []
        for a in scored:
            cat = getattr(a, key, None)
            if cat is not None:
                cat_scores.append(cat.score)

        if cat_scores:
            avg = sum(cat_scores) / len(cat_scores)
            bar = _bar(avg, 100, 25)
            print(
                f"    {label:<25s}  {_score_ansi(avg)}  "
                f"{_DIM}{bar}{_RESET}  "
                f"({len(cat_scores)} sites)"
            )
        else:
            print(
                f"    {label:<25s}  {_DIM}  N/A  (skipped){_RESET}"
            )
    print()

    # ── Top 10 Most Common Failures ───────────────────────────────────────
    failure_counter: Counter = Counter()
    for a in scored:
        for check in a.all_checks:
            if check.status in ('fail', 'warn'):
                failure_counter[check.name] += 1

    if failure_counter:
        top_failures = failure_counter.most_common(10)
        max_fail_count = top_failures[0][1] if top_failures else 1

        print(f"  {_BOLD}Top 10 Most Common Failures:{_RESET}")
        for rank, (check_name, count) in enumerate(top_failures, 1):
            bar = _bar(count, max_fail_count, 20)
            pct = (count / len(scored) * 100) if scored else 0
            print(
                f"    {_DIM}{rank:2d}.{_RESET} {check_name:<30s}  "
                f"{_RED}{count:3d}{_RESET}  {bar}  ({pct:.0f}%)"
            )
        print()

    # ── Sites with Errors ─────────────────────────────────────────────────
    if errored:
        print(f"  {_BOLD}{_RED}⚠ Sites with Errors:{_RESET}")
        for a in errored:
            print(
                f"    {_RED}•{_RESET} {a.name or a.domain:<30s}  "
                f"{_DIM}{a.error}{_RESET}"
            )
        print()

    # ── Footer ────────────────────────────────────────────────────────────
    print(f"{_BOLD}{_CYAN}{'═' * 70}{_RESET}")
    print()
