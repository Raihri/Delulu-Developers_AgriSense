from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch_forecast(lat: float, lon: float, *, days: int = 7) -> dict[str, Any]:
    if not 1 <= days <= 16:
        raise ValueError("days must be between 1 and 16")
    parameters = {
        "latitude": lat,
        "longitude": lon,
        "forecast_days": days,
        "timezone": "auto",
        "daily": ",".join(
            [
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_sum",
                "et0_fao_evapotranspiration",
            ]
        ),
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(parameters)
    with urlopen(url, timeout=20) as response:  # noqa: S310 - fixed trusted host
        payload = json.load(response)
    return {
        "source_id": "open_meteo",
        "request": parameters,
        "request_url": url,
        "timezone": payload.get("timezone"),
        "daily_units": payload.get("daily_units"),
        "daily": payload.get("daily"),
    }
