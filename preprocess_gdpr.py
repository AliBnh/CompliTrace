import json
import re
import sys
import hashlib
from bisect import bisect_right
from pathlib import Path

import fitz  # PyMuPDF


# ============================================================
# Configuration
# ============================================================

TARGET_MAX_WORDS_PER_CHUNK = 150
SOFT_MAX_WORDS_PER_CHUNK = 190
HARD_MAX_WORDS_PER_CHUNK = 220

MAX_TOP_LEVEL_PARAGRAPHS_PER_CHUNK = 2
MAX_SUBPOINTS_PER_GROUP = 3
MIN_LAST_GROUP_WORDS = 35


# ============================================================
# Regexes
# ============================================================

RE_PAGE_MARKER = re.compile(r"^L\s+\d+/\d+$")
RE_ARTICLE_HEADING = re.compile(r"(?m)^Article\s+(\d+[A-Za-z]?)\s*$")
RE_CHAPTER_HEADING = re.compile(r"(?m)^CHAPTER\s+([IVXLCDM]+)\s*$")
RE_SECTION_HEADING = re.compile(r"(?m)^Section\s+\d+[A-Za-z]*\s*$", re.IGNORECASE)

RE_DANGLING_TITLE_END = re.compile(
    r".*\b(of|or|and|to|for|with|in|on|under|regarding|concerning|including|restriction)\s*$",
    re.IGNORECASE,
)

RE_TOP_LEVEL_PARA = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=:\s)|(?<=;\s))\((\d+)\)\s|^\s*(\d+)\.\s*",
    re.MULTILINE,
)

RE_ANY_LETTERED_MARKER = re.compile(r"\(([a-z])\)\s")
RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

RE_DANGLING_REFERENCE_END = re.compile(
    r"\b(point|points|article|articles|paragraph|paragraphs|chapter|section|title|or|and|to|of|under|in)\s*$",
    re.IGNORECASE,
)
RE_REFERENCE_CONTINUATION_START = re.compile(
    r"^(?:\([a-z0-9]+\)\s+)?(?:of|and|or|to)\b",
    re.IGNORECASE,
)
RE_SUBPOINT_INTRO = re.compile(
    r"\b("
    r"one of the following|"
    r"all of the following|"
    r"at least the following|"
    r"shall contain|"
    r"shall provide|"
    r"following information|"
    r"following conditions|"
    r"following applies|"
    r"following grounds|"
    r"following tasks|"
    r"where one of the following applies|"
    r"where one of the following grounds applies|"
    r"the following information|"
    r"the following applies"
    r")\b",
    re.IGNORECASE,
)


# ============================================================
# Helpers
# ============================================================

