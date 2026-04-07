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


HEADING_RE = re.compile(r"^[A-Z][A-Za-z0-9\s,/:&()\-]{2,100}$")
PAGE_RE = re.compile(r"^(?:page\s+)?\d{1,4}$", re.IGNORECASE)
SECTION_NUM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(.+)$")
SUBSECTION_HEADING_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,2}\s+[A-Z].{1,120}$")
SECTION_HEADING_RE = re.compile(r"^\d{1,2}\.\s+[A-Z].{1,120}$")
FILE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/).*(?:\.pdf|\.docx?|\.txt)", re.IGNORECASE)
MULTISPACE_RE = re.compile(r"\s+")
INLINE_HEADING_RE = re.compile(r"(?=(?:^|\s)(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+[A-Z])")
EMBEDDED_SUBHEADING_RE = re.compile(r"\s(?=\d{1,2}(?:\.\d{1,2}){0,2}\.?\s+[A-Z])")

SENTENCE_START_WORDS = {
    "we",
    "our",
    "this",
    "these",
    "they",
    "it",
    "you",
    "your",
    "the",
    "a",
    "an",
    "in",
    "to",
    "for",
    "by",
    "of",
    "with",
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "may",
    "can",
    "will",
    "should",
}


def _normalize_space(text: str) -> str:
    return MULTISPACE_RE.sub(" ", text).strip()


def _canonical_line(text: str) -> str:
    return _normalize_space(text).lower()


