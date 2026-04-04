from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser import ParsedSection, is_heading


def test_heading_detection():
    assert is_heading("Data Retention") is True
    assert is_heading("This is a full sentence.") is False


def test_parsed_section_dataclass():
    section = ParsedSection(1, "Intro", "Body", 1, 1)
    assert section.section_title == "Intro"
