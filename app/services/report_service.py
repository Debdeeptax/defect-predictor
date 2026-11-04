"""ReportService — renders a prediction payload as CSV / PDF and compares two runs.

The payload is the JSON-serialisable dict produced by PredictionEngine.predict(); the
web layer stores it on the Report row and passes it here for export.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app.services.prediction_engine import RISK_HIGH, RISK_LOW, RISK_MEDIUM, RISK_ORDER

RISK_COLORS = {RISK_HIGH: colors.HexColor("#c0392b"), RISK_MEDIUM: colors.HexColor("#e67e22"),
               RISK_LOW: colors.HexColor("#27ae60")}
PDF_MAX_FILES = 200

FILE_CSV_COLUMNS = [
    "rank", "file", "language", "risk", "probability", "function_probability",
    "class_probability", "driver_level", "driver_unit", "driver_line", "top_metric_1",
    "top_metric_2", "top_metric_3", "explanation_method", "loc", "functions", "classes",
    "max_cc", "avg_cc", "maintainability_index", "partial_metrics",
]
UNIT_CSV_COLUMNS = ["file", "level", "unit", "start_line", "risk", "probability",
                    "top_metric_1", "top_metric_2", "top_metric_3", "explanation_method"]


def _fmt_metric(m: dict | None) -> str:
    if not m:
        return ""
    sign = "+" if m["contribution"] > 0 else ""
    return f"{m['label']}={m['value']:g} ({sign}{m['contribution']:.3f})"


class ReportService:
    # ------------------------------------------------------------------ CSV
    @staticmethod
    def to_csv(payload: dict[str, Any], granularity: str = "file") -> str:
        buf = io.StringIO()
        if granularity == "unit":
            w = csv.DictWriter(buf, fieldnames=UNIT_CSV_COLUMNS, lineterminator="\n")
            w.writeheader()
            for f in payload["files"]:
                for u in f["units"]:
                    tm = u["top_metrics"] + [None] * 3
                    w.writerow({"file": f["path"], "level": u["level"], "unit": u["unit"],
                                "start_line": u["start_line"], "risk": u["risk"],
                                "probability": u["probability"],
                                "top_metric_1": _fmt_metric(tm[0]), "top_metric_2": _fmt_metric(tm[1]),
                                "top_metric_3": _fmt_metric(tm[2]),
                                "explanation_method": u["explanation_method"]})
            return buf.getvalue()

        w = csv.DictWriter(buf, fieldnames=FILE_CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for f in payload["files"]:
            tm = f["top_metrics"] + [None] * 3
            d = f["driver"] or {}
            m = f["metrics"]
            w.writerow({
                "rank": f["rank"], "file": f["path"], "language": f["language"], "risk": f["risk"],
                "probability": f["probability"], "function_probability": f["function_probability"],
                "class_probability": f["class_probability"], "driver_level": d.get("level"),
                "driver_unit": d.get("unit"), "driver_line": d.get("start_line"),
                "top_metric_1": _fmt_metric(tm[0]), "top_metric_2": _fmt_metric(tm[1]),
                "top_metric_3": _fmt_metric(tm[2]), "explanation_method": f["explanation_method"],
                "loc": m.get("loc"), "functions": m.get("functions"), "classes": m.get("classes"),
                "max_cc": m.get("max_cc"), "avg_cc": m.get("avg_cc"),
                "maintainability_index": m.get("maintainability_index"),
                "partial_metrics": f["partial"],
            })
        return buf.getvalue()

    # ------------------------------------------------------------------ PDF
    @staticmethod
    def to_pdf(payload: dict[str, Any], *, title: str = "Defect Prediction Report",
               source: str = "", author: str = "", report_id: int | str | None = None) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm,
                                rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                                title=title, author=author or "SDP System")
        ss = getSampleStyleSheet()
        small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=7.5, leading=9,
                               alignment=TA_LEFT)
        story: list = [Paragraph(escape(title), ss["Title"])]

        s = payload["summary"]
        models = payload.get("models", {})
        meta_rows = [
            ["Report", f"#{report_id}" if report_id is not None else "-",
             "Generated", _nice_dt(payload.get("generated_at"))],
            ["Source", Paragraph(escape(source or "-"), small), "Submitted by", author or "-"],
            ["Files analysed", str(s["files"]), "Units scored",
             f"{s['units']} ({s['function_units']} functions, {s['class_units']} classes)"],
            ["Function model", _model_str(models.get("function")),
             "Class model", _model_str(models.get("class"))],
            ["Risk thresholds", f"Medium ≥ {payload['thresholds']['medium']}, "
                                f"High ≥ {payload['thresholds']['high']}",
             "Skipped files", str(s["skipped_count"])],
        ]
        t = Table(meta_rows, colWidths=[32 * mm, 95 * mm, 32 * mm, 95 * mm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ]))
        story += [t, Spacer(1, 5 * mm)]

        story.append(KeepTogether([Paragraph("Risk distribution", ss["Heading3"]),
                                   _risk_chart(s["risk_counts"])]))
        story.append(Spacer(1, 4 * mm))

        story.append(Paragraph("Files ranked by defect probability", ss["Heading3"]))
        files = payload["files"][:PDF_MAX_FILES]
        rows = [["#", "File", "Lang", "Risk", "Prob.", "Driving unit", "Top contributing metrics"]]
        for f in files:
            d = f["driver"] or {}
            rows.append([
                str(f["rank"]), Paragraph(escape(f["path"]), small), f["language"], f["risk"],
                f"{f['probability']:.3f}",
                Paragraph(escape(f"{d.get('unit', '-')} (line {d.get('start_line', '-')})"), small),
                Paragraph("<br/>".join(escape(_fmt_metric(m)) for m in f["top_metrics"][:3]) or "-", small),
            ])
        ft = Table(rows, repeatRows=1,
                   colWidths=[8 * mm, 70 * mm, 18 * mm, 16 * mm, 14 * mm, 55 * mm, 88 * mm])
        style = [
            ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ]
        for i, f in enumerate(files, start=1):
            style += [("TEXTCOLOR", (3, i), (3, i), RISK_COLORS[f["risk"]]),
                      ("FONTNAME", (3, i), (3, i), "Helvetica-Bold")]
        ft.setStyle(TableStyle(style))
        story.append(ft)
        if len(payload["files"]) > PDF_MAX_FILES:
            story.append(Paragraph(f"… {len(payload['files']) - PDF_MAX_FILES} more files in the "
                                   f"CSV export.", small))

        notes = list(payload.get("warnings", []))
        if payload.get("skipped"):
            notes.append("Skipped: " + "; ".join(f"{x['path']} ({x['reason']})"
                                                 for x in payload["skipped"][:30]))
        notes.append(
            "Method: per-unit probabilities from Random-Forest-style models trained on NASA MDP "
            "(function level) and PROMISE CK (class level); a file's probability is the maximum over "
            "its units. Contributions are SHAP values (positive = raises risk). Models were trained "
            "on C/Java projects, so treat scores on other code as relative rankings.")
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Notes", ss["Heading3"]))
        story += [Paragraph(escape(n), small) for n in notes]

        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
        return buf.getvalue()

    # ------------------------------------------------------------------ compare
    @staticmethod
    def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        """Compare run A (baseline) with run B (newer)."""
        fa = {f["path"]: f for f in a["files"]}
        fb = {f["path"]: f for f in b["files"]}
        rows = []
        for path in sorted(set(fa) | set(fb)):
            x, y = fa.get(path), fb.get(path)
            status = "added" if x is None else "removed" if y is None else "common"
            pa = x["probability"] if x else None
            pb = y["probability"] if y else None
            ra = x["risk"] if x else None
            rb = y["risk"] if y else None
            change = "same"
            if status == "common" and ra != rb:
                change = "worse" if RISK_ORDER[rb] < RISK_ORDER[ra] else "better"
            elif status != "common":
                change = status
            rows.append({"path": path, "status": status, "probability_a": pa, "probability_b": pb,
                         "delta": round(pb - pa, 4) if pa is not None and pb is not None else None,
                         "risk_a": ra, "risk_b": rb, "risk_change": change})
        rows.sort(key=lambda r: (-(abs(r["delta"]) if r["delta"] is not None else 2), r["path"]))
        common = [r for r in rows if r["status"] == "common"]
        return {
            "rows": rows,
            "summary": {
                "common": len(common),
                "added": sum(r["status"] == "added" for r in rows),
                "removed": sum(r["status"] == "removed" for r in rows),
                "worse": sum(r["risk_change"] == "worse" for r in rows),
                "better": sum(r["risk_change"] == "better" for r in rows),
                "mean_delta": round(sum(r["delta"] for r in common) / len(common), 4) if common else 0.0,
                "risk_counts_a": a["summary"]["risk_counts"],
                "risk_counts_b": b["summary"]["risk_counts"],
            },
        }


# ---------------------------------------------------------------------- helpers
def _risk_chart(counts: dict[str, int]) -> Drawing:
    d = Drawing(160 * mm, 45 * mm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 15 * mm, 8 * mm, 80 * mm, 32 * mm
    levels = [RISK_HIGH, RISK_MEDIUM, RISK_LOW]
    chart.data = [[counts.get(k, 0) for k in levels]]
    chart.categoryAxis.categoryNames = levels
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(1, max(chart.data[0])) * 1.15
    chart.valueAxis.valueStep = max(1, round(chart.valueAxis.valueMax / 4))
    chart.bars.strokeWidth = 0
    for i, k in enumerate(levels):
        chart.bars[(0, i)].fillColor = RISK_COLORS[k]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontName = "Helvetica"
    d.add(chart)
    for i, k in enumerate(levels):
        d.add(String(105 * mm, (36 - 9 * i) * mm, f"{k}: {counts.get(k, 0)} file(s)",
                     fontName="Helvetica", fontSize=9, fillColor=RISK_COLORS[k]))
    return d


def _model_str(m: dict | None) -> str:
    if not m:
        return "not available"
    auc = f", CV AUC {m['cv_auc']:.3f}" if m.get("cv_auc") is not None else ""
    return f"v{m.get('version')} {m.get('display_name') or m.get('file')}{auc}"


def _nice_dt(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(14 * mm, 7 * mm, "Software Defect Prediction System")
    canvas.drawRightString(doc.pagesize[0] - 14 * mm, 7 * mm, f"Page {doc.page}")
    canvas.restoreState()
