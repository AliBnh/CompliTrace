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
PAGE_HEADING_RE = re.compile(r"^page\s+\d+$", re.IGNORECASE)
SECTION_NUM_HEADING_RE = re.compile(r"^\d{1,2}\.\s+[A-Z][A-Za-z0-9\s\-/&()]{2,80}$")
SUBSECTION_NUM_HEADING_RE = re.compile(r"^\d{1,2}\.\d{1,2}\s+[A-Z][A-Za-z0-9\s\-/&()]{2,100}$")
FILE_PATH_RE = re.compile(r"([A-Za-z]:\\|/).*(\\.pdf|\\.docx?)", re.IGNORECASE)
NOISE_LINE_RE = re.compile(r"^y:\\\\|approved policies|approved templates", re.IGNORECASE)
POLICY_HEADER_RE = re.compile(r"(?:[A-Za-z][A-Za-z0-9&\s]{1,40}\s*-\s*)?privacy policy", re.IGNORECASE)
INLINE_HEADING_SPLIT_RE = re.compile(r"\s(?=(?:\d{1,2}\.\d{1,2}|\d{1,2}\.)\s+[A-Z])")
NUMBERED_LEAD_RE = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2})?\.?)\s+(?P<rest>.+)$")
STOP_TITLE_WORDS = {
    "we",
    "our",
    "this",
    "these",
    "by",
    "when",
    "in",
    "to",
    "individuals",
    "users",
    "you",
    "your",
    "it",
    "they",
}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_sentence_start(word: str) -> bool:
    w = word.lower().strip(",.;:()")
    return w in STOP_TITLE_WORDS or w in {"is", "are", "was", "were", "has", "have", "may", "can"}


def is_heading(line: str) -> bool:
    s = _normalize_space(line)
    if not s:
        return False
    if PAGE_HEADING_RE.match(s):
        return False
    if len(s) < 5:
        return False
    if "/" in s and any(len(tok) <= 3 for tok in s.split("/")):
        return False
    if len(s.split()) > 12:
        return False
    if s.endswith(".") and not SECTION_NUM_HEADING_RE.match(s):
        return False
    if s.lower().startswith(("article ", "chapter ")):
        return False
    if SECTION_NUM_HEADING_RE.match(s) or SUBSECTION_NUM_HEADING_RE.match(s):
        return True
    # Avoid sentence-like lines with commas and verbs in the middle.
    words = s.split()
    if len(words) >= 6 and any(_looks_like_sentence_start(w) for w in words[3:]):
        return False
    return bool(HEADING_RE.match(s) and (s.istitle() or s.isupper()))


def is_noise_line(line: str) -> bool:
    s = _normalize_space(line)
    if not s:
        return True
    if FILE_PATH_RE.search(s):
        return True
    if NOISE_LINE_RE.search(s):
        return True
    if POLICY_HEADER_RE.search(s) and len(s.split()) <= 10:
        return True
    if PAGE_HEADING_RE.match(s):
        return True
    if re.fullmatch(r"\d+", s):
        return True
    return False


def split_inline_headings(line: str) -> list[str]:
    line = _normalize_space(line)
    if not line:
        return []
    parts = INLINE_HEADING_SPLIT_RE.split(line)
    return [p.strip() for p in parts if p.strip()]


def scrub_inline_noise(text: str) -> str:
    text = POLICY_HEADER_RE.sub("", text)
    text = re.sub(r"\b\d{4}\.docx\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:draft|final)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-–—]\s*$", "", text)
    return _normalize_space(text)


def split_numbered_heading_and_body(line: str) -> tuple[str, str] | None:
    """Split lines like `6. Cookies ... We use ...` into heading and body."""
    m = NUMBERED_LEAD_RE.match(line)
    if not m:
        return None

    num = m.group("num")
    rest = m.group("rest").strip()
    words = rest.split()
    if len(words) < 3:
        return None

    cut = None
    for i, w in enumerate(words):
        if i >= 3 and _looks_like_sentence_start(w):
            cut = i
            break
    if cut is None and len(words) > 8:
        # If heading is too long, assume sentence starts around natural break.
        cut = 8
    if cut is None:
        return None

    heading = _normalize_space(f"{num} {' '.join(words[:cut])}")
    body = _normalize_space(" ".join(words[cut:]))
    if len(heading.split()) < 2 or len(body.split()) < 3:
        return None
    return heading, body


def _merge_small_sections(sections: list[ParsedSection], min_words: int = 40) -> list[ParsedSection]:
    if not sections:
        return sections

    merged: list[ParsedSection] = []
    for section in sections:
        wc = len(section.content.split())
        if merged and wc < min_words and not section.section_title.lower().startswith(("appendix", "annex")):
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


def _detect_boilerplate_lines(pages: list[tuple[int, list[str]]]) -> set[str]:
    """Find repeated short lines that appear across many pages (headers/footers)."""
    if len(pages) < 3:
        return set()

    counts: dict[str, int] = {}
    total = len(pages)
    for _, lines in pages:
        seen = {l.lower() for l in lines if 1 <= len(l.split()) <= 8}
        for line in seen:
            counts[line] = counts.get(line, 0) + 1

    threshold = max(2, int(total * 0.5))
    return {line for line, c in counts.items() if c >= threshold}


def parse_pdf_into_sections(pdf_path: str) -> list[ParsedSection]:
    import fitz

    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        lines: list[str] = []
        for raw_line in text.splitlines():
            for part in split_inline_headings(raw_line):
                cleaned = scrub_inline_noise(part)
                if not cleaned:
                    continue
                split_pair = split_numbered_heading_and_body(cleaned)
                if split_pair:
                    heading_part, body_part = split_pair
                    if not is_noise_line(heading_part):
                        lines.append(heading_part)
                    if body_part and not is_noise_line(body_part):
                        lines.append(body_part)
                elif not is_noise_line(cleaned):
                    lines.append(cleaned)
        pages.append((i, lines))

    boilerplate = _detect_boilerplate_lines(pages)

    sections: list[ParsedSection] = []
    current_title = "Introduction"
    current_lines: list[str] = []
    current_start: int | None = 1
    last_page: int | None = 1

    for page_num, lines in pages:
        for line in lines:
            if line.lower() in boilerplate and not is_heading(line):
                continue
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
                normalized_title = line
                if SECTION_NUM_HEADING_RE.match(line):
                    normalized_title = re.sub(r"^\d{1,2}\.\s+", "", line).strip()
                current_title = normalized_title
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