def sha1_short(text: str, length: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def roman_to_int(value: str | None) -> int | None:
    if not value:
        return None
    mapping = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(value.upper()):
        cur = mapping[ch]
        if cur < prev:
            total -= cur
        else:
            total += cur
            prev = cur
    return total


def make_chunk_id(
    article_number: str,
    paragraph_ref: str | None,
    content: str,
    subpoint_range: str | None = None,
    subchunk_index: int | None = None,
) -> str:
    base = {
        "article_number": article_number,
        "paragraph_ref": paragraph_ref,
        "subpoint_range": subpoint_range,
        "subchunk_index": subchunk_index,
        "content": content,
    }
    digest = sha1_short(json.dumps(base, ensure_ascii=False, sort_keys=True))
    prefix = f"gdpr-art-{article_number}-p-{paragraph_ref or 'null'}"
    if subpoint_range:
        prefix += f"-sp-{subpoint_range}"
    if subchunk_index is not None:
        prefix += f"-seg-{subchunk_index}"
    return f"{prefix}-{digest}"


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(
        RE_ARTICLE_HEADING.match(s)
        or RE_CHAPTER_HEADING.match(s)
        or RE_SECTION_HEADING.match(s)
    )


def should_continue_title(previous_title_line: str, current_line: str) -> bool:
    s = current_line.strip()
    if not s:
        return False
    if is_heading_line(s):
        return False
    if RE_TOP_LEVEL_PARA.search(s):
        return False
    if re.match(r"^[a-z]", s):
        return True
    if RE_DANGLING_TITLE_END.match(previous_title_line.strip()):
        return True
    if len(s.split()) <= 4 and not re.search(r"[.;:!?]$", s):
        return True
    return False


def boundary_is_unsafe(left_text: str, right_text: str) -> bool:
    left = left_text.strip()
    right = right_text.strip()

    if not left or not right:
        return False
    if RE_DANGLING_REFERENCE_END.search(left):
        return True
    if RE_REFERENCE_CONTINUATION_START.match(right):
        return True
    return False


def is_true_subpoint_boundary(text: str, pos: int) -> bool:
    if pos == 0:
        return True

    prefixes = ["\n", ": ", "; ", "; or ", "; and "]
    lower_text = text.lower()

    for prefix in prefixes:
        start = pos - len(prefix)
        if start >= 0 and lower_text[start:pos] == prefix:
            return True

    return False


def find_true_lettered_subpoint_matches(text: str):
    matches = []
    for match in RE_ANY_LETTERED_MARKER.finditer(text):
        if is_true_subpoint_boundary(text, match.start()):
            matches.append(match)
    return matches


# ============================================================
# Text cleanup / repair
# ============================================================

BROKEN_PHRASE_REPAIRS = [
    (r"\bnot later than hours\b", "not later than 72 hours"),
    (r"\breferred to in Article\s*,", "referred to in Article 10,"),
    (r"\bpursuant to Article\s*;", "pursuant to Article 10;"),
    (r"\bthe right referred to in paragraphs 1 and shall\b", "the right referred to in paragraphs 1 and 2 shall"),
    (r"\bwithin period of up to eight weeks\b", "within a period of up to eight weeks"),
    (r"\btaxation a matters\b", "taxation matters"),
]

OCR_SEP = "(?:\\s|\\u00a0|\\u2009|\\u200a|\\u202f|\\u00ad|-)+"

BROKEN_WORD_PATTERNS = [
    ("\\binternat" + OCR_SEP + "ional\\b", "international"),
    ("\\bin" + OCR_SEP + "ternational\\b", "international"),
    ("\\bcertifi" + OCR_SEP + "cation\\b", "certification"),
    ("\\bauthoris" + OCR_SEP + "ation\\b", "authorisation"),
    ("\\bauthor" + OCR_SEP + "isation\\b", "authorisation"),
    ("\\badminis" + OCR_SEP + "tration\\b", "administration"),
    ("\\bpropor" + OCR_SEP + "tionate\\b", "proportionate"),
    ("\\bphysio" + OCR_SEP + "logical\\b", "physiological"),
    ("\\brepresenta" + OCR_SEP + "tive\\b", "representative"),
    ("\\bidenti" + OCR_SEP + "fication\\b", "identification"),
    ("\\borgan" + OCR_SEP + "isation\\b", "organisation"),
    ("\\borgan" + OCR_SEP + "isations\\b", "organisations"),
]


def repair_broken_words(text: str) -> str:
    for pattern, replacement in BROKEN_WORD_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def repair_known_phrase_defects(text: str) -> str:
    for pattern, replacement in BROKEN_PHRASE_REPAIRS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def clean_page_text(raw: str) -> str:
    lines = raw.splitlines()
    cleaned = []
    skip_footnote_block = False

    for line in lines:
        s = line.strip().replace("\u00ad", "")

        if skip_footnote_block:
            if not s:
                skip_footnote_block = False
            continue

        if not s:
            cleaned.append("")
            continue

        if s in {
            "I",
            "(Legislative acts)",
            "REGULATIONS",
            "EN",
            "Official Journal of the European Union",
            "4.5.2016",
        }:
            continue

        if RE_PAGE_MARKER.match(s):
            continue

        if re.fullmatch(r"\(\d+\)", s):
            continue

        if re.match(r"^\(\d+\)\s+(OJ|Directive|Regulation|Council|Commission|Position|Decision)", s):
            skip_footnote_block = True
            continue

        if re.match(r"^OJ\s+[CL]\s+\d+", s):
            skip_footnote_block = True
            continue

        cleaned.append(s)

    text = "\n".join(cleaned).strip()
    text = repair_broken_words(text)
    text = repair_known_phrase_defects(text)
    return text


def normalize_block_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\u2011", "-")
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "-")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = repair_broken_words(text)
    text = repair_known_phrase_defects(text)
    return text