def _clean_line(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = _normalize_space(text)
    text = re.sub(r"\s*[-–—]\s*$", "", text)
    return text


def is_noise_line(line: str) -> bool:
    s = _clean_line(line)
    if not s:
        return True
    if FILE_PATH_RE.search(s):
        return True
    if PAGE_RE.match(s):
        return True
    if re.fullmatch(r"[\W_]+", s):
        return True
    if len(s) <= 2:
        return True
    return False


def _looks_sentence_like(words: list[str]) -> bool:
    if len(words) < 6:
        return False
    return any(w.lower().strip(",.;:()") in SENTENCE_START_WORDS for w in words[3:])


def is_heading(line: str) -> bool:
    s = _clean_line(line)
    if not s or is_noise_line(s):
        return False

    if SECTION_HEADING_RE.match(s) or SUBSECTION_HEADING_RE.match(s):
        return True

    if len(s.split()) > 12:
        return False
    if "/" in s and any(len(tok.strip()) <= 3 for tok in s.split("/")):
        return False
    if s.endswith("."):
        return False
    if s.lower().startswith(("article ", "chapter ")):
        return False

    words = s.split()
    if _looks_sentence_like(words):
        return False

    return bool(HEADING_RE.match(s) and (s.istitle() or s.isupper()))


def split_inline_numbered_chunks(line: str) -> list[str]:
    """Split a line containing multiple inline numbered headings into chunks."""
    s = _clean_line(line)
    if not s:
        return []

    matches = list(INLINE_HEADING_RE.finditer(s))
    if len(matches) <= 1:
        return [s]

    starts = [m.start() for m in matches]
    parts: list[str] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(s)
        chunk = _clean_line(s[start:end])
        if chunk:
            parts.append(chunk)
    return parts or [s]


def split_numbered_heading_and_body(line: str) -> tuple[str, str] | None:
    """Split `N(.M) Heading ... body` into heading/body when body is detectable."""
    s = _clean_line(line)
    m = SECTION_NUM_RE.match(s)
    if not m:
        return None

    number = m.group(1)
    rest = m.group(2)
    words = rest.split()
    if len(words) < 4:
        return None

    cut: int | None = None
    for i, word in enumerate(words):
        norm = word.lower().strip(",.;:()")
        if i >= 3 and norm in SENTENCE_START_WORDS:
            cut = i
            break

    if cut is None and len(words) > 9:
        cut = 9

    if cut is None:
        return None

    heading = _clean_line(f"{number}. {' '.join(words[:cut])}")
    body = _clean_line(" ".join(words[cut:]))
    if len(heading.split()) < 2 or len(body.split()) < 3:
        return None
    return heading, body


def _detect_boilerplate_lines(pages: list[tuple[int, list[str]]]) -> set[str]:
    """Detect repeated short lines likely to be page headers/footers."""
    if len(pages) < 3:
        return set()

    counts: dict[str, int] = {}
    for _, lines in pages:
        seen: set[str] = set()
        for line in lines:
            c = _canonical_line(line)
            if 1 <= len(c.split()) <= 10:
                seen.add(c)
        for c in seen:
            counts[c] = counts.get(c, 0) + 1

    threshold = max(2, int(len(pages) * 0.5))
    return {k for k, v in counts.items() if v >= threshold}


def _normalize_section_title(title: str) -> str:
    s = _clean_line(title)
    m = SECTION_NUM_RE.match(s)
    if m:
        num = m.group(1)
        rest = _clean_line(m.group(2))
        return f"{num} {rest}".strip()
    return s


def _remove_boilerplate_phrases(text: str, boilerplate_lines: set[str]) -> str:
    """Remove frequent header/footer phrases even when embedded inside content lines."""
    cleaned = text
    for phrase in boilerplate_lines:
        if not phrase or len(phrase.split()) > 6:
            continue
        escaped = re.escape(phrase)
        cleaned = re.sub(rf"\b{escaped}\b\s*[-–—]?", " ", cleaned, flags=re.IGNORECASE)
    return _clean_line(cleaned)


def _split_embedded_numbered_subheadings(text: str) -> list[str]:
    """Split paragraph text when inline numbered subheadings are embedded in body text."""
    parts = EMBEDDED_SUBHEADING_RE.split(text)
    cleaned_parts = [_clean_line(p) for p in parts if _clean_line(p)]

    # Avoid pathological splitting when no real heading-like chunk exists.
    if len(cleaned_parts) <= 1:
        return cleaned_parts
    if not any(SECTION_NUM_RE.match(part) for part in cleaned_parts[1:]):
        return [_clean_line(text)]
    return cleaned_parts


def _refine_sections(sections: list[ParsedSection], boilerplate_lines: set[str]) -> list[ParsedSection]:
    """Post-process sections to remove boilerplate and split leaked inline subheadings."""
    refined: list[ParsedSection] = []

    for sec in sections:
        content = _remove_boilerplate_phrases(sec.content, boilerplate_lines)
        title = _normalize_section_title(sec.section_title)

        # Fix weak parent titles where body immediately starts with numbered heading.
        if not SECTION_NUM_RE.match(title):
            leading = split_numbered_heading_and_body(content)
            if leading:
                title = _normalize_section_title(leading[0])
                content = leading[1]

        parts = _split_embedded_numbered_subheadings(content)
        if not parts:
            continue

        primary_content: list[str] = []
        current_title = title
        page_start = sec.page_start
        page_end = sec.page_end

        for idx, part in enumerate(parts):
            parsed = split_numbered_heading_and_body(part)
            if idx == 0:
                if parsed and SECTION_NUM_RE.match(current_title):
                    primary_content.append(parsed[1])
                else:
                    primary_content.append(part)
                continue

            # If this chunk clearly starts with a subheading, open a new section.
            if parsed:
                if primary_content:
                    refined.append(
                        ParsedSection(
                            section_order=0,
                            section_title=current_title,
                            content=_clean_line(" ".join(primary_content)),
                            page_start=page_start,
                            page_end=page_end,
                        )
                    )
                current_title = _normalize_section_title(parsed[0])
                primary_content = [parsed[1]]
            else:
                primary_content.append(part)

        if primary_content:
            refined.append(
                ParsedSection(
                    section_order=0,
                    section_title=current_title,
                    content=_clean_line(" ".join(primary_content)),
                    page_start=page_start,
                    page_end=page_end,
                )
            )

    for i, sec in enumerate(refined, start=1):
        refined[i - 1] = ParsedSection(
            section_order=i,
            section_title=sec.section_title,
            content=sec.content,
            page_start=sec.page_start,
            page_end=sec.page_end,
        )
    return refined


def _commit_section(
    sections: list[ParsedSection],
    title: str,
    content_lines: list[str],
    page_start: int | None,
    page_end: int | None,
) -> None:
    content = _clean_line(" ".join(content_lines))
    if not content:
        return
    sections.append(
        ParsedSection(
            section_order=len(sections) + 1,
            section_title=_normalize_section_title(title) or "Untitled Section",
            content=content,
            page_start=page_start,
            page_end=page_end,
        )
    )


def parse_pdf_into_sections(pdf_path: str) -> list[ParsedSection]:
    import fitz

    doc = fitz.open(pdf_path)
    pages: list[tuple[int, list[str]]] = []

    for page_num, page in enumerate(doc, start=1):
        page_lines: list[str] = []
        for raw_line in page.get_text("text").splitlines():
            cleaned = _clean_line(raw_line)
            if not cleaned or is_noise_line(cleaned):
                continue

            chunks = split_inline_numbered_chunks(cleaned)
            for chunk in chunks:
                split_pair = split_numbered_heading_and_body(chunk)
                if split_pair:
                    heading, body = split_pair
                    if not is_noise_line(heading):
                        page_lines.append(heading)
                    if body and not is_noise_line(body):
                        page_lines.append(body)
                elif not is_noise_line(chunk):
                    page_lines.append(chunk)

        pages.append((page_num, page_lines))

    boilerplate = _detect_boilerplate_lines(pages)

    sections: list[ParsedSection] = []
    current_title = "Introduction"
    current_content: list[str] = []
    current_start: int | None = 1
    last_page: int | None = 1

    for page_num, lines in pages:
        for line in lines:
            if _canonical_line(line) in boilerplate and not is_heading(line):
                continue

            if is_heading(line):
                _commit_section(sections, current_title, current_content, current_start, last_page)
                current_title = line
                current_content = []
                current_start = page_num
                last_page = page_num
                continue

            current_content.append(line)
            last_page = page_num

    _commit_section(sections, current_title, current_content, current_start, last_page)

    if sections:
        return _refine_sections(sections, boilerplate)

    full_text = _clean_line(" ".join(" ".join(lines) for _, lines in pages))
    return [
        ParsedSection(
            section_order=1,
            section_title="Document Body",
            content=full_text,
            page_start=1,
            page_end=len(pages) if pages else 1,
        )
    ]
