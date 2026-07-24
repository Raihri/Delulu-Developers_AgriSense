from __future__ import annotations

import pytest

from kb.ingest import clean_html, looks_like_legacy_bengali, promote_reviewed


def test_html_cleaner_removes_scripts_and_navigation() -> None:
    cleaned = clean_html(
        "<nav>menu</nav><article><h1>ভুট্টা</h1><p>দো-আঁশ মাটি</p></article>"
        "<script>bad()</script>"
    )
    assert "ভুট্টা" in cleaned
    assert "দো-আঁশ মাটি" in cleaned
    assert "menu" not in cleaned
    assert "bad()" not in cleaned


def test_legacy_text_is_blocked_until_review() -> None:
    assert looks_like_legacy_bengali("Avwg " * 100)
    assert not looks_like_legacy_bengali("This is a normal long English paragraph. " * 20)
    with pytest.raises(ValueError, match="Human review"):
        promote_reviewed({"source_locator": "PDF page 1"}, human_reviewed=False)
    promoted = promote_reviewed(
        {"source_locator": "PDF page 1", "text": "reviewed"}, human_reviewed=True
    )
    assert promoted["curation_status"] == "human_reviewed"