# ============================================================
# PDF extraction
# ============================================================

def extract_pages(pdf_path: str):
    doc = fitz.open(pdf_path)
    pages = []

    for idx, page in enumerate(doc):
        raw = page.get_text("text")
        cleaned = clean_page_text(raw)
        pages.append({
            "page_number": idx + 1,
            "text": cleaned,
        })

    return pages


def build_combined_text_with_offsets(pages):
    parts = []
    page_offsets = []
    current_offset = 0

    for page in pages:
        page_offsets.append((page["page_number"], current_offset))
        parts.append(page["text"])
        current_offset += len(page["text"]) + 2

    return "\n\n".join(parts), page_offsets


def char_offset_to_page(char_offset: int, page_offsets):
    offsets_only = [offset for _, offset in page_offsets]
    idx = bisect_right(offsets_only, char_offset) - 1
    idx = max(0, idx)
    return page_offsets[idx][0]


# ============================================================
# Operative GDPR window
# ============================================================

def extract_operative_window(full_text: str):
    start_marker = "HAVE ADOPTED THIS REGULATION:"
    end_marker = "Done at Brussels"

    start_idx = full_text.find(start_marker)
    if start_idx == -1:
        raise ValueError("Could not find start marker: HAVE ADOPTED THIS REGULATION:")

    end_idx = full_text.find(end_marker, start_idx)
    if end_idx == -1:
        end_idx = len(full_text)

    return start_idx, end_idx, full_text[start_idx:end_idx].strip()


# ============================================================
# Chapter / Article parsing
# ============================================================

def parse_chapters(operative_text: str):
    pattern = re.compile(r"(?m)^CHAPTER\s+([IVXLCDM]+)\s*$\n^(.+?)\s*$")
    chapters = []

    for match in pattern.finditer(operative_text):
        chapters.append({
            "chapter_number": match.group(1).strip(),
            "chapter_number_int": roman_to_int(match.group(1).strip()),
            "chapter_title": match.group(2).strip(),
            "start": match.start(),
        })

    return chapters


def chapter_for_offset(char_offset: int, chapters):
    current = None
    for chapter in chapters:
        if chapter["start"] <= char_offset:
            current = chapter
        else:
            break
    return current


def split_article_block_into_title_and_body(block: str):
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, None, None

    article_heading = lines[0]
    m = RE_ARTICLE_HEADING.match(article_heading)
    if not m:
        return None, None, None

    article_number = m.group(1)
    rest = lines[1:]
    if not rest:
        return article_number, None, ""

    title_lines = [rest[0]]
    idx = 1

    while idx < len(rest):
        line = rest[idx]
        if should_continue_title(title_lines[-1], line):
            title_lines.append(line)
            idx += 1
        else:
            break

    article_title = normalize_block_text(" ".join(title_lines)).strip()
    body_lines = rest[idx:]

    filtered_body = []
    for line in body_lines:
        if is_heading_line(line):
            break
        filtered_body.append(line)

    body = "\n".join(filtered_body).strip()

    if article_number == "19" and body.lower().startswith("processing "):
        article_title = f"{article_title} processing".strip()
        body = body[len("processing "):].strip()

    article_title = repair_known_phrase_defects(repair_broken_words(article_title))
    body = repair_known_phrase_defects(repair_broken_words(body))

    return article_number, article_title, body


