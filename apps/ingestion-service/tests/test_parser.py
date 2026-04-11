from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser import (
    ParsedSection,
    _detect_boilerplate_lines,
    _refine_sections,
    _remove_boilerplate_phrases,
    is_heading,
    is_noise_line,
    parse_pdf_into_sections,
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


def test_split_numbered_heading_and_body_returns_none_for_long_sentence_without_clear_boundary():
    line = "4.1 The Company primarily relies on user consent inferred from interactions with our services."
    heading, body = split_numbered_heading_and_body(line) or ("", "")
    assert heading == "4.1"
    assert body.startswith("The Company primarily relies")


def test_split_numbered_heading_and_body_prefers_colon_delimited_subheading():
    line = (
        "2.1 Identifiers: We collect full name, email address, phone number, and session tokens "
        "used to authenticate and manage access to services."
    )
    heading, body = split_numbered_heading_and_body(line) or ("", "")
    assert heading == "2.1 Identifiers"
    assert body.startswith("We collect full name")


def test_detect_boilerplate_lines_generic():
    pages = [
        (1, ["Confidential", "Data Retention"]),
        (2, ["Confidential", "Access Rights"]),
        (3, ["Confidential", "Data Minimization"]),
    ]
    found = _detect_boilerplate_lines(pages)
    assert "confidential" in found


def test_remove_boilerplate_phrases_inside_content():
    text = "This is valid text. Confidential - More valid text."
    cleaned = _remove_boilerplate_phrases(text, {"confidential"})
    assert "Confidential" not in cleaned
    assert "More valid text" in cleaned


def test_refine_sections_splits_embedded_subheading():
    sections = [
        ParsedSection(
            section_order=1,
            section_title="5.5 Compliance and Protective Grounds",
            content=(
                "We may process personal data as required. "
                "6.1 Tracking Technologies We Use "
                "We use cookies and related technologies."
            ),
            page_start=6,
            page_end=6,
        )
    ]
    refined = _refine_sections(sections, set())
    assert len(refined) == 2
    assert refined[1].section_title.startswith("6.1 Tracking Technologies")


def test_refine_sections_splits_embedded_top_level_heading():
    sections = [
        ParsedSection(
            section_order=1,
            section_title="6.4 Do Not Track and Similar Signals",
            content=(
                "Preference signals may be ignored in some environments. "
                "7. Sharing, Disclosure, and Downstream Use "
                "We disclose data to service providers."
            ),
            page_start=6,
            page_end=6,
        )
    ]
    refined = _refine_sections(sections, set())
    assert len(refined) == 2
    assert refined[1].section_title.startswith("7")


def test_refine_sections_fixes_weak_title_when_numbered_body_starts():
    sections = [
        ParsedSection(
            section_order=1,
            section_title="We Process",
            content="2.1 Account, Identity, and Registration Data We collect account data for operations.",
            page_start=2,
            page_end=3,
        )
    ]
    refined = _refine_sections(sections, set())
    assert refined[0].section_title == "2.1"
    assert refined[0].content.startswith("Account, Identity")


def test_parse_pdf_into_sections_does_not_merge_parent_and_child_titles(monkeypatch):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self, _mode: str) -> str:
            return self._text

    class _FakeDoc(list):
        pass

    class _FakeFitz:
        @staticmethod
        def open(_path: str):
            return _FakeDoc(
                [
                    _FakePage(
                        "\n".join(
                            [
                                "1. Introduction and Scope",
                                "1.1 Purpose of this Policy",
                                "This Privacy Policy describes processing practices.",
                            ]
                        )
                    )
                ]
            )

    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)
    sections = parse_pdf_into_sections("dummy.pdf")
    assert len(sections) == 2
    assert sections[0].section_title == "1. Introduction and Scope"
    assert sections[0].content == "1. Introduction and Scope"
    assert sections[1].section_title == "1.1 Purpose of this Policy"


def test_parse_pdf_into_sections_keeps_decimal_subheading_without_extra_dot(monkeypatch):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self, _mode: str) -> str:
            return self._text

    class _FakeDoc(list):
        pass

    class _FakeFitz:
        @staticmethod
        def open(_path: str):
            return _FakeDoc(
                [
                    _FakePage(
                        "\n".join(
                            [
                                "2 Categories of Data Collected 2.1 Identifiers: We collect full name and email used to authenticate access.",
                            ]
                        )
                    )
                ]
            )

    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)
    sections = parse_pdf_into_sections("dummy.pdf")
    titles = [s.section_title for s in sections]
    assert "2.1 Identifiers" in titles
    assert "2.1. Identifiers" not in titles


