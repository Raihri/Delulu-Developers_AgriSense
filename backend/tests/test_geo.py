from __future__ import annotations

from tools.geo import resolve_location


def test_bogura_sadar_resolves_admin_and_ambiguous_aez_candidates() -> None:
    result = resolve_location(24.89539917, 89.35605547)
    assert result["matched"] is True
    assert result["admin"]["adm3"]["pcode"] == "BD50100020"
    assert {row["aez_id"] for row in result["aez_candidates"]} == {3, 25, 27}
    assert result["point_aez_resolved"] is False
    aliases = result["aliases"]["BD50100020"]
    assert any(row["alias"] == "বগুড়া সদর" for row in aliases)
