from __future__ import annotations

from kb.build import seed_supabase
from kb.vector_store import SupabaseVectorStore
from tests.fakes import FakeSupabaseClient


def test_bilingual_retrieval_keeps_source_locator() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    store = SupabaseVectorStore(fake)

    bengali = store.search("মসুরের জন্য কোন মাটি ভালো", crop="lentil", limit=1)
    assert bengali
    assert bengali[0].metadata["source_id"] == "ais_crop_production"
    assert bengali[0].metadata["source_locator"]

    english = store.search("maize fertilizer nitrogen timing", crop="maize", limit=1)
    assert english
    assert english[0].metadata["source_id"] == "barc_frg_2024"
    assert english[0].metadata["source_locator"] == "PDF page 91"
