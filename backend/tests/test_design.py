from mac.design import SECTIONS, facts, markdown_to_storage, page_title, render_page
from mac.spec import parse_spec
from mac.validate import execution_order

from .conftest import DEMO_SPEC, IAC, MCP

SPEC = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))
SHAS = {key: c * 40 for key, c in zip(sorted(SPEC.repos()), "abcd")}


def test_headings_paragraphs_and_lists():
    html = markdown_to_storage("## Overview\nLine one\nline two.\n\n- a\n- b\n\n1. first\n2. second\n### Detail\ntext")
    assert html == ("<h2>Overview</h2><p>Line one line two.</p><ul><li>a</li><li>b</li></ul>"
                    "<ol><li>first</li><li>second</li></ol><h3>Detail</h3><p>text</p>")


def test_inline_formatting():
    html = markdown_to_storage("A **bold** move, an *emphasis* and `code`. 2 * 3 * 4 stays.")
    assert html == "<p>A <strong>bold</strong> move, an <em>emphasis</em> and <code>code</code>. 2 * 3 * 4 stays.</p>"


def test_nothing_the_model_writes_becomes_markup():
    nasty = ('<script>alert(1)</script>\n<ac:structured-macro ac:name="html"/>\n'
             '[click](javascript:alert(1)) <a href="x">x</a> &amp; ok')
    html = markdown_to_storage(nasty)
    assert "<script" not in html and "<ac:" not in html and "<a " not in html
    assert "&lt;script&gt;" in html and "&lt;ac:structured-macro" in html and "&amp;amp;" in html


def test_code_fences_are_dropped_but_their_text_is_kept_escaped():
    html = markdown_to_storage("```\n<b>x</b>\n```")
    assert html == "<p>&lt;b&gt;x&lt;/b&gt;</p>"


def test_facts_cover_every_step_approval_and_commit():
    text = facts(SPEC, SHAS)
    for step in execution_order(SPEC):
        assert f"- {step.id} " in text
    for approval in SPEC.approvals:
        assert approval.id in text
    assert f"commit {SHAS[IAC][:7]}" in text and f"commit {SHAS[MCP][:7]}" in text
    assert "only after APPR-MGR-001" in text
    assert "a person must start it" in text  # db_migrate is manual
    assert "undo with terraform destroy" in text and "nothing to undo" in text


def test_page_has_the_prose_then_an_exact_appendix():
    page = render_page(SPEC, SHAS, "## Overview\nShort.", run_id="run123")
    assert page.startswith("<h2>Overview</h2><p>Short.</p><h2>Appendix")
    assert page.count("<tr>") == 1 + len(SPEC.steps)  # header + one row per step
    assert "db_migrate (manual)" in page and "APPR-MGR-001, APPR-MCP-001" in page
    assert SPEC.digest()[:12] in page and "run123" in page


def test_appendix_escapes_spec_values():
    data = DEMO_SPEC.read_text(encoding="utf-8").replace(
        'summary: "Tech Risk: move', 'summary: "<b>Tech Risk</b>: move')
    page = render_page(parse_spec(data), SHAS, "", run_id="r")
    assert "&lt;b&gt;Tech Risk&lt;/b&gt;" in page and "<b>" not in page


def test_title_and_sections():
    assert page_title(SPEC) == "MaC design: ClaimsAdjudicationService (claims-adjudication-onprem-to-aws)"
    assert SECTIONS[0] == "Overview" and "Rollback plan" in SECTIONS
