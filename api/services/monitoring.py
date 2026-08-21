"""Unified monitoring data helpers shared by the monitoring routes."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from api import core
from api.core import (
    BBWSSession,
    EmptyHistoricalData,
    PARAMETER_CACHE,
    PARAMETER_CACHE_TTL,
    _TATONAS_PARAMETER_CACHE,
    _parse_any_datetime,
    _tatonas_parameters_from_catalog,
    _tatonas_sensor_catalog,
    classify_parameter,
    clean_text,
    dashindo_data,
    dashindo_parameters_for,
    dashindo_stations,
    get_config,
    higertech_data,
    higertech_parameters_for,
    higertech_stations,
    positions_for_data_type,
    tatonas_data,
    tatonas_parameters,
    tatonas_stations,
)

# ============================================================
# UNIFIED MONITORING (SEPARATE PAGE)
# ============================================================

_MONITORING_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
MONITORING_CACHE_TTL = int(get_config("MONITORING_CACHE_TTL", 5 * 60))
MONITORING_BEACON_WORKERS = max(1, min(3, int(get_config("MONITORING_BEACON_WORKERS", 3))))


def _preferred_monitor_parameter(params: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    candidates = []
    for p in params:
        ptype = clean_text(str(p.get("type") or ""))
        name = clean_text(str(p.get("name") or ""))
        classified = classify_parameter(name)
        if category == "rain" and ptype not in {"rain", "rainfall"} and classified != "rainfall":
            continue
        if category == "tma" and ptype not in {"tma", "water_level"} and classified != "water_level":
            continue
        candidates.append(p)
    if not candidates:
        return None

    def score(p: dict[str, Any]) -> tuple[int, str]:
        name = clean_text(str(p.get("name") or "")).lower()
        if category == "rain":
            # Match the Olah Data default: explicit channel 2 wins; if there is
            # only channel 1, it naturally becomes the best available candidate.
            channel = re.search(
                r"(?:precipitation\s*intensity|curah\s*hujan|rainfall|precipitation|rain\s*intensity)\s*[-_#]?\s*(\d+)\b",
                name,
            )
            if channel and channel.group(1) == "2":
                return (2200, name)
            if "precipitation intensity" in name:
                return (1800, name)
            if "curah hujan" in name or "rainfall" in name or "precipitation" in name or "rain intensity" in name:
                return (1700, name)
        else:
            if "tinggi muka air" in name:
                return (2000, name)
            if "water level" in name:
                return (1900, name)
            if "elevasi muka air" in name or "water stage" in name or "muka air" in name:
                return (1800, name)
        return (1000, name)

    return sorted(candidates, key=lambda p: (-score(p)[0], score(p)[1]))[0]


def _monitor_station_catalog(category: str) -> dict[str, list[dict[str, Any]]]:
    """Build each vendor catalog concurrently; persisted metadata makes cold UI cheap."""
    catalog: dict[str, list[dict[str, Any]]] = {"beacon": [], "higertech": [], "tatonas": [], "dashindo": []}

    def beacon_catalog() -> list[dict[str, Any]]:
        return [{
            "vendor": "beacon", "id_logger": str(pos["id_logger"]), "name": pos["name"],
        } for pos in positions_for_data_type(category)]

    def higer_catalog() -> list[dict[str, Any]]:
        allowed = {"AWLR_ARR"}
        allowed.update({"ARR", "AWS"} if category == "rain" else {"AWLR"})
        out = []
        for st in higertech_stations():
            if st.get("type") not in allowed:
                continue
            params = core._HIGERTECH_PARAMETER_CATALOG.get(str(st.get("deviceId")), []) if isinstance(core._HIGERTECH_PARAMETER_CATALOG, dict) else []
            if not params:
                params = higertech_parameters_for(category)
            out.append({
                "vendor": "higertech", "id_logger": st["deviceId"], "name": st["name"],
                "parameter": _preferred_monitor_parameter(params, category),
            })
        return out

    def tatonas_catalog() -> list[dict[str, Any]]:
        out = []
        sensor_catalog: list[dict[str, Any]] = []
        stations = tatonas_stations()
        if any(str(st.get("kd_hardware")) not in _TATONAS_PARAMETER_CACHE for st in stations):
            try:
                sensor_catalog = _tatonas_sensor_catalog()
            except Exception:
                sensor_catalog = []
        for st in stations:
            is_tma = st.get("station_type") == "water_level"
            if (category == "tma") != is_tma:
                continue
            hw = str(st["kd_hardware"])
            cached = _TATONAS_PARAMETER_CACHE.get(hw)
            params = cached[1] if cached else (
                _tatonas_parameters_from_catalog(hw, sensor_catalog, station=st) if sensor_catalog else tatonas_parameters(hw)
            )
            out.append({
                "vendor": "tatonas", "id_logger": hw,
                "name": st.get("name") or st.get("location_original") or hw,
                "parameter": _preferred_monitor_parameter(params, category),
            })
        return out

    def dashindo_catalog() -> list[dict[str, Any]]:
        if category != "tma":
            return []
        out = []
        for st in dashindo_stations():
            params = dashindo_parameters_for(str(st["id"]), "tma")
            out.append({
                "vendor": "dashindo", "id_logger": str(st["id"]), "name": st["name"],
                "parameter": _preferred_monitor_parameter(params, category),
            })
        return out

    builders = {
        "beacon": beacon_catalog, "higertech": higer_catalog,
        "tatonas": tatonas_catalog, "dashindo": dashindo_catalog,
    }
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor-meta") as executor:
        futures = {executor.submit(fn): vendor for vendor, fn in builders.items()}
        for future in as_completed(futures):
            vendor = futures[future]
            try:
                catalog[vendor] = future.result()
            except Exception as exc:
                # Keep one vendor metadata failure from hiding all other vendors.
                print(f"Metadata monitoring {vendor} gagal: {exc}")
                catalog[vendor] = []

    for items in catalog.values():
        items.sort(key=lambda x: str(x.get("name", "")).casefold())
    return catalog


def _monitor_parse_rows(rows: list[list[Any]], category: str, vendor: str, parameter: dict[str, Any]) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for row in rows:
        if len(row) < 2:
            continue
        dt = _parse_any_datetime(row[0])
        if dt is None:
            continue
        raw_value = clean_text(str(row[1])).replace(",", ".")
        number_match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", raw_value)
        if not number_match:
            continue
        try:
            value = float(number_match.group(0))
        except (TypeError, ValueError):
            continue
        if category == "tma" and vendor == "tatonas" and clean_text(str(parameter.get("source_unit") or "")).lower() == "cm":
            value /= 100.0
        out.append((dt, value))
    return out


def _monitor_fetch_nonbeacon(st: dict[str, Any], category: str, start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    vendor = st["vendor"]
    param = st.get("parameter")
    if not param:
        raise RuntimeError("Parameter yang sesuai tidak ditemukan.")
    dari = start_dt.strftime("%Y-%m-%d %H:%M")
    sampai = end_dt.strftime("%Y-%m-%d %H:%M")
    if vendor == "higertech":
        _headers, rows, _station = higertech_data(
            st["id_logger"], dari, sampai, str(param["id"]), isolated_session=True
        )
    elif vendor == "tatonas":
        _headers, rows, _station, returned_param = tatonas_data(
            st["id_logger"], dari, sampai, str(param["id"]), isolated_session=True
        )
        param = returned_param or param
    elif vendor == "dashindo":
        _headers, rows, _station, returned_param = dashindo_data(st["id_logger"], str(param["id"]), dari, sampai)
        param = returned_param or param
    else:
        raise RuntimeError(f"Vendor monitoring tidak dikenal: {vendor}")
    return {**st, "parameter": param, "series": _monitor_parse_rows(rows, category, vendor, param)}


def _monitor_fetch_beacon_group(stations: list[dict[str, Any]], category: str, start_dt: datetime, end_dt: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    if not stations:
        return [], []
    groups: list[list[dict[str, Any]]] = [[] for _ in range(min(MONITORING_BEACON_WORKERS, len(stations)))]
    for idx, st in enumerate(stations):
        groups[idx % len(groups)].append(st)

    def worker(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        client = BBWSSession()
        try:
            client.login()
        except Exception as exc:
            failed = [{**st, "parameter": None, "series": [], "fetch_failed": True} for st in items]
            return failed, [f"Beacon: login gagal ({exc})"]
        for st in items:
            try:
                cached = PARAMETER_CACHE.get(str(st["id_logger"]))
                params = cached[1] if cached and time.time() - cached[0] < PARAMETER_CACHE_TTL else client.discover_parameters(str(st["id_logger"]))
                param = _preferred_monitor_parameter(params, category)
                if not param:
                    warnings.append(f"Beacon {st.get('name')}: parameter monitoring tidak ditemukan")
                    results.append({**st, "parameter": None, "series": [], "fetch_failed": True})
                    continue
                try:
                    _headers, rows, _title = client.fetch_historical(
                        id_logger=str(st["id_logger"]),
                        id_param=str(param["id"]),
                        dari=start_dt.strftime("%Y-%m-%d %H:%M"),
                        sampai=end_dt.strftime("%Y-%m-%d %H:%M"),
                        parameter_name=str(param.get("name") or "Data"),
                        parallel_workers=1,
                    )
                except EmptyHistoricalData:
                    rows = []
                results.append({**st, "parameter": param, "series": _monitor_parse_rows(rows, category, "beacon", param)})
            except Exception as exc:
                warnings.append(f"Beacon {st.get('name')}: {exc}")
                results.append({**st, "parameter": None, "series": [], "fetch_failed": True})
        return results, warnings

    all_results: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=len(groups), thread_name_prefix="monitor-beacon") as executor:
        futures = [executor.submit(worker, group) for group in groups if group]
        for future in as_completed(futures):
            res, warn = future.result()
            all_results.extend(res)
            all_warnings.extend(warn)
    return all_results, all_warnings


def _monitor_period_keys(start_date: datetime, end_date: datetime, category: str, resolution: str) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if resolution == "daily":
        day = start_date.date()
        last_day = end_date.date()
        if category == "rain" and end_date.hour < 7:
            last_day -= timedelta(days=1)
        while day <= last_day:
            key = day.isoformat()
            keys.append((key, day.strftime("%Y-%m-%d")))
            day += timedelta(days=1)
        return keys

    cursor = start_date
    while cursor <= end_date:
        key = cursor.strftime("%Y-%m-%d %H:00")
        if category == "rain":
            hydro_day = cursor.date() if cursor.hour >= 7 else (cursor - timedelta(days=1)).date()
            label = f"{hydro_day.isoformat()} {cursor.strftime('%H:00')}"
        else:
            label = key
        keys.append((key, label))
        cursor += timedelta(hours=1)
    return keys


def _monitor_aggregate(series: list[tuple[datetime, float]], category: str, resolution: str) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for dt, value in series:
        if resolution == "hourly":
            key = dt.strftime("%Y-%m-%d %H:00")
        else:
            effective = dt
            if category == "rain" and dt.hour < 7:
                effective = dt - timedelta(days=1)
            key = effective.strftime("%Y-%m-%d")
        buckets.setdefault(key, []).append(value)
    out: dict[str, float] = {}
    for key, vals in buckets.items():
        if not vals:
            continue
        out[key] = sum(vals) if category == "rain" else sum(vals) / len(vals)
    return out