def parse_articles(operative_text: str, operative_start_offset: int, page_offsets):
    article_matches = list(RE_ARTICLE_HEADING.finditer(operative_text))
    chapters = parse_chapters(operative_text)
    articles = []

    for i, match in enumerate(article_matches):
        start = match.start()
        end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(operative_text)

        block = operative_text[start:end].strip()
        article_number, article_title, body = split_article_block_into_title_and_body(block)

        if not article_number or not article_title:
            continue

        chapter = chapter_for_offset(start, chapters)
        abs_start = operative_start_offset + start
        abs_end = operative_start_offset + end

        articles.append({
            "article_number": article_number,
            "article_title": article_title,
            "chapter_number": chapter["chapter_number"] if chapter else None,
            "chapter_number_int": chapter["chapter_number_int"] if chapter else None,
            "chapter_title": chapter["chapter_title"] if chapter else None,
            "body": body,
            "page_start": char_offset_to_page(abs_start, page_offsets),
            "page_end": char_offset_to_page(abs_end, page_offsets),
        })

    return articles


# ============================================================
# Paragraph extraction / splitting
# ============================================================

def parse_top_level_paragraphs(body: str):
    matches = list(RE_TOP_LEVEL_PARA.finditer(body))
    paragraphs = []

    if matches:
        for i, match in enumerate(matches):
            para_num = match.group(1) or match.group(2)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            text = normalize_block_text(body[start:end].strip())
            if text:
                paragraphs.append({
                    "top_ref": para_num,
                    "text": text,
                })
    else:
        text = normalize_block_text(body)
        if text:
            paragraphs.append({
                "top_ref": None,
                "text": text,
            })

    return paragraphs


def should_split_by_true_subpoints(text: str) -> bool:
    matches = find_true_lettered_subpoint_matches(text)
    if len(matches) < 2:
        return False

    intro = text[:matches[0].start()].strip()
    if ":" in intro:
        return True
    if RE_SUBPOINT_INTRO.search(intro):
        return True
    return True


def parse_true_lettered_units(text: str):
    matches = find_true_lettered_subpoint_matches(text)
    if len(matches) < 2:
        return None

    intro = text[:matches[0].start()].strip()
    units = []

    for i, match in enumerate(matches):
        letter = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        piece = text[start:end].strip()

        if i == 0 and intro:
            piece = f"{intro} {piece}"

        piece = normalize_block_text(piece)
        if piece:
            units.append({
                "letter": letter,
                "content": piece,
            })

    return units if units else None


def rebalance_small_tail_groups(groups):
    if len(groups) < 2:
        return groups

    last_wc = word_count(groups[-1]["content"])
    prev_wc = word_count(groups[-2]["content"])

    if last_wc < MIN_LAST_GROUP_WORDS and prev_wc + last_wc <= SOFT_MAX_WORDS_PER_CHUNK:
        groups[-2]["content"] = f"{groups[-2]['content']} {groups[-1]['content']}".strip()
        groups[-2]["letters_end"] = groups[-1]["letters_end"]
        groups[-2]["subpoint_range"] = (
            groups[-2]["letters_start"]
            if groups[-2]["letters_start"] == groups[-2]["letters_end"]
            else f"{groups[-2]['letters_start']}-{groups[-2]['letters_end']}"
        )
        groups.pop()

    return groups


def group_lettered_units(top_ref: str | None, units):
    groups = []
    current_units = []
    current_words = 0
    current_letters = []

    for unit in units:
        wc = word_count(unit["content"])

        if not current_units:
            current_units = [unit["content"]]
            current_words = wc
            current_letters = [unit["letter"]]
            continue

        if (
            current_words + wc <= TARGET_MAX_WORDS_PER_CHUNK
            and len(current_units) < MAX_SUBPOINTS_PER_GROUP
        ):
            current_units.append(unit["content"])
            current_words += wc
            current_letters.append(unit["letter"])
            continue

        if current_words < 55 and current_words + wc <= SOFT_MAX_WORDS_PER_CHUNK:
            current_units.append(unit["content"])
            current_words += wc
            current_letters.append(unit["letter"])
            continue

        groups.append({
            "paragraph_ref": top_ref,
            "subpoint_range": current_letters[0] if len(current_letters) == 1 else f"{current_letters[0]}-{current_letters[-1]}",
            "letters_start": current_letters[0],
            "letters_end": current_letters[-1],
            "content": " ".join(current_units).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })

        current_units = [unit["content"]]
        current_words = wc
        current_letters = [unit["letter"]]

    if current_units:
        groups.append({
            "paragraph_ref": top_ref,
            "subpoint_range": current_letters[0] if len(current_letters) == 1 else f"{current_letters[0]}-{current_letters[-1]}",
            "letters_start": current_letters[0],
            "letters_end": current_letters[-1],
            "content": " ".join(current_units).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })

    return rebalance_small_tail_groups(groups)


