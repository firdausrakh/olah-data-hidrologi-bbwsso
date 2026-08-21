"""Monitoring page and unified monitoring API routes."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from flask import jsonify, redirect, render_template, request, session, url_for

from api.core import TATONAS_PARALLEL_WORKERS, app, clean_text, now_wib_naive
from api.routes.auth import is_server_authenticated, require_server_access
from api.services.monitoring import (
    MONITORING_CACHE_TTL,
    _MONITORING_CACHE,
    _monitor_aggregate,
    _monitor_fetch_beacon_group,
    _monitor_fetch_nonbeacon,
    _monitor_period_keys,
    _monitor_station_catalog,
)

@app.get("/monitoring")
def monitoring_page():
    if not is_server_authenticated():
        return redirect(url_for("index"))
    return render_template("monitoring.html")


@app.post("/api/monitoring/data")
def monitoring_data_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or request.form
    category = clean_text(str(payload.get("category", "rain"))).lower()
    resolution = clean_text(str(payload.get("resolution", "hourly"))).lower()
    date_from = clean_text(str(payload.get("date_from", "")))
    date_to = clean_text(str(payload.get("date_to", "")))
    if category not in {"rain", "tma"}:
        return jsonify({"ok": False, "error": "Kategori monitoring tidak valid."}), 400
    if resolution not in {"hourly", "daily"}:
        return jsonify({"ok": False, "error": "Interval monitoring tidak valid."}), 400
    try:
        from_day = datetime.strptime(date_from, "%Y-%m-%d")
        to_day = datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "error": "Tanggal harus berformat YYYY-MM-DD."}), 400
    if to_day < from_day:
        return jsonify({"ok": False, "error": "Tanggal akhir tidak boleh sebelum tanggal awal."}), 400

    now_local = now_wib_naive().replace(second=0, microsecond=0)
    today_local = now_local.date()
    if from_day.date() > today_local:
        return jsonify({"ok": False, "error": "Tanggal mulai tidak boleh melebihi tanggal hari ini."}), 400
    if to_day.date() > today_local:
        to_day = datetime.combine(today_local, datetime.min.time())
        date_to = today_local.isoformat()

    if (to_day - from_day).days > 366:
        return jsonify({"ok": False, "error": "Monitoring dibatasi maksimal 367 hari per permintaan."}), 400

    if category == "rain":
        start_dt = from_day.replace(hour=7, minute=0)
        requested_end = (to_day + timedelta(days=1)).replace(hour=6, minute=59)
    else:
        start_dt = from_day.replace(hour=0, minute=0)
        requested_end = to_day.replace(hour=23, minute=59)
    end_dt = min(requested_end, now_local)
    if end_dt < start_dt:
        return jsonify({"ok": False, "error": "Periode yang dipilih belum berjalan sampai waktu saat ini."}), 400

    cache_key = (category, date_from, date_to)
    cached = _MONITORING_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < MONITORING_CACHE_TTL:
        cached_response = dict(cached[1])
        selected_view = (cached_response.get("views") or {}).get(resolution) or {}
        cached_response.update({
            "resolution": resolution,
            "periods": selected_view.get("periods", cached_response.get("periods", [])),
            "period_keys": selected_view.get("period_keys", cached_response.get("period_keys", [])),
            "stations": selected_view.get("stations", cached_response.get("stations", [])),
        })
        return jsonify(cached_response)

    try:
        catalog = _monitor_station_catalog(category)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Gagal memuat metadata monitoring: {exc}"}), 500

    results: list[dict[str, Any]] = []
    warnings: list[str] = []

    def run_vendor(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        vendor_results: list[dict[str, Any]] = []
        vendor_warnings: list[str] = []
        if not items:
            return vendor_results, vendor_warnings
        vendor_name = str(items[0].get("vendor") or "")

        def one(st: dict[str, Any]) -> dict[str, Any]:
            return _monitor_fetch_nonbeacon(st, category, start_dt, end_dt)

        # All non-Beacon adapters now use independent request/session state for
        # monitoring, so logger requests can run concurrently inside each vendor.
        if vendor_name in {"higertech", "tatonas", "dashindo"} and len(items) > 1:
            vendor_limit = TATONAS_PARALLEL_WORKERS if vendor_name == "tatonas" else 4
            max_workers = min(vendor_limit, len(items))
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"monitor-{vendor_name}") as inner:
                fmap = {inner.submit(one, st): st for st in items}
                for future in as_completed(fmap):
                    st = fmap[future]
                    try:
                        vendor_results.append(future.result())
                    except Exception as exc:
                        vendor_warnings.append(f"{vendor_name.title()} {st.get('name')}: {exc}")
                        vendor_results.append({**st, "series": [], "fetch_failed": True})
        else:
            # Single-item vendor group.
            for st in items:
                try:
                    vendor_results.append(one(st))
                except Exception as exc:
                    vendor_warnings.append(f"{vendor_name.title()} {st.get('name')}: {exc}")
                    vendor_results.append({**st, "series": [], "fetch_failed": True})
        return vendor_results, vendor_warnings

    # Run all vendor groups at the same time. This is important on Vercel: total
    # wall-clock duration becomes approximately the slowest vendor, not the sum
    # of Beacon + Higertech + Tatonas + Dashindo.
    jobs: list[tuple[str, list[dict[str, Any]], Any]] = []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor-vendors") as executor:
        if catalog["beacon"]:
            jobs.append(("beacon", catalog["beacon"], executor.submit(_monitor_fetch_beacon_group, catalog["beacon"], category, start_dt, end_dt)))
        for vendor in ("higertech", "tatonas", "dashindo"):
            if catalog[vendor]:
                jobs.append((vendor, catalog[vendor], executor.submit(run_vendor, catalog[vendor])))
        for vendor, vendor_items, future in jobs:
            try:
                res, warn = future.result()
                results.extend(res)
                warnings.extend(warn)
            except Exception as exc:
                warnings.append(f"{vendor.title()}: {exc}")
                # Jika satu worker vendor gagal di level grup, tetap materialisasi
                # seluruh posnya sebagai Gagal agar status UI tidak salah menjadi 0.
                results.extend({**st, "series": [], "fetch_failed": True} for st in vendor_items)

    # Keep all vendors in one table. Only append vendor names when two physical
    # logger entries would otherwise have the exact same displayed station name.
    name_counts: dict[str, int] = {}
    for st in results:
        key = clean_text(str(st.get("name") or "")).casefold()
        name_counts[key] = name_counts.get(key, 0) + 1

    sorted_results = sorted(results, key=lambda x: clean_text(str(x.get("name") or "")).casefold())
    station_display_names: list[tuple[dict[str, Any], str]] = []
    for st in sorted_results:
        display_name = clean_text(str(st.get("name") or st.get("id_logger") or "Pos"))
        if name_counts.get(display_name.casefold(), 0) > 1:
            display_name += f" ({str(st.get('vendor','')).title()})"
        station_display_names.append((st, display_name))

    views: dict[str, dict[str, Any]] = {}
    for interval in ("hourly", "daily"):
        interval_periods = _monitor_period_keys(start_dt, end_dt, category, interval)
        interval_stations: list[dict[str, Any]] = []
        for st, display_name in station_display_names:
            agg = _monitor_aggregate(st.get("series") or [], category, interval)
            series = st.get("series") or []
            last_data_at = max((dt for dt, _value in series), default=None)
            interval_stations.append({
                "name": display_name,
                "vendor": st.get("vendor"),
                "values": [round(agg[key], 3) if key in agg else None for key, _label in interval_periods],
                # Timestamp data mentah terakhir dipakai UI untuk status freshness.
                # Nilai 0 tetap dianggap data valid; yang diperiksa adalah keberadaan timestamp.
                "last_data_at": last_data_at.strftime("%Y-%m-%d %H:%M") if last_data_at else None,
                "fetch_failed": bool(st.get("fetch_failed")),
            })
        views[interval] = {
            "periods": [label for _key, label in interval_periods],
            "period_keys": [key for key, _label in interval_periods],
            "stations": interval_stations,
        }

    selected_view = views[resolution]
    response = {
        "ok": True,
        "category": category,
        "resolution": resolution,
        "date_from": date_from,
        "date_to": date_to,
        "effective_start": start_dt.strftime("%Y-%m-%d %H:%M"),
        "effective_end": end_dt.strftime("%Y-%m-%d %H:%M"),
        "hydrological_day": category == "rain",
        "periods": selected_view["periods"],
        "period_keys": selected_view["period_keys"],
        "stations": selected_view["stations"],
        "views": views,
        "warnings": warnings[:50],
        "warning_count": len(warnings),
        "failed_count": sum(1 for st, _display_name in station_display_names if st.get("fetch_failed")),
    }
    _MONITORING_CACHE[cache_key] = (time.time(), response)
    if len(_MONITORING_CACHE) > 16:
        oldest = min(_MONITORING_CACHE, key=lambda k: _MONITORING_CACHE[k][0])
        _MONITORING_CACHE.pop(oldest, None)
    return jsonify(response)


