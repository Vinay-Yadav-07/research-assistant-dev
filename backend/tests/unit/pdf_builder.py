"""Builds small PDFs in memory with PyMuPDF, so parser tests need no files."""

from dataclasses import dataclass, field

import pymupdf

BODY_SIZE = 10
HEADING_SIZE = 16
LOREM = (
    "Porous scaffolds support cell attachment and nutrient transport in engineered tissue. "
    "Their stiffness and pore size are tuned to match the target tissue."
)


@dataclass
class Page:
    """Text blocks top to bottom: (text, font size), plus optional footer, vertical margin text,
    and two columns."""

    blocks: list[tuple[str, float]] = field(default_factory=list)
    footer: str | None = None
    margin_text: str | None = None
    columns: tuple[str, str] | None = None
    image_only: bool = False


def build_pdf(pages: list[Page], *, title: str | None = None, password: str | None = None) -> bytes:
    """Render `pages` to PDF bytes."""
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    for spec in pages:
        page = document.new_page(width=595, height=842)
        if spec.image_only:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
            pixmap.clear_with(180)
            page.insert_image(pymupdf.Rect(50, 50, 545, 792), pixmap=pixmap)
        y = 72.0
        for text, size in spec.blocks:
            rect = pymupdf.Rect(72, y, 523, y + 400)
            used = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
            y += 400 - used + size
        if spec.columns is not None:
            left, right = spec.columns
            page.insert_textbox(pymupdf.Rect(50, y, 287, 780), left, fontsize=BODY_SIZE)
            page.insert_textbox(pymupdf.Rect(308, y, 545, 780), right, fontsize=BODY_SIZE)
        if spec.footer is not None:
            page.insert_text((72, 815), spec.footer, fontsize=8)
        if spec.margin_text is not None:
            page.insert_text((20, 600), spec.margin_text, fontsize=8, rotate=90)
    if title is not None:
        document.set_metadata({"title": title})
    if password is not None:
        data: bytes = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password
        )
    else:
        data = document.tobytes()
    document.close()
    return data
