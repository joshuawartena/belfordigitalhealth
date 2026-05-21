"""
pdf_generator.py
═══════════════════════════════════════════════════════════════════════════════
Digital Health Monitor — PDF Report Generator (fpdf2)
═══════════════════════════════════════════════════════════════════════════════

Generates a clean, professional multi-page PDF audit report.

Functions:
    generate_pdf_report  – Full PDF report with cover, recommendations, details
"""

from __future__ import annotations

import logging
import os
from typing import List, Tuple

from fpdf import FPDF

from checkers import AuditResult, CategoryResult, CheckResult

logger = logging.getLogger('audit')

# ─── Colour helpers ───────────────────────────────────────────────────────────

PRIORITY_COLORS = {
    'critical': '#dc2626',
    'high':     '#f97316',
    'medium':   '#f59e0b',
    'low':      '#3b82f6',
}

STATUS_BG = {
    'pass':  '#dcfce7',
    'warn':  '#fef9c3',
    'fail':  '#fee2e2',
    'error': '#fee2e2',
    'skip':  '#f1f5f9',
}

STATUS_LABEL = {
    'pass':  'PASS',
    'warn':  'WARN',
    'fail':  'FAIL',
    'error': 'ERR',
    'skip':  'SKIP',
}


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert a hex colour string (e.g. '#3b82f6') to an (R, G, B) tuple."""
    h = hex_color.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _score_color_hex(score: float) -> str:
    """Return a hex colour based on score thresholds."""
    if score >= 75:
        return '#22c55e'
    if score >= 60:
        return '#f59e0b'
    if score >= 40:
        return '#f97316'
    return '#ef4444'


def _safe_text(text: str) -> str:
    """Strip characters that fpdf2 can't encode in latin-1."""
    return text.encode('latin-1', errors='replace').decode('latin-1')


# ═══════════════════════════════════════════════════════════════════════════════
#  Custom FPDF subclass for consistent footer
# ═══════════════════════════════════════════════════════════════════════════════

class AuditPDF(FPDF):
    """FPDF subclass that adds a branded footer on every page."""

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(148, 163, 184)  # #94a3b8
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')
        self.set_y(-10)
        self.set_font('Helvetica', '', 7)
        self.cell(0, 10, 'BFG WMS  -  Digital Health Monitor', align='C')


# ═══════════════════════════════════════════════════════════════════════════════
#  Drawing helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_header_bar(pdf: AuditPDF, text: str):
    """Draw a dark header bar across the page width."""
    r, g, b = _hex_to_rgb('#1e293b')
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 14, f'  {_safe_text(text)}', fill=True, new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)


def _draw_score_circle(pdf: AuditPDF, x: float, y: float, radius: float,
                        score: float, grade: str, color_hex: str):
    """Draw a filled circle with the grade letter and score inside."""
    r, g, b = _hex_to_rgb(color_hex)
    pdf.set_fill_color(r, g, b)
    pdf.set_draw_color(r, g, b)
    pdf.ellipse(x - radius, y - radius, radius * 2, radius * 2, style='F')

    # Grade letter
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', int(radius * 1.3))
    pdf.set_xy(x - radius, y - radius * 0.55)
    pdf.cell(radius * 2, radius * 0.8, grade, align='C')

    # Score number
    pdf.set_font('Helvetica', '', int(radius * 0.55))
    pdf.set_xy(x - radius, y + radius * 0.15)
    pdf.cell(radius * 2, radius * 0.5, str(round(score, 1)), align='C')

    pdf.set_text_color(0, 0, 0)


def _draw_mini_bar(pdf: AuditPDF, x: float, y: float, width: float,
                   height: float, pct: float, color_hex: str):
    """Draw a small progress bar."""
    # Track
    pdf.set_fill_color(226, 232, 240)  # #e2e8f0
    pdf.rect(x, y, width, height, style='F')
    # Fill
    r, g, b = _hex_to_rgb(color_hex)
    pdf.set_fill_color(r, g, b)
    fill_w = max(width * (pct / 100.0), 1)
    pdf.rect(x, y, fill_w, height, style='F')


