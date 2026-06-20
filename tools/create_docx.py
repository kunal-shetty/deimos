import os
import re
from .base import BaseTool

try:
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

EMPHASIS_RE = re.compile(r"(\*\*.+?\*\*|\*.+?\*)")


class CreateDocxTool(BaseTool):
    name = "create_docx"
    description = (
        "Create a Word (.docx) document from a structured content array. "
        "Read the 'docx' skill first (via read_skill) to learn the content "
        "block format and formatting conventions before calling this."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "output_path": {
                "type": "string",
                "description": "File path to save the document to, ending in .docx",
            },
            "content": {
                "type": "array",
                "description": (
                    "Array of content blocks. Each block has a 'type' field: "
                    "'heading' (text, level 1-4), 'paragraph' (text, supports "
                    "**bold**/*italic*), 'bullet_list' (items), "
                    "'numbered_list' (items), 'table' (headers, rows), "
                    "'page_break', or 'spacer'."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["output_path", "content"],
    }

    def run(self, output_path: str, content: list) -> str:
        if not DOCX_AVAILABLE:
            return (
                "Error: python-docx is not installed. "
                "Run: pip install python-docx --break-system-packages"
            )

        if not output_path.endswith(".docx"):
            output_path += ".docx"

        try:
            doc = Document()
            for block in content:
                self._render_block(doc, block)

            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
            doc.save(output_path)

            abs_path = os.path.abspath(output_path)
            return f"Created Word document: {abs_path} ({len(content)} content blocks)"
        except Exception as e:
            return f"Error creating document: {e}"

    def _render_block(self, doc, block: dict):
        block_type = block.get("type")

        if block_type == "heading":
            text = block.get("text", "")
            level = max(1, min(4, int(block.get("level", 2))))
            doc.add_heading(text, level=level)

        elif block_type == "paragraph":
            text = block.get("text", "")
            p = doc.add_paragraph()
            _add_runs_with_emphasis(p, text)

        elif block_type == "bullet_list":
            for item in block.get("items", []):
                p = doc.add_paragraph(style="List Bullet")
                _add_runs_with_emphasis(p, item)

        elif block_type == "numbered_list":
            for item in block.get("items", []):
                p = doc.add_paragraph(style="List Number")
                _add_runs_with_emphasis(p, item)

        elif block_type == "table":
            headers = block.get("headers", [])
            rows = block.get("rows", [])
            if not headers:
                return
            table = doc.add_table(rows=1, cols=len(headers))
            table.style = "Light Grid Accent 1"

            header_cells = table.rows[0].cells
            for i, h in enumerate(headers):
                header_cells[i].text = str(h)
                for p in header_cells[i].paragraphs:
                    for run in p.runs:
                        run.bold = True

            for row in rows:
                cells = table.add_row().cells
                for i, val in enumerate(row):
                    if i < len(cells):
                        cells[i].text = str(val)

        elif block_type == "page_break":
            doc.add_page_break()

        elif block_type == "spacer":
            doc.add_paragraph()


def _add_runs_with_emphasis(paragraph, text: str):
    """Split text on **bold** and *italic* markers and add styled runs."""
    if not text:
        return

    parts = EMPHASIS_RE.split(text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)