"""
Pytest Word report generator.

When the backend test suite runs, this plugin writes a detailed Word-compatible
.docx document listing every collected test case, its purpose, result, and
duration. It intentionally uses only the Python standard library so the Docker
test command does not need extra packages.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


REPORTS_DIR = Path("app/tests/reports")
COMBINED_REPORT_PATH = REPORTS_DIR / "testcase_documentation.docx"
COMBINED_MANIFEST_PATH = REPORTS_DIR / "testcase_documentation.manifest.json"
MODULES_DIR = REPORTS_DIR / "modules"
_DOCS: dict[str, "TestCaseDoc"] = {}


@dataclass
class TestCaseDoc:
    nodeid: str
    file_path: str
    function_name: str
    class_name: str | None
    module_title: str
    purpose: str
    markers: list[str] = field(default_factory=list)
    result: str = "Not run"
    duration_s: float = 0.0
    failure_summary: str = ""


def pytest_configure(config: Any) -> None:
    global _DOCS
    _DOCS = {}
    config._da_testcase_docs = {}
    config._da_report_started_at = datetime.now(timezone.utc)


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    global _DOCS
    docs: dict[str, TestCaseDoc] = {}
    for item in items:
        module = inspect.getmodule(item.obj)
        module_title = _first_doc_line(module.__doc__ if module else "") or Path(
            str(item.fspath)
        ).stem
        purpose = inspect.getdoc(item.obj) or _humanize_test_name(item.name)
        class_name = item.cls.__name__ if getattr(item, "cls", None) else None
        markers = sorted({marker.name for marker in item.iter_markers()})

        docs[item.nodeid] = TestCaseDoc(
            nodeid=item.nodeid,
            file_path=str(item.fspath),
            function_name=item.name,
            class_name=class_name,
            module_title=module_title,
            purpose=purpose,
            markers=markers,
        )

    config._da_testcase_docs = docs
    _DOCS = docs


def pytest_runtest_logreport(report: Any) -> None:
    doc = _DOCS.get(report.nodeid)
    if not doc:
        return

    doc.duration_s += getattr(report, "duration", 0.0) or 0.0

    if report.when == "call":
        doc.result = _result_label(report)
    elif report.failed and doc.result == "Not run":
        doc.result = f"{report.when.capitalize()} failed"

    if report.failed:
        doc.failure_summary = _clean_failure(str(getattr(report, "longrepr", "")))
    elif report.skipped and doc.result == "Not run":
        doc.result = "Skipped"
        doc.failure_summary = _clean_failure(str(getattr(report, "longrepr", "")))


def _compute_fingerprint(docs: dict[str, "TestCaseDoc"]) -> str:
    entries = sorted(
        f"{d.nodeid}|{d.purpose}|{','.join(d.markers)}"
        for d in docs.values()
    )
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def _load_manifest(manifest_path: Path) -> dict:
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(manifest_path: Path, fingerprint: str, nodeids: list[str]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"fingerprint": fingerprint, "nodeids": sorted(nodeids)}, indent=2),
        encoding="utf-8",
    )


def _diff_reason(manifest: dict, curr_ids: set[str]) -> str:
    prev_ids = set(manifest.get("nodeids", []))
    added = curr_ids - prev_ids
    removed = prev_ids - curr_ids
    parts = []
    if added:
        parts.append(f"{len(added)} new test(s)")
    if removed:
        parts.append(f"{len(removed)} removed test(s)")
    if not parts:
        parts.append("test(s) updated")
    return ", ".join(parts)


def _maybe_write_report(
    output_path: Path,
    manifest_path: Path,
    docs: dict[str, "TestCaseDoc"],
    started_at: Any,
    exitstatus: int,
    label: str,
    terminal: Any,
) -> None:
    fingerprint = _compute_fingerprint(docs)
    manifest = _load_manifest(manifest_path)

    if output_path.exists() and manifest.get("fingerprint") == fingerprint:
        if terminal:
            terminal.write_line(f"  [unchanged] {label}: {output_path}")
        return

    doc_title = f"DroneArjuna — {label} Test Case Documentation"
    _write_docx(output_path, list(docs.values()), started_at, exitstatus, title=doc_title)
    _save_manifest(manifest_path, fingerprint, list(docs.keys()))

    if terminal:
        if manifest.get("fingerprint"):
            reason = _diff_reason(manifest, set(docs.keys()))
            terminal.write_line(f"  [updated — {reason}] {label}: {output_path}")
        else:
            terminal.write_line(f"  [generated] {label}: {output_path}")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    docs: dict[str, TestCaseDoc] = getattr(session.config, "_da_testcase_docs", {})
    started_at = getattr(session.config, "_da_report_started_at", None)

    if not docs:
        return

    # Group tests by source file
    grouped: dict[str, dict[str, TestCaseDoc]] = {}
    for nodeid, doc in docs.items():
        grouped.setdefault(doc.file_path, {})[nodeid] = doc

    if terminal:
        terminal.write_line("\n--- DroneArjuna test case documentation ---")

    # Per-module individual reports
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    for file_path, module_docs in sorted(grouped.items()):
        stem = Path(file_path).stem  # e.g. "test_auth"
        module_title = next(iter(module_docs.values())).module_title
        out = MODULES_DIR / f"{stem}_documentation.docx"
        mf = MODULES_DIR / f"{stem}_documentation.manifest.json"
        _maybe_write_report(out, mf, module_docs, started_at, exitstatus, module_title, terminal)

    # Combined report: only regenerate when running more than one module.
    # Single-file runs leave the existing combined report untouched so it
    # always reflects the last full test suite run.
    if len(grouped) > 1:
        _maybe_write_report(
            COMBINED_REPORT_PATH,
            COMBINED_MANIFEST_PATH,
            docs,
            started_at,
            exitstatus,
            "Combined (all modules)",
            terminal,
        )
    elif terminal:
        if COMBINED_REPORT_PATH.exists():
            terminal.write_line(
                f"  [untouched] Combined (all modules): {COMBINED_REPORT_PATH}"
            )
        else:
            terminal.write_line(
                "  [skipped] Combined report not yet created — run the full test suite to generate it."
            )

    if terminal:
        terminal.write_line("-------------------------------------------")


def _result_label(report: Any) -> str:
    if report.passed:
        return "Passed"
    if report.failed:
        return "Failed"
    if report.skipped:
        return "Skipped"
    return str(report.outcome).title()


def _first_doc_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in inspect.cleandoc(doc).splitlines():
        line = line.strip(" =")
        if line:
            return line
    return ""


def _humanize_test_name(name: str) -> str:
    name = re.sub(r"\[.*\]$", "", name)
    name = name.removeprefix("test_").replace("_", " ")
    return name[:1].upper() + name[1:]


def _clean_failure(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:12])


def _write_docx(
    output_path: Path,
    tests: list[TestCaseDoc],
    started_at: datetime | None,
    exitstatus: int,
    title: str = "DroneArjuna Backend Test Case Documentation",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tests = sorted(tests, key=lambda t: (t.file_path, t.nodeid))
    generated_at = datetime.now(timezone.utc)
    started_text = started_at.isoformat(timespec="seconds") if started_at else "Unknown"

    total = len(tests)
    passed = sum(1 for t in tests if t.result == "Passed")
    failed = sum(1 for t in tests if "Failed" in t.result)
    skipped = sum(1 for t in tests if t.result == "Skipped")
    not_run = sum(1 for t in tests if t.result == "Not run")

    body: list[str] = []
    body.append(_paragraph(title, "Title"))
    body.append(_paragraph(f"Generated at: {generated_at.isoformat(timespec='seconds')}"))
    body.append(_paragraph(f"Test session started: {started_text}"))
    body.append(_paragraph(f"Pytest exit status: {exitstatus}"))
    body.append(_paragraph(""))
    body.append(_heading("Summary", level=1))
    body.append(
        _table(
            ["Metric", "Value"],
            [
                ["Total collected test cases", str(total)],
                ["Passed", str(passed)],
                ["Failed", str(failed)],
                ["Skipped", str(skipped)],
                ["Not run", str(not_run)],
            ],
        )
    )

    grouped: dict[str, list[TestCaseDoc]] = {}
    for test in tests:
        grouped.setdefault(test.file_path, []).append(test)

    body.append(_heading("Detailed Test Cases", level=1))
    for file_path, file_tests in grouped.items():
        module_title = file_tests[0].module_title
        body.append(_heading(module_title, level=2))
        body.append(_paragraph(f"Source file: {file_path}"))
        rows = []
        for index, test in enumerate(file_tests, start=1):
            rows.append(
                [
                    str(index),
                    test.function_name,
                    test.purpose,
                    test.result,
                    f"{test.duration_s:.3f}",
                    ", ".join(test.markers) if test.markers else "-",
                    test.failure_summary or "-",
                ]
            )
        body.append(
            _table(
                [
                    "#",
                    "Test case",
                    "Functionality / expected behavior",
                    "Result",
                    "Duration (s)",
                    "Markers",
                    "Failure / notes",
                ],
                rows,
            )
        )

    document_xml = _document_xml("".join(body))
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml())
        docx.writestr("_rels/.rels", _rels_xml())
        docx.writestr("word/_rels/document.xml.rels", _document_rels_xml())
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", _styles_xml())


def _document_xml(body_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body_xml}
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/></w:sectPr>
  </w:body>
</w:document>"""


def _paragraph(text: str, style: str | None = None) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{style_xml}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _heading(text: str, level: int) -> str:
    return _paragraph(text, f"Heading{level}")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    all_rows = [headers] + rows
    table_rows = []
    for row_index, row in enumerate(all_rows):
        cells = []
        for value in row:
            bold_start = "<w:rPr><w:b/></w:rPr>" if row_index == 0 else ""
            text = escape(str(value)).replace("\n", " | ")
            cells.append(
                "<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>"
                f"<w:p><w:r>{bold_start}<w:t>{text}</w:t></w:r></w:p></w:tc>"
            )
        table_rows.append(f"<w:tr>{''.join(cells)}</w:tr>")

    return (
        "<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/>"
        "<w:tblW w:w=\"0\" w:type=\"auto\"/></w:tblPr>"
        f"{''.join(table_rows)}</w:tbl>"
    )


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""


def _rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _document_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/><w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/><w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""