def test_parse_pdf_into_sections_policy_sample_from_screenshot_keeps_titles_and_bodies(monkeypatch):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self, _mode: str) -> str:
            return self._text

    class _FakeDoc(list):
        pass

    class _FakeFitz:
        @staticmethod
        def open(_path: str):
            return _FakeDoc(
                [
                    _FakePage(
                        "\n".join(
                            [
                                "Open Data Synthesis, Inc.",
                                "Enterprise Privacy Policy",
                                "1. Introduction",
                                "1.1 Overview",
                                "This Privacy Policy describes categories of personal data processed.",
                                "2. Categories of Data Collected",
                                "2.1 Identifiers We collect full name, email address, phone number and organizational identifiers.",
                                "2.2 Technical Data This includes system logs, IP address metadata, browser type, and telemetry.",
                                "3. Information Processing",
                                "3.1 Service Delivery Personal data is processed to enable authentication and access management.",
                                "3.2 Analytics and Optimization Data is used to generate operational insights and improve experiences.",
                            ]
                        )
                    ),
                    _FakePage(
                        "\n".join(
                            [
                                "4. Legal Basis for Processing",
                                "4.1 The Company primarily relies on user consent where required",
                                "under local law.",
                                "5. Security Measures",
                                "5.1 The Company employs encryption protocols",
                                "and audit controls.",
                                "6. Data Subject Rights",
                                "6.1 Users may exercise rights of access, rectification,",
                                "erasure and portability.",
                                "13. Contact Information",
                                "13.1 For inquiries regarding this Privacy Policy",
                                "contact privacy@opendata.com.",
                            ]
                        )
                    ),
                ]
            )

    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)

    sections = parse_pdf_into_sections("dummy.pdf")
    titles = [s.section_title for s in sections]
    by_title = {s.section_title: s.content for s in sections}

    assert "Enterprise Privacy Policy" in titles
    assert "Open Data Synthesis, Inc." in by_title["Enterprise Privacy Policy"]
    assert "1. Introduction" in titles
    assert "2. Categories of Data Collected" in titles
    assert "3. Information Processing" in titles
    assert "4. Legal Basis for Processing" in titles
    assert "2.1 Identifiers" in titles
    assert "2.2 Technical Data" in titles
    assert "3.1 Service Delivery" in titles
    assert "3.2 Analytics and Optimization" in titles
    assert any(title == "4.1" or title.startswith("4.1 ") for title in titles)
    assert any(title == "13.1" or title.startswith("13.1 ") for title in titles)
    assert "5.1" in titles
    assert "6.1" in titles

    assert "We collect full name, email address" in by_title["2.1 Identifiers"]
    assert "This includes system logs" in by_title["2.2 Technical Data"]
    assert "processed to enable authentication and access management" in by_title["3.1 Service Delivery"]
    assert all(". ." not in title for title in titles)


def test_parse_pdf_header_preserves_company_first_line_and_metadata_line_breaks(monkeypatch):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self, _mode: str) -> str:
            return self._text

    class _FakeDoc(list):
        pass

    class _FakeFitz:
        @staticmethod
        def open(_path: str):
            return _FakeDoc(
                [
                    _FakePage(
                        "\n".join(
                            [
                                "Orion Data Systems, Inc.",
                                "Enterprise Privacy Policy",
                                "Effective Date: January 1, 2026 | Last Updated: January 1, 2026",
                                "Registered Address: 1200 Market Street, Suite 400, San Francisco, CA, USA",
                                "Contact: privacy@oriondata.com",
                                "1. Introduction",
                                "1.1 Overview Orion runs enterprise data services.",
                            ]
                        )
                    )
                ]
            )

    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)
    sections = parse_pdf_into_sections("dummy.pdf")
    assert sections[0].section_title == "Enterprise Privacy Policy"
    assert "Orion Data Systems, Inc." in sections[0].content
    assert "Effective Date: January 1, 2026" in sections[0].content
    assert "\n" in sections[0].content
    assert any(s.section_title == "1. Introduction" and s.content == "1. Introduction" for s in sections)
