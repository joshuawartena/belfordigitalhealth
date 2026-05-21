#!/usr/bin/env python3
"""
main.py
═══════════════════════════════════════════════════════════════════════════════
Digital Health Monitor — CLI Entry Point
═══════════════════════════════════════════════════════════════════════════════

Orchestrates the full audit pipeline:
  1. Parse CLI arguments (single-site or batch CSV)
  2. Run the enabled checkers (Website SEO, PageSpeed, GBP)
  3. Compute weighted scores and grades
  4. Generate reports (HTML, JSON, PDF)
  5. Print a console summary

Usage:
  # Single site
  python main.py --url https://forkschemdry.com --business "Forks Chem-Dry" --city "Grand Forks"

  # Batch mode
  python main.py --batch franchise_list.csv --output ./results --workers 3

  # Skip optional checkers
  python main.py --url https://example.com --no-gbp --no-pagespeed
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

import config
from checkers import AuditResult
from checkers.website_seo import WebsiteSEOChecker
from checkers.pagespeed import PageSpeedChecker
from checkers.gbp import GBPChecker
from scoring import calculate_scores, print_console_summary

# Lazy imports — these modules may not exist yet
# from reporter import generate_html_report, generate_json_report, generate_batch_csv, generate_batch_excel
# from pdf_generator import generate_pdf_report

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain / URL Normalization
# ─────────────────────────────────────────────────────────────────────────────

def normalize_domain(raw: str) -> str:
    """Strip a raw URL or domain string down to a clean hostname.

    Examples:
        >>> normalize_domain('https://www.forkschemdry.com/')
        'forkschemdry.com'
        >>> normalize_domain('http://example.com/page?q=1')
        'example.com'
        >>> normalize_domain('example.com')
        'example.com'
    """
    domain = raw.strip()
    # Strip protocol
    domain = re.sub(r'^https?://', '', domain)
    # Strip www. prefix
    domain = re.sub(r'^www\.', '', domain)
    # Strip path, query, fragment
    domain = domain.split('/')[0].split('?')[0].split('#')[0]
    # Strip trailing dots / whitespace
    domain = domain.strip('. ')
    return domain.lower()


def domain_to_url(domain: str) -> str:
    """Convert a clean domain to a canonical HTTPS URL."""
    return f"https://{domain}"


# ─────────────────────────────────────────────────────────────────────────────
# Single-Site Audit
# ─────────────────────────────────────────────────────────────────────────────

def run_single_audit(
    audit: AuditResult,
    *,
    skip_gbp: bool = False,
    skip_pagespeed: bool = False,
    delay: float = 0.5,
) -> AuditResult:
    """Run all enabled checkers on a single site and score the results.

    Args:
        audit:          Pre-populated AuditResult with identity fields set.
        skip_gbp:       If True, skip Google Business Profile checks.
        skip_pagespeed: If True, skip PageSpeed Insights checks.
        delay:          Seconds to wait between API calls.

    Returns:
        The scored AuditResult with all category results and grades populated.
    """
    audit.audited_at = datetime.now(timezone.utc).isoformat()
    domain = audit.domain

    if not domain:
        audit.error = "No domain provided"
        logger.error("No domain provided for audit: %s", audit.name)
        return audit

    logger.info("━━━ Starting audit: %s (%s) ━━━", audit.name or domain, domain)

    # ── 1. Website SEO ────────────────────────────────────────────────────
    try:
        logger.info("Running Website SEO checks for %s …", domain)
        checker = WebsiteSEOChecker(domain)
        audit.website_seo = checker.run(audit)
        logger.info(
            "Website SEO: %.1f / %.1f (%.1f%%)",
            audit.website_seo.earned,
            audit.website_seo.possible,
            audit.website_seo.score,
        )
    except Exception as exc:
        logger.error("Website SEO checker failed for %s: %s", domain, exc)
        audit.error = f"SEO checker error: {exc}"

    if delay > 0:
        time.sleep(delay)

    # ── 2. PageSpeed Insights ─────────────────────────────────────────────
    if not skip_pagespeed:
        try:
            logger.info("Running PageSpeed checks for %s …", domain)
            checker = PageSpeedChecker(domain)
            audit.pagespeed = checker.run(audit)
            logger.info(
                "PageSpeed: %.1f / %.1f (%.1f%%)",
                audit.pagespeed.earned,
                audit.pagespeed.possible,
                audit.pagespeed.score,
            )
        except Exception as exc:
            logger.error("PageSpeed checker failed for %s: %s", domain, exc)
            if audit.error:
                audit.error += f"; PageSpeed error: {exc}"
            else:
                audit.error = f"PageSpeed error: {exc}"

        if delay > 0:
            time.sleep(delay)
    else:
        logger.info("Skipping PageSpeed checks (--no-pagespeed)")

    # ── 3. Google Business Profile ────────────────────────────────────────
    if not skip_gbp:
        try:
            logger.info("Running GBP checks for %s …", domain)
            checker = GBPChecker()
            audit.gbp = checker.run(audit)
            logger.info(
                "GBP: %.1f / %.1f (%.1f%%)",
                audit.gbp.earned,
                audit.gbp.possible,
                audit.gbp.score,
            )
        except Exception as exc:
            logger.error("GBP checker failed for %s: %s", domain, exc)
            if audit.error:
                audit.error += f"; GBP error: {exc}"
            else:
                audit.error = f"GBP error: {exc}"
    else:
        logger.info("Skipping GBP checks (--no-gbp)")

    # ── 4. Score & grade ──────────────────────────────────────────────────
    calculate_scores(audit)

    return audit


# ─────────────────────────────────────────────────────────────────────────────
# Report Generation Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_output_dir(path: str) -> Path:
    """Create the output directory if it doesn't exist."""
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _audit_to_dict(audit: AuditResult) -> dict:
    """Serialize an AuditResult to a JSON-compatible dict."""
    data = {
        'name': audit.name,
        'domain': audit.domain,
        'url': audit.url,
        'city': audit.city,
        'state': audit.state,
        'phone': audit.phone,
        'address': audit.address,
        'zip_code': audit.zip_code,
        'owner': audit.owner,
        'place_id': audit.place_id,
        'gbp_url': audit.gbp_url,
        'business_name': audit.business_name,
        'audited_at': audit.audited_at,
        'http_status': audit.http_status,
        'error': audit.error,
        'total_score': audit.total_score,
        'grade': audit.grade,
        'grade_label': audit.grade_label,
        'grade_color': audit.grade_color,
    }

    for key in ('website_seo', 'pagespeed', 'gbp'):
        cat = getattr(audit, key, None)
        if cat is not None:
            data[key] = {
                'name': cat.name,
                'score': cat.score,
                'earned': cat.earned,
                'possible': cat.possible,
                'pass_count': cat.pass_count,
                'fail_count': cat.fail_count,
                'warn_count': cat.warn_count,
                'checks': [
                    {
                        'name': c.name,
                        'status': c.status,
                        'priority': c.priority,
                        'points_earned': c.points_earned,
                        'points_possible': c.points_possible,
                        'value': c.value,
                        'detail': c.detail,
                        'recommendation': c.recommendation,
                    }
                    for c in cat.checks
                ],
            }
        else:
            data[key] = None

    return data


