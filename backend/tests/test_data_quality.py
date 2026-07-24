from __future__ import annotations

import json

import yaml

from config import CURATED_ROOT, DATASET_ROOT
from kb.validate import validate_repository


def test_repository_manifest_hashes_and_schemas_pass() -> None:
    report = validate_repository()
    assert report["errors"] == []


def test_bbs_carrot_table_is_quarantined_not_corrected() -> None:
    quarantine = yaml.safe_load(
        (CURATED_ROOT / "data_quality_quarantine.yaml").read_text(encoding="utf-8")
    )
    item = next(
        row
        for row in quarantine["items"]
        if row["id"] == "bbs_2024_carrot_table_3_9_29"
    )
    assert item["status"] == "blocked"
    assert item["action"] == "exclude_from_ingestion"
    assert item["correction_allowed"] is False


def test_hdx_has_507_unique_adm3_pcodes_and_english_names_only() -> None:
    data = json.loads(
        (DATASET_ROOT / "hdx/bgd_admin3.geojson").read_text(encoding="utf-8")
    )
    pcodes = [feature["properties"]["adm3_pcode"] for feature in data["features"]]
    assert len(pcodes) == 507
    assert len(set(pcodes)) == 507
    assert all(feature["properties"]["lang"] == "en" for feature in data["features"])
