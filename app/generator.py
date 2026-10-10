"""Certificate PDF generation using a single predefined template.

We draw the certificate with ReportLab directly onto an A4-landscape canvas.
This keeps the dependency footprint small (no headless browser / HTML engine)
while producing a real, shareable PDF.
"""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from app.config import OUTPUT_DIR

_PAGE = landscape(A4)
_WIDTH, _HEIGHT = _PAGE

# Template colors.
_NAVY = HexColor("#1b2a4a")
_GOLD = HexColor("#b8860b")
_GREY = HexColor("#555555")


def _draw_border(c: canvas.Canvas) -> None:
    c.setStrokeColor(_NAVY)
    c.setLineWidth(6)
    c.rect(20, 20, _WIDTH - 40, _HEIGHT - 40)
    c.setStrokeColor(_GOLD)
    c.setLineWidth(2)
    c.rect(32, 32, _WIDTH - 64, _HEIGHT - 64)


def _centered(c: canvas.Canvas, y: float, text: str, font: str, size: int, color) -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(_WIDTH / 2, y, text)


def render_certificate(
    *,
    cert_id: str,
    recipient_name: str,
    course_name: str,
    issuer: str,
    issue_date: str,
    output_dir: Path | None = None,
) -> Path:
    """Render one certificate PDF and return the path it was written to.

    Raises on any rendering failure so the caller can mark the certificate
    as failed.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{cert_id}.pdf"

    c = canvas.Canvas(str(path), pagesize=_PAGE)
    _draw_border(c)

    _centered(c, _HEIGHT - 140, "CERTIFICATE OF COMPLETION", "Helvetica-Bold", 32, _NAVY)
    _centered(c, _HEIGHT - 190, "This is proudly presented to", "Helvetica", 16, _GREY)
    _centered(c, _HEIGHT - 260, recipient_name, "Helvetica-Bold", 40, _GOLD)

    _centered(
        c,
        _HEIGHT - 320,
        "for successfully completing",
        "Helvetica",
        16,
        _GREY,
    )
    _centered(c, _HEIGHT - 360, course_name, "Helvetica-Bold", 24, _NAVY)

    # Footer: issuer, date, and the certificate id (acts as a verification ref).
    c.setFont("Helvetica", 13)
    c.setFillColor(_GREY)
    c.drawString(80, 90, f"Issued by: {issuer}")
    c.drawRightString(_WIDTH - 80, 90, f"Date: {issue_date}")
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(_WIDTH / 2, 55, f"Certificate ID: {cert_id}")

    c.showPage()
    c.save()
    return path