def _sanitize_surrogates(obj):
    """Recursively replace surrogate characters in strings so json.dump doesn't crash."""
    if isinstance(obj, str):
        return obj.encode('utf-8', errors='replace').decode('utf-8')
    if isinstance(obj, dict):
        return {k: _sanitize_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_surrogates(item) for item in obj]
    return obj
    

def save_json_report(audit: AuditResult, output_dir: Path) -> Path:
    """Save a single audit result as a JSON file.

    Args:
        audit:      The scored AuditResult to serialize.
        output_dir: Directory to write the JSON file into.

    Returns:
        Path to the saved JSON file.
    """
    filename = f"{audit.domain.replace('.', '_')}_report.json"
    filepath = output_dir / filename
    data = _sanitize_surrogates(_audit_to_dict(audit))   # ← add this line
    with open(filepath, 'w', encoding='utf-8', errors='replace') as f:   # ← add errors='replace'
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("JSON report saved: %s", filepath)
    return filepath


def generate_reports(
    audit: AuditResult,
    output_dir: Path,
    *,
    generate_pdf: bool = False,
    generate_html: bool = True,
) -> None:
    """Generate all requested reports for a single audit.

    Args:
        audit:         The scored AuditResult.
        output_dir:    Directory to write reports into.
        generate_pdf:  Whether to generate a PDF report.
        generate_html: Whether to generate an HTML report.
    """
    # Always save JSON
    save_json_report(audit, output_dir)

    # HTML report
    if generate_html:
        try:
            from reporter import generate_html_report
            html_path = output_dir / f"{audit.domain.replace('.', '_')}_report.html"
            generate_html_report(audit, str(html_path))
            logger.info("HTML report generated for %s: %s", audit.domain, html_path)
        except ImportError:
            logger.warning(
                "reporter module not found — skipping HTML report. "
                "Create reporter.py to enable HTML reports."
            )
        except Exception as exc:
            logger.error("HTML report generation failed: %s", exc)

    # PDF report
    if generate_pdf:
        try:
            from pdf_generator import generate_pdf_report
            pdf_path = output_dir / f"{audit.domain.replace('.', '_')}_report.pdf"
            generate_pdf_report(audit, str(pdf_path))
            logger.info("PDF report generated for %s: %s", audit.domain, pdf_path)
        except ImportError:
            logger.warning(
                "pdf_generator module not found — skipping PDF report. "
                "Create pdf_generator.py to enable PDF reports."
            )
        except Exception as exc:
            logger.error("PDF report generation failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Batch CSV Loading
# ─────────────────────────────────────────────────────────────────────────────

def load_batch_csv(csv_path: str) -> List[AuditResult]:
    """Load a batch CSV file and return a list of AuditResult objects.

    Required columns: ``name``, ``domain``
    Optional columns: ``city``, ``state``, ``phone``, ``address``, ``zip``,
                      ``owner``, ``place_id``, ``gbp_url``, ``business_name``

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of AuditResult objects with identity fields populated.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError:        If required columns are missing.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Batch CSV not found: {csv_path}")

    audits: List[AuditResult] = []

    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]

        # Validate required columns
        if 'name' not in headers or 'domain' not in headers:
            raise ValueError(
                f"CSV must have 'name' and 'domain' columns. "
                f"Found: {headers}"
            )

        for row_num, row in enumerate(reader, start=2):
            # Normalize column names
            row = {k.strip().lower(): (v or '').strip() for k, v in row.items()}

            domain = normalize_domain(row.get('domain', ''))
            if not domain:
                logger.warning("Row %d: empty domain, skipping", row_num)
                continue

            audit = AuditResult(
                name=row.get('name', ''),
                domain=domain,
                url=domain_to_url(domain),
                city=row.get('city', ''),
                state=row.get('state', ''),
                phone=row.get('phone', ''),
                address=row.get('address', ''),
                zip_code=row.get('zip', ''),
                owner=row.get('owner', ''),
                place_id=row.get('place_id', ''),
                gbp_url=row.get('gbp_url', ''),
                business_name=row.get('business_name', row.get('name', '')),
                expected_category=row.get('expected_category', ''),
            )
            audits.append(audit)

    logger.info("Loaded %d sites from %s", len(audits), csv_path)
    return audits


# ─────────────────────────────────────────────────────────────────────────────
# Batch Execution
# ─────────────────────────────────────────────────────────────────────────────

def run_batch(
    audits: List[AuditResult],
    *,
    skip_gbp: bool = False,
    skip_pagespeed: bool = False,
    workers: int = 3,
    delay: float = 0.5,
    output_dir: Path = Path('./results'),
    generate_pdf: bool = False,
    generate_html: bool = True,
) -> List[AuditResult]:
    """Run audits on a batch of sites using a thread pool.

    Args:
        audits:         List of AuditResult objects with identity fields set.
        skip_gbp:       Skip GBP checks for all sites.
        skip_pagespeed: Skip PageSpeed checks for all sites.
        workers:        Number of parallel worker threads.
        delay:          Seconds between API calls per worker.
        output_dir:     Directory for generated reports.
        generate_pdf:   Whether to generate PDF reports.
        generate_html:  Whether to generate HTML reports.

    Returns:
        List of completed (scored) AuditResult objects.
    """
    completed: List[AuditResult] = []

    logger.info(
        "Starting batch audit: %d sites, %d workers",
        len(audits), workers,
    )

    def _audit_worker(audit: AuditResult) -> AuditResult:
        """Run a single audit and generate reports."""
        result = run_single_audit(
            audit,
            skip_gbp=skip_gbp,
            skip_pagespeed=skip_pagespeed,
            delay=delay,
        )
        generate_reports(
            result, output_dir,
            generate_pdf=generate_pdf,
            generate_html=generate_html,
        )
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_audit_worker, audit): audit
            for audit in audits
        }

        with tqdm(total=len(futures), desc="Auditing sites", unit="site") as pbar:
            for future in as_completed(futures):
                audit = futures[future]
                try:
                    result = future.result()
                    completed.append(result)
                    pbar.set_postfix_str(
                        f"{result.domain}: {result.grade} ({result.total_score})",
                        refresh=True,
                    )
                except Exception as exc:
                    logger.error(
                        "Audit failed for %s: %s",
                        audit.domain, exc,
                    )
                    audit.error = str(exc)
                    completed.append(audit)
                pbar.update(1)

    logger.info("Batch audit complete: %d sites processed", len(completed))
    return completed


def generate_batch_reports(
    audits: List[AuditResult],
    output_dir: Path,
) -> None:
    """Generate aggregate batch reports (CSV summary and Excel workbook).

    Args:
        audits:     List of completed AuditResult objects.
        output_dir: Directory for generated reports.
    """
    # CSV summary
    try:
        from reporter import generate_batch_csv
        csv_path = output_dir / "batch_summary.csv"
        generate_batch_csv(audits, str(csv_path))
        logger.info("Batch CSV summary generated: %s", csv_path)
    except ImportError:
        logger.warning(
            "reporter module not found — skipping batch CSV. "
            "Create reporter.py to enable."
        )
    except Exception as exc:
        logger.error("Batch CSV generation failed: %s", exc)

    # Excel workbook
    try:
        from reporter import generate_batch_excel
        excel_path = output_dir / "batch_summary.xlsx"
        generate_batch_excel(audits, str(excel_path))
        logger.info("Batch Excel workbook generated: %s", excel_path)
    except ImportError:
        logger.warning(
            "reporter module not found — skipping Excel. "
            "Create reporter.py to enable."
        )
    except Exception as exc:
        logger.error("Batch Excel generation failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# CLI Argument Parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog='digital-health-monitor',
        description=(
            'Digital Health Monitor — Audit franchise websites for SEO, '
            'PageSpeed, and Google Business Profile health.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single site audit
  python main.py --url https://forkschemdry.com --business "Forks Chem-Dry" --city "Grand Forks"

  # Single site with Place ID
  python main.py --url https://forkschemdry.com --place-id ChIJ...

  # Batch audit from CSV
  python main.py --batch franchise_list.csv --output ./results --workers 5

  # Skip optional checkers
  python main.py --url https://example.com --no-gbp --no-pagespeed

  # Generate PDF reports
  python main.py --batch franchise_list.csv --pdf
""",
    )

    # ── Input sources ─────────────────────────────────────────────────────
    input_group = parser.add_argument_group('Input')
    input_group.add_argument(
        '--url',
        type=str,
        help='Single URL to audit (e.g., https://forkschemdry.com)',
    )
    input_group.add_argument(
        '--business',
        type=str,
        default='',
        help='Business name for GBP text search',
    )
    input_group.add_argument(
        '--city',
        type=str,
        default='',
        help='City for GBP text search',
    )
    input_group.add_argument(
        '--place-id',
        type=str,
        default='',
        help='Direct Google Place ID (skips text search)',
    )
    input_group.add_argument(
        '--gbp-url',
        type=str,
        default='',
        help='GBP share link (e.g., https://share.google/...)',
    )
    input_group.add_argument(
        '--batch',
        type=str,
        help='Path to CSV file for batch mode',
    )

    # ── Output options ────────────────────────────────────────────────────
    output_group = parser.add_argument_group('Output')
    output_group.add_argument(
        '--output',
        type=str,
        default='./results',
        help='Output directory for reports (default: ./results)',
    )
    output_group.add_argument(
        '--pdf',
        action='store_true',
        default=False,
        help='Generate PDF reports (requires pdf_generator module)',
    )
    output_group.add_argument(
        '--no-html',
        action='store_false',
        dest='html',
        default=True,
        help='Disable HTML report generation',
    )

    # ── Checker toggles ───────────────────────────────────────────────────
    toggle_group = parser.add_argument_group('Checker Toggles')
    toggle_group.add_argument(
        '--no-gbp',
        action='store_true',
        default=False,
        help='Skip Google Business Profile checks',
    )
    toggle_group.add_argument(
        '--no-pagespeed',
        action='store_true',
        default=False,
        help='Skip PageSpeed Insights checks',
    )

    # ── Performance ───────────────────────────────────────────────────────
    perf_group = parser.add_argument_group('Performance')
    perf_group.add_argument(
        '--workers',
        type=int,
        default=3,
        help='Parallel workers for batch mode (default: 3, max: 10)',
    )
    perf_group.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Seconds between API requests per worker (default: 0.5)',
    )

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Main entry point for the Digital Health Monitor CLI."""
    # Ensure stdout/stderr support unicode on Windows without crashing
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args()

    # ── Logging setup ─────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # ── Validate inputs ──────────────────────────────────────────────────
    if not args.url and not args.batch:
        parser.error("You must provide either --url or --batch")

    # Clamp workers
    if args.workers < 1:
        args.workers = 1
    elif args.workers > 10:
        logger.warning("Clamping --workers to maximum of 10")
        args.workers = 10

    # ── Prepare output directory ──────────────────────────────────────────
    output_dir = _ensure_output_dir(args.output)
    logger.info("Output directory: %s", output_dir.resolve())

    # ── Mode: Batch ───────────────────────────────────────────────────────
    if args.batch:
        logger.info("═══ BATCH MODE ═══")
        try:
            audits = load_batch_csv(args.batch)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Failed to load batch CSV: %s", exc)
            sys.exit(1)

        if not audits:
            logger.error("No valid sites found in %s", args.batch)
            sys.exit(1)

        completed = run_batch(
            audits,
            skip_gbp=args.no_gbp,
            skip_pagespeed=args.no_pagespeed,
            workers=args.workers,
            delay=args.delay,
            output_dir=output_dir,
            generate_pdf=args.pdf,
            generate_html=args.html,
        )

        # Generate aggregate reports
        generate_batch_reports(completed, output_dir)

        # Print network summary
        print_console_summary(completed)

        logger.info("Batch audit complete. Reports saved to: %s", output_dir.resolve())

    # ── Mode: Single Site ─────────────────────────────────────────────────
    else:
        logger.info("═══ SINGLE SITE MODE ═══")
        domain = normalize_domain(args.url)
        url = domain_to_url(domain)

        # Build the AuditResult with all provided identity fields
        audit = AuditResult(
            name=args.business or domain,
            domain=domain,
            url=url,
            city=args.city,
            place_id=args.place_id,
            gbp_url=args.gbp_url,
            business_name=args.business,
        )

        # Run the audit
        audit = run_single_audit(
            audit,
            skip_gbp=args.no_gbp,
            skip_pagespeed=args.no_pagespeed,
            delay=args.delay,
        )

        # Generate reports
        generate_reports(
            audit, output_dir,
            generate_pdf=args.pdf,
            generate_html=args.html,
        )

        # Print single-site summary
        print_console_summary([audit])

        logger.info("Audit complete. Reports saved to: %s", output_dir.resolve())


if __name__ == '__main__':
    main()
