from __future__ import annotations

import re
from dataclasses import dataclass



@dataclass
class ParsedSection:
    section_order: int
    section_title: str
    content: str
    page_start: int | None
    page_end: int | None


HEADING_RE = re.compile(r"^[A-Z][A-Za-z0-9\s,/:&()\-]{2,90}$")


def is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s.split()) > 12:
        return False
    if s.endswith("."):
        return False
    if s.lower().startswith(("article ", "chapter ")):
        return False
    return bool(HEADING_RE.match(s) and (s.istitle() or s.isupper()))


def _merge_small_sections(sections: list[ParsedSection], min_words: int = 50) -> list[ParsedSection]:
    if not sections:
        return sections

    merged: list[ParsedSection] = []
    for section in sections:
        wc = len(section.content.split())
        if merged and wc < min_words:
            prev = merged[-1]
            merged[-1] = ParsedSection(
                section_order=prev.section_order,
                section_title=prev.section_title,
                content=f"{prev.content}\n\n{section.content}".strip(),
                page_start=prev.page_start,
                page_end=section.page_end or prev.page_end,
            )
        else:
            merged.append(section)

    for idx, sec in enumerate(merged, start=1):
        merged[idx - 1] = ParsedSection(
            section_order=idx,
            section_title=sec.section_title,
            content=sec.content,
            page_start=sec.page_start,
            page_end=sec.page_end,
        )

    return merged


def parse_pdf_into_sections(pdf_path: str) -> list[ParsedSection]:
    import fitz

    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        pages.append((i, lines))

    sections: list[ParsedSection] = []
    current_title = "Introduction"
    current_lines: list[str] = []
    current_start: int | None = 1
    last_page: int | None = 1

    for page_num, lines in pages:
        for line in lines:
            if is_heading(line):
                if current_lines:
                    sections.append(
                        ParsedSection(
                            section_order=len(sections) + 1,
                            section_title=current_title,
                            content=" ".join(current_lines).strip(),
                            page_start=current_start,
                            page_end=last_page,
                        )
                    )
                current_title = line
                current_lines = []
                current_start = page_num
                last_page = page_num
            else:
                current_lines.append(line)
                last_page = page_num

    if current_lines:
        sections.append(
            ParsedSection(
                section_order=len(sections) + 1,
                section_title=current_title,
                content=" ".join(current_lines).strip(),
                page_start=current_start,
                page_end=last_page,
            )
        )

    if not sections:
        full_text = "\n".join("\n".join(lines) for _, lines in pages).strip()
        return [
            ParsedSection(
                section_order=1,
                section_title="Document Body",
                content=full_text,
                page_start=1,
                page_end=len(pages) if pages else 1,
            )
        ]

    return _merge_small_sections(sections)