def semicolon_units(text: str):
    parts = re.findall(r"[^;]+(?:;|$)", text)
    units = [normalize_block_text(p.strip()) for p in parts if p.strip()]
    return [u for u in units if u]


def should_split_by_semicolon_units(text: str) -> bool:
    if text.count(";") < 3:
        return False
    if ":" not in text and "inter alia" not in text.lower():
        return False
    return True


def group_units_without_subpoints(top_ref: str | None, units):
    groups = []
    current = []
    current_words = 0

    for unit in units:
        wc = word_count(unit)

        if not current:
            current = [unit]
            current_words = wc
            continue

        if current_words + wc <= TARGET_MAX_WORDS_PER_CHUNK:
            current.append(unit)
            current_words += wc
            continue

        if boundary_is_unsafe(current[-1], unit) and current_words + wc <= SOFT_MAX_WORDS_PER_CHUNK:
            current.append(unit)
            current_words += wc
            continue

        groups.append({
            "paragraph_ref": top_ref,
            "subpoint_range": None,
            "content": " ".join(current).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })
        current = [unit]
        current_words = wc

    if current:
        groups.append({
            "paragraph_ref": top_ref,
            "subpoint_range": None,
            "content": " ".join(current).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })

    if len(groups) >= 2:
        last_wc = word_count(groups[-1]["content"])
        prev_wc = word_count(groups[-2]["content"])
        if last_wc < MIN_LAST_GROUP_WORDS and prev_wc + last_wc <= SOFT_MAX_WORDS_PER_CHUNK:
            groups[-2]["content"] = f"{groups[-2]['content']} {groups[-1]['content']}".strip()
            groups.pop()

    return groups


def split_text_by_sentences_safely(text: str, paragraph_ref: str | None):
    sentences = [s.strip() for s in RE_SENTENCE_SPLIT.split(text) if s.strip()]

    if not sentences:
        return [{
            "paragraph_ref": paragraph_ref,
            "subpoint_range": None,
            "content": text,
            "mergeable": False,
            "numeric_ref": None,
        }]

    result = []
    current = [sentences[0]]
    current_words = word_count(sentences[0])

    for sentence in sentences[1:]:
        wc = word_count(sentence)
        proposed = current_words + wc

        if proposed <= TARGET_MAX_WORDS_PER_CHUNK:
            current.append(sentence)
            current_words = proposed
            continue

        if boundary_is_unsafe(current[-1], sentence) and proposed <= SOFT_MAX_WORDS_PER_CHUNK:
            current.append(sentence)
            current_words = proposed
            continue

        result.append({
            "paragraph_ref": paragraph_ref,
            "subpoint_range": None,
            "content": " ".join(current).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })
        current = [sentence]
        current_words = wc

    if current:
        result.append({
            "paragraph_ref": paragraph_ref,
            "subpoint_range": None,
            "content": " ".join(current).strip(),
            "mergeable": False,
            "numeric_ref": None,
        })

    merged = []
    for seg in result:
        if (
            merged
            and boundary_is_unsafe(merged[-1]["content"], seg["content"])
            and word_count(merged[-1]["content"]) + word_count(seg["content"]) <= SOFT_MAX_WORDS_PER_CHUNK
        ):
            merged[-1]["content"] = f"{merged[-1]['content']} {seg['content']}".strip()
        else:
            merged.append(seg)

    return merged


