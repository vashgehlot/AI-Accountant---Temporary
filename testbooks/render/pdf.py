"""A plain A4 page writer on reportlab, in invariant mode so the same input gives the same bytes."""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SUBJECT = "Synthetic test data, not a real document"
TOP, BOTTOM, LEFT, RIGHT = A4[1] - 50, 60, 50, A4[0] - 50


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def unique(path: Path) -> Path:
    """The path, or the same name with -2, -3 ... when a file of that name is already there."""
    n, candidate = 2, path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    return candidate


class Page:
    def __init__(self, path: Path, title: str, author: str):
        self.path = path
        self.c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
        self.c.setTitle(title)
        self.c.setAuthor(author)
        self.c.setSubject(SUBJECT)
        self.c.setCreator("testbooks")
        self.y = TOP

    def _room(self, height: float):
        if self.y - height < BOTTOM:
            self.c.showPage()
            self.y = TOP

    def text(self, s: str, size: int = 10, bold: bool = False, x: float = LEFT):
        self._room(size + 4)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(x, self.y, s)
        self.y -= size + 4

    def row(self, cells: list[tuple[float, str]], size: int = 9, bold: bool = False):
        """Cells at x positions; a negative x means right-aligned at abs(x)."""
        self._room(size + 4)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        for x, s in cells:
            if x < 0:
                self.c.drawRightString(-x, self.y, s)
            else:
                self.c.drawString(x, self.y, s)
        self.y -= size + 4

    def gap(self, n: float = 8):
        self.y -= n

    def stamp(self, s: str):
        """Large text across the page, as a VOID stamp."""
        self.c.saveState()
        self.c.setFont("Helvetica-Bold", 72)
        self.c.translate(A4[0] / 2, A4[1] / 2)
        self.c.rotate(30)
        self.c.drawCentredString(0, 0, s)
        self.c.restoreState()

    def save(self) -> Path:
        self.c.save()
        return self.path
