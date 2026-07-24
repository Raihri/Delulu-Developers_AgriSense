from __future__ import annotations

import csv
import json
from functools import lru_cache
from typing import Any

from config import CURATED_ROOT, DATASET_ROOT


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        xi, yi = point[0], point[1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lon: float, lat: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not _point_in_ring(lon, lat, polygon[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:])


def _contains(geometry: dict[str, Any], lon: float, lat: float) -> bool:
    if geometry.get("type") == "Polygon":
        return _point_in_polygon(lon, lat, geometry["coordinates"])
    if geometry.get("type") == "MultiPolygon":
        return any(
            _point_in_polygon(lon, lat, polygon)
            for polygon in geometry["coordinates"]
        )
    return False


@lru_cache(maxsize=1)
def _features() -> list[dict[str, Any]]:
    path = DATASET_ROOT / "hdx/bgd_admin3.geojson"
    return json.loads(path.read_text(encoding="utf-8"))["features"]


@lru_cache(maxsize=1)
def _aliases() -> dict[str, list[dict[str, str]]]:
    aliases: dict[str, list[dict[str, str]]] = {}
    with (CURATED_ROOT / "admin_aliases.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            aliases.setdefault(row["pcode"], []).append(row)
    return aliases


@lru_cache(maxsize=1)
def _aez_crosswalk() -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    with (CURATED_ROOT / "admin_aez_crosswalk.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            result.setdefault(row["adm3_pcode"], []).append(row)
    return result


def resolve_location(lat: float, lon: float) -> dict[str, Any]:
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid latitude/longitude")
    match = next(
        (feature for feature in _features() if _contains(feature["geometry"], lon, lat)),
        None,
    )
    if not match:
        return {
            "matched": False,
            "geometry_source": "hdx_cod_bgd",
            "aez_resolution": "unavailable",
        }
    properties = match["properties"]
    pcodes = [
        properties["adm1_pcode"],
        properties["adm2_pcode"],
        properties["adm3_pcode"],
    ]
    aliases = {
        pcode: [
            {
                "alias": row["alias"],
                "language": row["language"],
                "alias_type": row["alias_type"],
            }
            for row in _aliases().get(pcode, [])
        ]
        for pcode in pcodes
    }
    candidates = _aez_crosswalk().get(properties["adm3_pcode"], [])
    return {
        "matched": True,
        "geometry_source": "hdx_cod_bgd",
        "geometry_version": properties.get("version"),
        "admin": {
            "adm1": {
                "name": properties["adm1_name"],
                "pcode": properties["adm1_pcode"],
            },
            "adm2": {
                "name": properties["adm2_name"],
                "pcode": properties["adm2_pcode"],
            },
            "adm3": {
                "name": properties["adm3_name"],
                "pcode": properties["adm3_pcode"],
            },
        },
        "aliases": aliases,
        "aez_candidates": [
            {
                "aez_id": int(row["aez_id"]),
                "resolution": row["resolution"],
                "coverage_note": row["coverage_note"],
                "source_id": row["source_id"],
                "source_locator": row["source_locator"],
            }
            for row in candidates
        ],
        "aez_resolution": "admin_candidate" if candidates else "unavailable",
        "point_aez_resolved": False,
        "warning": (
            "AEZ candidates are an ADM3 fallback, not a point-in-polygon AEZ result."
            if candidates
            else "No reviewed ADM3-to-AEZ fallback exists for this location."
        ),
    }
