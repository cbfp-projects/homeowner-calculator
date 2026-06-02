#!/usr/bin/env python3
"""Update Bay Area city mortgage-rate estimates from a trusted public source.

Source:
- FRED series MORTGAGE30US (30-Year Fixed Rate Mortgage Average in the United States)

Method:
- Fetch latest non-empty observation from FRED REST API (JSON).
- Compute current city-rate median.
- Shift each city rate by (latest_source_rate - current_median), preserving relative spreads.
- Update metadata fields and cache-busting version in index.html.

Guardrails:
- Requires FRED_API_KEY environment variable (free key from https://fred.stlouisfed.org/docs/api/api_key.html).
- If source fetch fails or source data is unavailable, log and exit without modifying files.
- Validate JSON shape before modifying.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES_ID = "MORTGAGE30US"
DEFAULT_DATA_PATH = Path("data/bay-area-city-rates.json")
DEFAULT_INDEX_PATH = Path("index.html")
VERSION_SUFFIX = "daily-rate-refresh"


class ValidationError(ValueError):
    pass


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_rate_data(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        raise ValidationError("Rate data must be a JSON object")

    if not isinstance(data.get("rates"), list) or not data["rates"]:
        raise ValidationError("`rates` must be a non-empty array")

    validated = []
    for idx, entry in enumerate(data["rates"]):
        if not isinstance(entry, dict):
            raise ValidationError(f"rates[{idx}] must be an object")
        city = entry.get("city")
        rate = entry.get("rate")
        if not isinstance(city, str) or not city.strip():
            raise ValidationError(f"rates[{idx}].city must be a non-empty string")
        if not isinstance(rate, (int, float)):
            raise ValidationError(f"rates[{idx}].rate must be numeric")
        validated.append(entry)
    return validated


def fetch_latest_rate() -> tuple[dt.date, float]:
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        print("[skip] FRED_API_KEY environment variable is not set")
        raise RuntimeError("source_unavailable")

    params = urlencode({
        "series_id": FRED_SERIES_ID,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 10,  # fetch a few to find the latest non-missing value
    })
    url = f"{FRED_API_BASE}?{params}"

    try:
        with urlopen(url, timeout=20) as response:
            content = response.read().decode("utf-8")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"[skip] Could not reach FRED API: {exc}")
        raise RuntimeError("source_unavailable") from exc

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"[skip] FRED API returned invalid JSON: {exc}")
        raise RuntimeError("source_unavailable") from exc

    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        print("[skip] No observations found in FRED API response")
        raise RuntimeError("source_unavailable")

    latest_date: dt.date | None = None
    latest_value: float | None = None

    for obs in observations:
        date_text = (obs.get("date") or "").strip()
        value_text = (obs.get("value") or "").strip()
        if not date_text or value_text in {"", "."}:
            continue

        try:
            obs_date = dt.date.fromisoformat(date_text)
            obs_value = float(value_text)
        except ValueError:
            continue

        if latest_date is None or obs_date > latest_date:
            latest_date = obs_date
            latest_value = obs_value

    if latest_date is None or latest_value is None:
        print("[skip] No usable observations found in FRED API response")
        raise RuntimeError("source_unavailable")

    return latest_date, latest_value


def replace_index_data_version(index_html: Path, version_value: str) -> bool:
    original = index_html.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"const RATE_MAP_DATA_VERSION = '[^']*';",
        f"const RATE_MAP_DATA_VERSION = '{version_value}';",
        original,
        count=1,
    )
    if count == 0:
        raise ValidationError("Could not find RATE_MAP_DATA_VERSION in index.html")
    if updated == original:
        return False
    index_html.write_text(updated, encoding="utf-8")
    return True


def atomic_write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        json.dump(content, tmp, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def update_rates(data_path: Path, index_path: Path) -> int:
    data = load_json(data_path)
    rate_entries = validate_rate_data(data)

    city_rates = [float(entry["rate"]) for entry in rate_entries]
    current_median = statistics.median(city_rates)

    try:
        source_date, source_rate = fetch_latest_rate()
    except RuntimeError as exc:
        if str(exc) == "source_unavailable":
            return 0
        raise

    shift = source_rate - current_median

    updated_data = json.loads(json.dumps(data))
    for entry in updated_data["rates"]:
        entry["rate"] = round(float(entry["rate"]) + shift, 2)
        if "note" not in entry or not str(entry.get("note", "")).strip():
            entry["note"] = "Estimated from daily national average with city spread adjustment"

    updated_data["lastUpdated"] = source_date.isoformat()
    updated_data["estimateBasis"] = (
        "Daily update from FRED MORTGAGE30US national 30-year fixed average; "
        "city rates are shifted from prior city estimates by the source-vs-median delta."
    )
    updated_data["source"] = {
        "name": "FRED",
        "series": "MORTGAGE30US",
        "url": f"{FRED_API_BASE}?series_id={FRED_SERIES_ID}",
        "observationDate": source_date.isoformat(),
        "retrievedAtUtc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    if updated_data == data:
        print("[ok] No source-driven changes detected")
        return 0

    atomic_write_json(data_path, updated_data)
    version_value = f"{source_date.isoformat()}-{VERSION_SUFFIX}"
    index_changed = replace_index_data_version(index_path, version_value)

    print(
        "[ok] Updated rates:",
        f"source_date={source_date.isoformat()}",
        f"source_rate={source_rate:.2f}",
        f"median_before={current_median:.2f}",
        f"shift={shift:+.2f}",
        f"index_version_updated={index_changed}",
    )
    return 0


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    data_path = (repo_root / argv[1]).resolve() if len(argv) > 1 else (repo_root / DEFAULT_DATA_PATH).resolve()
    index_path = (repo_root / argv[2]).resolve() if len(argv) > 2 else (repo_root / DEFAULT_INDEX_PATH).resolve()

    if not data_path.exists():
        raise FileNotFoundError(f"Rate data file not found: {data_path}")
    if not index_path.exists():
        raise FileNotFoundError(f"index.html not found: {index_path}")

    try:
        return update_rates(data_path, index_path)
    except ValidationError as exc:
        print(f"[error] Validation failure: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
