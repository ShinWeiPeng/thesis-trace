"""Opt-in regression tests at the development probe's bytes/result boundary.

No database, network fetch, provider call, or production parser is exercised.
An explicitly selected isolated library and namespace capability are required.
"""

import io
import os
from pathlib import Path

import pytest

from source_extraction_probe import run_isolated


@pytest.fixture
def library():
    configured = os.environ.get("THESIS_TRACE_EXTRACTION_PROTOTYPE_LIBRARY")
    if not configured:
        pytest.skip("opt-in prototype: select an isolated pypdf library first")
    selected = Path(configured).resolve()
    assert (selected / "pypdf").is_dir(), "selected pypdf library is unavailable"
    return selected


@pytest.mark.parametrize(
    "markup, expected",
    [
        ("<p>單位：百萬元；未經查核。</p>", "單位：百萬元；未經查核。"),
        ("<h1>Synthetic heading</h1>", "Synthetic heading"),
        (
            "<body><p>單位：百萬元；未經查核。</p></body>",
            "單位：百萬元；未經查核。",
        ),
    ],
)
def test_html_preserves_visible_blocks_without_requiring_a_wrapper(
    library, markup, expected
):
    result = run_isolated(markup.encode("utf-8"), "html", library, 128)

    assert result["child_ready"] and result["child_reaped"], result
    assert result["status"] == "readable", result
    assert [fragment["text"] for fragment in result["fragments"]] == [expected]


def test_html_retains_heading_table_and_unit_note_in_source_order(library):
    markup = (
        "<h1>合成邊界資料</h1><table><tr><th>年份</th><th>金額</th></tr>"
        "<tr><td>2026</td><td>123</td></tr></table>"
        "<p>單位：百萬元；未經查核。</p>"
    )
    result = run_isolated(markup.encode("utf-8"), "html", library, 128)

    assert result["status"] == "readable", result
    assert [fragment["text"] for fragment in result["fragments"]] == [
        "合成邊界資料",
        "年份 金額",
        "2026 123",
        "單位：百萬元；未經查核。",
    ]
    assert result["document_verified"] is False


@pytest.mark.parametrize(
    "excluded",
    [
        "<p hidden>EXCLUDED</p>",
        '<div aria-hidden="true"><p>EXCLUDED</p></div>',
        "<nav><p>EXCLUDED</p></nav>",
        "<script>EXCLUDED</script>",
    ],
)
def test_html_still_excludes_hidden_or_non_body_content(library, excluded):
    markup = excluded + "<p>Visible evidence</p>"
    result = run_isolated(markup.encode("utf-8"), "html", library, 128)

    assert result["status"] == "readable", result
    assert [fragment["text"] for fragment in result["fragments"]] == [
        "Visible evidence"
    ]


@pytest.fixture
def mixed_pdf(library, monkeypatch):
    monkeypatch.syspath_prepend(str(library))
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
    )

    writer = PdfWriter()
    text_page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    text_page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    text_stream = DecodedStreamObject()
    text_stream.set_data(b"BT /F1 12 Tf 10 100 Td (SYNTHETIC text page) Tj ET")
    text_page[NameObject("/Contents")] = writer._add_object(text_stream)

    image_page = writer.add_blank_page(width=200, height=200)
    image = DecodedStreamObject()
    image.set_data(b"\x80")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Im1"): writer._add_object(image)}
            )
        }
    )
    image_stream = DecodedStreamObject()
    image_stream.set_data(b"q 100 0 0 100 0 0 cm /Im1 Do Q")
    image_page[NameObject("/Contents")] = writer._add_object(image_stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["pdf", "pdf-compact", "pdf-plain"])
def test_pdf_reports_missing_text_page_instead_of_silent_completeness(
    library, mixed_pdf, kind
):
    result = run_isolated(mixed_pdf, kind, library, 128)

    assert result["child_ready"] and result["child_reaped"], result
    assert result["status"] == "readable", result
    assert [fragment["text"] for fragment in result["fragments"]] == [
        "SYNTHETIC text page"
    ]
    assert result["selection_incomplete"] is True, result
    assert result["total_pages"] == 2
    assert result["pages_without_text"] == [2]
    assert result["document_verified"] is False


@pytest.mark.parametrize("kind", ["pdf", "pdf-compact", "pdf-plain"])
@pytest.mark.parametrize(
    "page_kind, expected_status, expected_missing",
    [("text", "readable", []), ("image", "no_text", [1]), ("blank", "no_text", [1])],
)
def test_pdf_coverage_distinguishes_readable_text_from_unextracted_pages(
    library, mixed_pdf, kind, page_kind, expected_status, expected_missing
):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    if page_kind == "blank":
        writer.add_blank_page(width=200, height=200)
    else:
        reader = PdfReader(io.BytesIO(mixed_pdf))
        writer.add_page(reader.pages[0 if page_kind == "text" else 1])
    output = io.BytesIO()
    writer.write(output)

    result = run_isolated(output.getvalue(), kind, library, 128)

    assert result["child_ready"] and result["child_reaped"], result
    assert result["status"] == expected_status, result
    assert result["total_pages"] == 1
    assert result["pages_without_text"] == expected_missing
    assert result["selection_incomplete"] is (page_kind != "text")
    assert result["document_verified"] is False
