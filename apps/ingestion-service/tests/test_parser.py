from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser import ParsedSection, is_heading, is_noise_line


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
    assert is_noise_line(r"Y:\\HM Policies & Procedures NEW\\GDPR\\Approved Policies\\GROUP Data Protection Policy_GDPR 2019.docx")
    assert is_noise_line("Page 3")
    assert not is_noise_line("Data Storage")