def paragraph_to_segments(paragraph):
    top_ref = paragraph["top_ref"]
    text = paragraph["text"]
    wc = word_count(text)
    numeric_ref = int(top_ref) if top_ref and top_ref.isdigit() else None

    if wc <= TARGET_MAX_WORDS_PER_CHUNK:
        return [{
            "paragraph_ref": top_ref,
            "subpoint_range": None,
            "content": text,
            "mergeable": numeric_ref is not None,
            "numeric_ref": numeric_ref,
        }]

    if should_split_by_true_subpoints(text):
        units = parse_true_lettered_units(text)
        if units:
            return group_lettered_units(top_ref, units)

    if should_split_by_semicolon_units(text):
        units = semicolon_units(text)
        if len(units) >= 3:
            return group_units_without_subpoints(top_ref, units)

    if wc <= SOFT_MAX_WORDS_PER_CHUNK:
        return [{
            "paragraph_ref": top_ref,
            "subpoint_range": None,
            "content": text,
            "mergeable": False,
            "numeric_ref": None,
        }]

    return split_text_by_sentences_safely(text, top_ref)


# ============================================================
# Chunk assembly
# ============================================================

def can_merge_top_level(acc, nxt):
    if not acc or not nxt:
        return False
    if not acc["mergeable"] or not nxt["mergeable"]:
        return False
    if acc["numeric_ref"] is None or nxt["numeric_ref"] is None:
        return False
    if nxt["numeric_ref"] != acc["range_end"] + 1:
        return False
    if acc["top_level_count"] >= MAX_TOP_LEVEL_PARAGRAPHS_PER_CHUNK:
        return False
    if acc["word_count"] + word_count(nxt["content"]) > TARGET_MAX_WORDS_PER_CHUNK:
        return False
    return True


def finalize_grouped_segments(grouped, article):
    finalized = []
    total = len(grouped)

    for idx, seg in enumerate(grouped, start=1):
        content = normalize_block_text(seg["content"])
        if not content:
            continue

        finalized.append({
            "article_number": article["article_number"],
            "article_title": article["article_title"],
            "chapter_number": article["chapter_number"],
            "chapter_number_int": article["chapter_number_int"],
            "chapter_title": article["chapter_title"],
            "paragraph_ref": seg["paragraph_ref"],
            "subpoint_range": seg.get("subpoint_range"),
            "subchunk_index": idx,
            "subchunk_count": total,
            "content": content,
            "page_start": article["page_start"],
            "page_end": article["page_end"],
        })

    return finalized


def build_article_chunks(article):
    paragraphs = parse_top_level_paragraphs(article["body"])
    segments = []

    for paragraph in paragraphs:
        segments.extend(paragraph_to_segments(paragraph))

    grouped = []
    acc = None

    for seg in segments:
        seg_wc = word_count(seg["content"])

        if acc is None:
            acc = {
                "contents": [seg["content"]],
                "paragraph_ref": seg["paragraph_ref"],
                "subpoint_range": seg.get("subpoint_range"),
                "range_start": seg["numeric_ref"],
                "range_end": seg["numeric_ref"],
                "numeric_ref": seg["numeric_ref"],
                "mergeable": seg["mergeable"],
                "word_count": seg_wc,
                "top_level_count": 1 if seg["mergeable"] and seg["numeric_ref"] is not None else 0,
            }
            continue

        if can_merge_top_level(acc, seg):
            acc["contents"].append(seg["content"])
            acc["range_end"] = seg["numeric_ref"]
            acc["word_count"] += seg_wc
            acc["top_level_count"] += 1

            if acc["range_start"] == acc["range_end"]:
                acc["paragraph_ref"] = str(acc["range_start"])
            else:
                acc["paragraph_ref"] = f"{acc['range_start']}-{acc['range_end']}"
        else:
            grouped.append({
                "paragraph_ref": acc["paragraph_ref"],
                "subpoint_range": acc["subpoint_range"],
                "content": " ".join(acc["contents"]).strip(),
            })
            acc = {
                "contents": [seg["content"]],
                "paragraph_ref": seg["paragraph_ref"],
                "subpoint_range": seg.get("subpoint_range"),
                "range_start": seg["numeric_ref"],
                "range_end": seg["numeric_ref"],
                "numeric_ref": seg["numeric_ref"],
                "mergeable": seg["mergeable"],
                "word_count": seg_wc,
                "top_level_count": 1 if seg["mergeable"] and seg["numeric_ref"] is not None else 0,
            }

    if acc is not None:
        grouped.append({
            "paragraph_ref": acc["paragraph_ref"],
            "subpoint_range": acc["subpoint_range"],
            "content": " ".join(acc["contents"]).strip(),
        })

    return finalize_grouped_segments(grouped, article)


