from __future__ import annotations

from kb.build import seed_supabase
from kb.verify import verify_seed
from tests.fakes import FakeSupabaseClient


def test_round1_seed_verification_contract() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)

    result = verify_seed(fake)

    assert result["status"] == "passed"
    assert result["count_mismatches"] == {}
    assert result["cited_vector_search"] is True
