"""Exportadores de entregables V3: PDF (reportlab), PPTX (python-pptx), XLSX (openpyxl) y ZIP."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches, Pt
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def export_pdf(report_dir: Path, manifest: Dict[str, Any], full_markdown: str) -> Path:
    """Genera el entregable ejecutivo PDF."""
    out_path = report_dir / f"{manifest.get('project_slug', 'proyecto')}_{manifest.get('report_id', 'report')}.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(str(manifest.get("title") or "Estudio de Mercado Prospéctica V3"), styles["Title"]),
        Spacer(1, 12),
    ]
    for raw_line in (full_markdown or "").splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("## "):
            story.append(Paragraph(safe[3:], styles["Heading2"]))
        elif line.startswith("# "):
            story.append(Paragraph(safe[2:], styles["Heading1"]))
        else:
            story.append(Paragraph(safe, styles["BodyText"]))
    doc.build(story)
    return out_path


def export_pptx(report_dir: Path, manifest: Dict[str, Any], chapters: List[Dict[str, Any]]) -> Path:
    """Genera presentación ejecutiva PPTX."""
    out_path = report_dir / f"{manifest.get('project_slug', 'proyecto')}_{manifest.get('report_id', 'report')}.pptx"
    prs = Presentation()
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.shapes.title.text = str(manifest.get("project_name") or "Prospéctica V3")
    title_slide.placeholders[1].text = str(manifest.get("title") or "Estudio de Inteligencia de Mercados")

    for ch in chapters[:12]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = str(ch.get("title") or "Capítulo")
        body = slide.placeholders[1].text_frame
        body.clear()
        lines = [ln.strip() for ln in str(ch.get("content_markdown") or "").splitlines() if ln.strip()][:6]
        for idx, ln in enumerate(lines):
            p = body.paragraphs[0] if idx == 0 else body.add_paragraph()
            p.text = ln[:180]
            p.font.size = Pt(13)

    prs.save(str(out_path))
    return out_path


def export_xlsx(report_dir: Path, manifest: Dict[str, Any], bundle: Dict[str, Any]) -> Path:
    """Genera libro Excel XLSX con datos cuantitativos, pricing, unidad económica y flujo M1–M24."""
    out_path = report_dir / f"{manifest.get('project_slug', 'proyecto')}_{manifest.get('report_id', 'report')}.xlsx"
    wb = Workbook()

    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Proyecto", manifest.get("project_name", "")])
    ws.append(["Report ID", manifest.get("report_id", "")])
    ws.append(["Simulation ID", manifest.get("simulation_id", "")])
    ws.append(["Version", manifest.get("version", "v3_18ch")])
    ws.append(["SHA-256", manifest.get("analytics_sha256", "")])

    # TAM/SAM/SOM
    ws_tam = wb.create_sheet("TAM_SAM_SOM")
    ws_tam.append(["Nivel", "Min COP", "Probable COP", "Max COP"])
    td = ((bundle.get("secondary_research") or {}).get("tam_sam_som") or {}).get("top_down") or {}
    for lvl in ("tam", "sam", "som"):
        d = td.get(lvl) or {}
        ws_tam.append([lvl.upper(), d.get("min", 0), d.get("probable", 0), d.get("max", 0)])

    # Flujo mensual
    ws_flow = wb.create_sheet("Flujo_M1_M24")
    ws_flow.append(["Mes", "Casos", "Ingresos COP", "Costos Variables COP", "OPEX COP", "Flujo Neto COP", "Caja Acumulada COP"])
    m_rows = ((bundle.get("funnel_finance") or {}).get("projection_24m") or {}).get("monthly_m1_m24") or []
    for r in m_rows:
        ws_flow.append([
            r.get("month"),
            r.get("cases"),
            r.get("revenue"),
            r.get("variable_costs"),
            r.get("opex"),
            r.get("net_cashflow"),
            r.get("cumulative_cash"),
        ])

    # Monte Carlo
    ws_mc = wb.create_sheet("Monte_Carlo")
    mc = (bundle.get("funnel_finance") or {}).get("monte_carlo") or {}
    rev = mc.get("revenue_24m_percentiles") or {}
    cash = mc.get("ending_cash_percentiles") or {}
    ws_mc.append(["Metrica", "P10", "P50", "P90"])
    ws_mc.append(["Ingresos 24m", rev.get("p10", 0), rev.get("p50", 0), rev.get("p90", 0)])
    ws_mc.append(["Caja Final 24m", cash.get("p10", 0), cash.get("p50", 0), cash.get("p90", 0)])

    wb.save(str(out_path))
    return out_path


def export_zip(
    report_dir: Path,
    manifest: Dict[str, Any],
    full_markdown: str,
    bundle: Dict[str, Any],
    chapters: List[Dict[str, Any]],
) -> Path:
    """Empaqueta MD, PDF, PPTX, XLSX, manifest, validation_report y bundle en un ZIP."""
    pdf_p = export_pdf(report_dir, manifest, full_markdown)
    pptx_p = export_pptx(report_dir, manifest, chapters)
    xlsx_p = export_xlsx(report_dir, manifest, bundle)
    md_p = report_dir / "full_report.md"
    if not md_p.exists():
        md_p.write_text(full_markdown, encoding="utf-8")

    zip_path = report_dir / f"{manifest.get('project_slug', 'proyecto')}_{manifest.get('report_id', 'report')}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in (md_p, pdf_p, pptx_p, xlsx_p, report_dir / "report_manifest.json", report_dir / "validation_report.json"):
            if p.exists():
                zf.write(p, arcname=p.name)
        zf.writestr("analytics_bundle.json", json.dumps(bundle, ensure_ascii=False, indent=2))
    return zip_path
