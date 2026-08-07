from __future__ import annotations

import base64
import html
import re
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = MODULE_ROOT / "docs"
EXPLANATION_ROOT = DOCS_ROOT / "CONDUCTOR_explanation"

PAGES = [
    (EXPLANATION_ROOT / "CONDUCTOR_v4_overview.md", EXPLANATION_ROOT / "CONDUCTOR_v4_overview.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_overview_A1_style.png"),
    (EXPLANATION_ROOT / "CONDUCTOR_v4_description_features.md", EXPLANATION_ROOT / "CONDUCTOR_v4_description_features.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_description_A1_style.png"),
    (EXPLANATION_ROOT / "CONDUCTOR_v4_clustering_features.md", EXPLANATION_ROOT / "CONDUCTOR_v4_clustering_features.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_clustering_A1_style.png"),
    (EXPLANATION_ROOT / "CONDUCTOR_v4_operator_features.md", EXPLANATION_ROOT / "CONDUCTOR_v4_operator_features.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_operator_A1_style.png"),
    (EXPLANATION_ROOT / "CONDUCTOR_v4_description_relationships_and_coverage.md", EXPLANATION_ROOT / "CONDUCTOR_v4_description_relationships_and_coverage.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_description_A1_style.png"),
    (DOCS_ROOT / "CONDUCTOR_v4_description_relationships_and_coverage.md", DOCS_ROOT / "CONDUCTOR_v4_description_relationships_and_coverage.html", EXPLANATION_ROOT / "A1_style_set" / "CONDUCTOR_description_A1_style.png"),
]

NAV = (
    '<nav><a href="CONDUCTOR_v4_overview.html">全体</a>'
    '<a href="CONDUCTOR_v4_description_features.html">Description</a>'
    '<a href="CONDUCTOR_v4_clustering_features.html">Clustering</a>'
    '<a href="CONDUCTOR_v4_operator_features.html">Operator</a>'
    '<a href="CONDUCTOR_v4_description_relationships_and_coverage.html">Description関係図</a></nav>'
)


def inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^]]+)]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_body(markdown: str) -> tuple[str, str]:
    lines = markdown.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "CONDUCTOR")
    output: list[str] = []
    index = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("!["):
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            language = stripped[3:].strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            output.append(f'<pre data-language="{html.escape(language)}"><code>{html.escape(chr(10).join(code))}</code></pre>')
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and is_table_separator(lines[index + 1]):
            flush_paragraph()
            headers = table_cells(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(table_cells(lines[index]))
                index += 1
            output.append("<div class='table-wrap'><table><thead><tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in headers) + "</tr></thead><tbody>")
            output.extend("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in rows)
            output.append("</tbody></table></div>")
            continue
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            pattern = r"^\d+\.\s+" if ordered else r"^[-*]\s+"
            while index < len(lines) and re.match(pattern, lines[index].strip()):
                items.append(re.sub(pattern, "", lines[index].strip()))
                index += 1
            output.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            output.append(f"<blockquote>{inline(stripped.lstrip('>').strip())}</blockquote>")
            index += 1
            continue
        paragraph.append(stripped.rstrip("  "))
        index += 1
    flush_paragraph()
    return title, "\n".join(output)


def render(source: Path, target: Path, image_path: Path) -> None:
    title, body = markdown_body(source.read_text(encoding="utf-8"))
    css = (EXPLANATION_ROOT / "conductor-docs.css").read_text(encoding="utf-8")
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    nav = NAV if target.parent == EXPLANATION_ROOT else ""
    document = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{css}</style></head>
<body><main>{nav}<img class="hero" src="data:image/png;base64,{image_data}" alt="{html.escape(title)}の概念図">
{body}</main></body></html>
'''
    target.write_text(document, encoding="utf-8")


def main() -> int:
    for source, target, image_path in PAGES:
        render(source, target, image_path)
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
