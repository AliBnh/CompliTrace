from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser import (
    ParsedSection,
    _detect_boilerplate_lines,
    is_heading,
    is_noise_line,
    split_inline_numbered_chunks,
    split_numbered_heading_and_body,
)


def test_heading_detection():
    assert is_heading("Data Retention") is True
    assert is_heading("This is a full sentence.") is False
    assert is_heading("Page 1") is False
    assert is_heading("Subject/Ser") is False
    assert is_heading("1. Introduction") is True


def test_parsed_section_dataclass():
    section = ParsedSection(1, "Intro", "Body", 1, 1)
    assert section.section_title == "Intro"


def test_noise_line_detection():
    assert is_noise_line(r"Y:\\Policies\\archive\\doc.pdf")
    assert is_noise_line("Page 3")
    assert not is_noise_line("Data Storage")


def test_split_inline_numbered_chunks():
    line = "5.5 Compliance and Protective Grounds 6. Cookies, Similar Technologies, and Digital Tracking"
    parts = split_inline_numbered_chunks(line)
    assert len(parts) == 2
    assert parts[0].startswith("5.5 Compliance")
    assert parts[1].startswith("6. Cookies")


def test_split_numbered_heading_and_body():
    line = "6. Cookies, Similar Technologies, and Digital Tracking We use cookies and related tools."
    heading, body = split_numbered_heading_and_body(line) or ("", "")
    assert heading.startswith("6. Cookies")
    assert body.startswith("We use cookies")


def test_split_numbered_heading_and_body_returns_none_when_no_body():
    line = "6. Cookies, Similar Technologies, and Digital Tracking"
    assert split_numbered_heading_and_body(line) is None


def test_detect_boilerplate_lines_generic():
    pages = [
        (1, ["Confidential", "Data Retention"]),
        (2, ["Confidential", "Access Rights"]),
        (3, ["Confidential", "Data Minimization"]),
    ]
    found = _detect_boilerplate_lines(pages)
    assert "confidential" in found