def build_chunks(articles, source_pdf: str):
    chunks = []

    for article in articles:
        article_chunks = build_article_chunks(article)

        for chunk in article_chunks:
            content = chunk["content"].strip()
            if not content:
                continue

            chunk_id = make_chunk_id(
                article_number=chunk["article_number"],
                paragraph_ref=chunk["paragraph_ref"],
                content=content,
                subpoint_range=chunk.get("subpoint_range"),
                subchunk_index=chunk.get("subchunk_index"),
            )

            chunks.append({
                "chunk_id": chunk_id,
                "article_number": chunk["article_number"],
                "article_title": chunk["article_title"],
                "chapter_number": chunk["chapter_number"],
                "chapter_number_int": chunk["chapter_number_int"],
                "chapter_title": chunk["chapter_title"],
                "paragraph_ref": chunk["paragraph_ref"],
                "subpoint_range": chunk.get("subpoint_range"),
                "subchunk_index": chunk["subchunk_index"],
                "subchunk_count": chunk["subchunk_count"],
                "content": content,
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "word_count": word_count(content),
                "source_pdf": source_pdf,
            })

    return chunks


# ============================================================
# Output
# ============================================================

def write_jsonl(chunks, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def print_summary(chunks):
    by_article = {}
    over_target = []
    over_soft = []
    over_hard = []

    for chunk in chunks:
        by_article.setdefault(chunk["article_number"], 0)
        by_article[chunk["article_number"]] += 1

        wc = chunk["word_count"]
        if wc > TARGET_MAX_WORDS_PER_CHUNK:
            over_target.append((chunk["chunk_id"], wc))
        if wc > SOFT_MAX_WORDS_PER_CHUNK:
            over_soft.append((chunk["chunk_id"], wc))
        if wc > HARD_MAX_WORDS_PER_CHUNK:
            over_hard.append((chunk["chunk_id"], wc))

    print(f"Total chunks: {len(chunks)}")
    print(f"Total articles covered: {len(by_article)}")
    print(f"Target max words per chunk: {TARGET_MAX_WORDS_PER_CHUNK}")
    print(f"Soft max words per chunk: {SOFT_MAX_WORDS_PER_CHUNK}")
    print(f"Hard max words per chunk: {HARD_MAX_WORDS_PER_CHUNK}")

    if over_target:
        print("Chunks over target max:")
        for chunk_id, wc in over_target[:20]:
            print(f"  - {chunk_id}: {wc} words")
    else:
        print("No chunks over target max.")

    if over_soft:
        print("Chunks over soft max:")
        for chunk_id, wc in over_soft[:20]:
            print(f"  - {chunk_id}: {wc} words")
    else:
        print("No chunks over soft max.")

    if over_hard:
        print("Chunks over hard max:")
        for chunk_id, wc in over_hard[:20]:
            print(f"  - {chunk_id}: {wc} words")
    else:
        print("No chunks over hard max.")

    if chunks:
        print("\nExample chunk:")
        print(json.dumps(chunks[0], indent=2, ensure_ascii=False))


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python preprocess_gdpr.py /path/to/CELEX_32016R0679_EN_TXT.pdf [output.jsonl]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "gdpr_chunks.jsonl"
    pdf_name = Path(pdf_path).name

    pages = extract_pages(pdf_path)
    combined_text, page_offsets = build_combined_text_with_offsets(pages)
    operative_start, _, operative_text = extract_operative_window(combined_text)

    articles = parse_articles(
        operative_text=operative_text,
        operative_start_offset=operative_start,
        page_offsets=page_offsets,
    )

    chunks = build_chunks(
        articles=articles,
        source_pdf=pdf_name,
    )

    write_jsonl(chunks, output_path)
    print_summary(chunks)


if __name__ == "__main__":
    main()