def _draw_category_card(pdf: AuditPDF, x: float, y: float, cat: CategoryResult):
    """Draw a compact category score card."""
    card_w = 55
    color = _score_color_hex(cat.score)

    pdf.set_xy(x, y)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(100, 116, 139)  # #64748b
    pdf.cell(card_w, 5, _safe_text(cat.name), align='C')

    pdf.set_xy(x, y + 6)
    r, g, b = _hex_to_rgb(color)
    pdf.set_text_color(r, g, b)
    pdf.set_font('Helvetica', 'B', 20)
    pdf.cell(card_w, 10, str(cat.score), align='C')

    _draw_mini_bar(pdf, x + 5, y + 18, card_w - 10, 3, cat.score, color)

    pdf.set_text_color(0, 0, 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main generator
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pdf_report(audit: AuditResult, output_path: str) -> str:
    """
    Generate a multi-page PDF audit report.

    Pages:
        1. Cover / Summary — title, score circle, category cards
        2. Top Recommendations — priority action items
        3+. Detailed Findings — one section per category with check tables

    Args:
        audit: Completed AuditResult with scored categories.
        output_path: Filesystem path for the output .pdf file.

    Returns:
        The *output_path* that was written.
    """
    try:
        pdf = AuditPDF(orientation='P', unit='mm', format='A4')
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.set_margins(15, 15, 15)

        # ══════════════════════════════════════════════════════════════════
        #  PAGE 1 — Cover / Summary
        # ══════════════════════════════════════════════════════════════════
        pdf.add_page()

        # Dark header banner
        r, g, b = _hex_to_rgb('#1e293b')
        pdf.set_fill_color(r, g, b)
        pdf.rect(0, 0, 210, 55, style='F')

        pdf.set_xy(15, 12)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 22)
        pdf.cell(0, 10, 'Digital Health Audit Report')

        pdf.set_xy(15, 24)
        pdf.set_font('Helvetica', '', 14)
        pdf.cell(0, 8, _safe_text(audit.name))

        pdf.set_xy(15, 34)
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(0, 6, _safe_text(audit.domain))

        pdf.set_xy(15, 42)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 6, f'Audited: {_safe_text(audit.audited_at)}')

        pdf.set_text_color(0, 0, 0)

        # Score circle (right side of header)
        grade_color = audit.grade_color or '#3b82f6'
        _draw_score_circle(pdf, 170, 30, 18, audit.total_score, audit.grade, grade_color)

        # Grade label below header
        pdf.set_xy(15, 60)
        pdf.set_font('Helvetica', '', 12)
        pdf.set_text_color(71, 85, 105)  # #475569
        pdf.cell(0, 8, _safe_text(audit.grade_label or ''), align='C')
        pdf.ln(14)

        # Separator line
        pdf.set_draw_color(226, 232, 240)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(8)

        # Summary stats
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 8, 'Audit Summary')
        pdf.ln(10)

        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(71, 85, 105)
        stats = [
            ('Total Checks', str(len(audit.all_checks))),
            ('Passed', str(audit.total_pass)),
            ('Warnings', str(audit.total_warn)),
            ('Failed', str(audit.total_fail)),
        ]
        for label, val in stats:
            pdf.cell(45, 7, f'{label}:', align='L')
            pdf.set_font('Helvetica', 'B', 10)
            pdf.cell(20, 7, val)
            pdf.set_font('Helvetica', '', 10)
            pdf.ln(7)

        pdf.ln(6)

        # Separator
        pdf.set_draw_color(226, 232, 240)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(8)

        # Category score cards
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 8, 'Category Scores')
        pdf.ln(10)

        categories = audit.categories
        card_y = pdf.get_y()
        card_start_x = 30
        for i, cat in enumerate(categories):
            _draw_category_card(pdf, card_start_x + i * 60, card_y, cat)

        pdf.ln(30)

        # Location info if available
        if audit.city or audit.address:
            pdf.set_draw_color(226, 232, 240)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(8)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(30, 41, 59)
            pdf.cell(0, 8, 'Location Details')
            pdf.ln(10)
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(71, 85, 105)
            if audit.address:
                pdf.cell(0, 7, _safe_text(f'Address: {audit.address}'))
                pdf.ln(7)
            if audit.city:
                pdf.cell(0, 7, _safe_text(f'City: {audit.city}, {audit.state} {audit.zip_code}'))
                pdf.ln(7)
            if audit.phone:
                pdf.cell(0, 7, _safe_text(f'Phone: {audit.phone}'))
                pdf.ln(7)

        # ══════════════════════════════════════════════════════════════════
        #  PAGE 2 — Top Recommendations
        # ══════════════════════════════════════════════════════════════════
        pdf.add_page()
        _draw_header_bar(pdf, 'Priority Action Items')

        recommendations = audit.top_recommendations(10)

        if not recommendations:
            pdf.set_font('Helvetica', 'I', 11)
            pdf.set_text_color(148, 163, 184)
            pdf.cell(0, 10, 'No actionable recommendations at this time.', align='C')
        else:
            for idx, rec in enumerate(recommendations, start=1):
                y_start = pdf.get_y()

                # Check if we need a new page
                if y_start > 260:
                    pdf.add_page()
                    _draw_header_bar(pdf, 'Priority Action Items (continued)')
                    y_start = pdf.get_y()

                # Number
                pdf.set_font('Helvetica', 'B', 11)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(10, 7, f'{idx}.')

                # Priority badge
                pri_color = PRIORITY_COLORS.get(rec.priority, '#64748b')
                pr, pg, pb = _hex_to_rgb(pri_color)
                pdf.set_fill_color(pr, pg, pb)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font('Helvetica', 'B', 7)
                badge_text = _safe_text(rec.priority.upper())
                badge_w = pdf.get_string_width(badge_text) + 6
                pdf.cell(badge_w, 7, f' {badge_text} ', fill=True)
                pdf.cell(3, 7, '')  # spacer

                # Check name
                pdf.set_text_color(30, 41, 59)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.cell(0, 7, _safe_text(rec.name))
                pdf.ln(8)

                # Recommendation text
                pdf.set_x(25)
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(71, 85, 105)
                pdf.multi_cell(160, 5, _safe_text(rec.recommendation))
                pdf.ln(4)

                # Separator
                pdf.set_draw_color(241, 245, 249)
                pdf.line(25, pdf.get_y(), 195, pdf.get_y())
                pdf.ln(4)

        # ══════════════════════════════════════════════════════════════════
        #  PAGES 3+ — Detailed Findings
        # ══════════════════════════════════════════════════════════════════
        for cat in categories:
            pdf.add_page()

            # Category header
            cat_color = _score_color_hex(cat.score)
            _draw_header_bar(pdf, f'{cat.name}  -  Score: {cat.score}/100')

            # Summary line
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(0, 6,
                     f'Passed: {cat.pass_count}  |  Warnings: {cat.warn_count}  |  '
                     f'Failed: {cat.fail_count}  |  '
                     f'Points: {cat.earned}/{cat.possible}')
            pdf.ln(10)

            # Table header
            col_widths = [18, 48, 50, 46, 18]  # Status, Check, Details, Value, Points
            headers = ['Status', 'Check', 'Details', 'Value', 'Pts']

            pdf.set_font('Helvetica', 'B', 8)
            pdf.set_fill_color(248, 250, 252)  # #f8fafc
            pdf.set_text_color(100, 116, 139)
            pdf.set_draw_color(226, 232, 240)

            for i, h in enumerate(headers):
                pdf.cell(col_widths[i], 8, h, border=1, fill=True, align='C')
            pdf.ln()

            # Table rows
            pdf.set_font('Helvetica', '', 8)
            for check in cat.checks:
                # Check if we need a new page
                if pdf.get_y() > 265:
                    pdf.add_page()
                    # Re-draw table header
                    pdf.set_font('Helvetica', 'B', 8)
                    pdf.set_fill_color(248, 250, 252)
                    pdf.set_text_color(100, 116, 139)
                    for i, h in enumerate(headers):
                        pdf.cell(col_widths[i], 8, h, border=1, fill=True, align='C')
                    pdf.ln()
                    pdf.set_font('Helvetica', '', 8)

                # Row background colour
                bg_hex = STATUS_BG.get(check.status, '#ffffff')
                br, bg, bb = _hex_to_rgb(bg_hex)
                pdf.set_fill_color(br, bg, bb)
                pdf.set_text_color(30, 41, 59)
                pdf.set_draw_color(226, 232, 240)

                row_h = 7
                status_text = STATUS_LABEL.get(check.status, check.status.upper())

                # Status cell with colour
                sr, sg, sb = _hex_to_rgb(check.status_color)
                pdf.set_text_color(sr, sg, sb)
                pdf.cell(col_widths[0], row_h, status_text, border=1, fill=True, align='C')

                pdf.set_text_color(30, 41, 59)

                # Check name (truncate if needed)
                name_text = _safe_text(check.name)[:30]
                pdf.cell(col_widths[1], row_h, name_text, border=1, fill=True)

                # Detail (truncate)
                detail_text = _safe_text(check.detail)[:32] if check.detail else '-'
                pdf.cell(col_widths[2], row_h, detail_text, border=1, fill=True)

                # Value (truncate)
                value_text = _safe_text(check.value)[:28] if check.value else '-'
                pdf.cell(col_widths[3], row_h, value_text, border=1, fill=True)

                # Points
                pts_text = f'{check.points_earned}/{check.points_possible}'
                pdf.cell(col_widths[4], row_h, pts_text, border=1, fill=True, align='C')

                pdf.ln()

        # ── Save ──────────────────────────────────────────────────────────
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        pdf.output(output_path)
        logger.info('PDF report written → %s', output_path)
        return output_path

    except Exception:
        logger.exception('Failed to generate PDF report')
        raise
