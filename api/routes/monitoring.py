"""Monitoring page and unified monitoring API routes."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta
from typing import Any

from flask import jsonify, redirect, render_template, request, session, url_for

from api.core import app, clean_text, now_wib_naive
from api.routes.auth import is_server_authenticated, require_server_access
from api.services.monitoring import (
    MONITORING_CACHE_TTL,
    MONITORING_TATONAS_WORKERS,
    MONITORING_TATONAS_VENDOR_DEADLINE,
    _monitor_fetch_dashindo_group,
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
    request_started = time.perf_counter()
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or request.form
    category = clean_text(str(payload.get("category", "rain"))).lower()
    resolution = clean_text(str(payload.get("resolution", "hourly"))).lower()
    date_from = clean_text(str(payload.get("date_from", "")))
    date_to = clean_text(str(payload.get("date_to", "")))

    supported_vendors = ("beacon", "tatonas", "higertech", "dashindo")
    raw_vendors = payload.get("vendors")
    if raw_vendors is None and hasattr(payload, "getlist"):
        listed = payload.getlist("vendors")
        raw_vendors = listed if listed else None
    if raw_vendors is None:
        selected_vendors = list(supported_vendors)
    elif isinstance(raw_vendors, (list, tuple, set)):
        selected_vendors = [clean_text(str(v)).lower() for v in raw_vendors]
    else:
        selected_vendors = [clean_text(v).lower() for v in str(raw_vendors).split(",")]
    selected_vendors = [v for v in supported_vendors if v in set(selected_vendors)]
    if not selected_vendors:
        return jsonify({"ok": False, "error": "Pilih minimal satu Logger untuk Monitoring."}), 400
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

    cache_key = (category, date_from, date_to, tuple(selected_vendors))
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
        source_perf = dict(cached_response.get("performance") or {})
        cached_response["performance"] = {
            **source_perf,
            "cache_hit": True,
            "cache_age_ms": round((time.time() - cached[0]) * 1000.0, 1),
            "request_total_ms": round((time.perf_counter() - request_started) * 1000.0, 1),
        }
        return jsonify(cached_response)

    metadata_started = time.perf_counter()
    try:
        catalog, metadata_timing = _monitor_station_catalog(category, set(selected_vendors))
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Gagal memuat metadata monitoring: {exc}"}), 500
    metadata_ms = round((time.perf_counter() - metadata_started) * 1000.0, 1)

    results: list[dict[str, Any]] = []
    warnings: list[str] = []

    def run_vendor(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], float, dict[str, Any]]:
        vendor_started = time.perf_counter()
        vendor_results: list[dict[str, Any]] = []
        vendor_warnings: list[str] = []
        station_timings: list[dict[str, Any]] = []
        if not items:
            return vendor_results, vendor_warnings, 0.0, {"station_count": 0, "station_timings": []}
        vendor_name = str(items[0].get("vendor") or "")

        # Dashindo Monitoring has a specialized batch transport: one persistent
        # Engine.IO connection per worker is reused for multiple stations and
        # each station requests native hourly n_data first (CSV is fallback).
        # The Olah Data adapter remains untouched.
        if vendor_name == "dashindo":
            res, warn, detail = _monitor_fetch_dashindo_group(items, category, start_dt, end_dt)
            return res, warn, round((time.perf_counter() - vendor_started) * 1000.0, 1), detail

        vendor_deadline_at = (
            vendor_started + MONITORING_TATONAS_VENDOR_DEADLINE
            if vendor_name == "tatonas"
            else None
        )
        vendor_deadline_exceeded = False
        vendor_timed_out_count = 0

        def one(st: dict[str, Any]) -> dict[str, Any]:
            return _monitor_fetch_nonbeacon(
                st,
                category,
                start_dt,
                end_dt,
                deadline_at=vendor_deadline_at,
            )

        def timed_one(st: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, float, str | None]:
            t0 = time.perf_counter()
            try:
                result = one(st)
                return st, result, round((time.perf_counter() - t0) * 1000.0, 1), None
            except Exception as exc:
                return st, None, round((time.perf_counter() - t0) * 1000.0, 1), str(exc)

        # Monitoring has its own Tatonas concurrency/timeout profile.  Olah Data
        # still uses TATONAS_PARALLEL_WORKERS and the patient retry/split path in
        # api/core.py, unchanged.
        if vendor_name in {"higertech", "tatonas", "dashindo"} and len(items) > 1:
            vendor_limit = MONITORING_TATONAS_WORKERS if vendor_name == "tatonas" else 4
            max_workers = min(vendor_limit, len(items))

            # Tatonas gets a hard vendor-wide deadline in Monitoring.  This is
            # intentionally not used by Olah Data: the dashboard should return
            # partial multi-vendor data instead of waiting tens of seconds for
            # one degraded upstream server.
            if vendor_name == "tatonas":
                inner = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="monitor-tatonas")
                fmap = {inner.submit(timed_one, st): st for st in items}
                remaining = max(0.0, (vendor_deadline_at or vendor_started) - time.perf_counter())
                done, pending = wait(fmap, timeout=remaining)

                for future in done:
                    st, result, elapsed_ms, error = future.result()
                    station_timings.append({
                        "name": st.get("name"),
                        "id_logger": st.get("id_logger"),
                        "total_ms": elapsed_ms,
                        "ok": error is None,
                        **({"error": error} if error else {}),
                    })
                    if error is None and result is not None:
                        vendor_results.append(result)
                    else:
                        vendor_warnings.append(f"Tatonas {st.get('name')}: {error}")
                        vendor_results.append({**st, "series": [], "fetch_failed": True})

                if pending:
                    vendor_deadline_exceeded = True
                    vendor_timed_out_count = len(pending)
                    cutoff_ms = round((time.perf_counter() - vendor_started) * 1000.0, 1)
                    for future in pending:
                        st = fmap[future]
                        future.cancel()
                        station_timings.append({
                            "name": st.get("name"),
                            "id_logger": st.get("id_logger"),
                            "total_ms": cutoff_ms,
                            "ok": False,
                            "deadline_exceeded": True,
                            "error": f"Batas waktu total Tatonas {MONITORING_TATONAS_VENDOR_DEADLINE:g} dtk tercapai.",
                        })
                        vendor_results.append({**st, "series": [], "fetch_failed": True})
                    vendor_warnings.append(
                        f"Tatonas melewati batas waktu total {MONITORING_TATONAS_VENDOR_DEADLINE:g} dtk; "
                        f"{len(pending)} pos yang belum selesai dilewati."
                    )

                # Do not wait for already-running HTTP workers after the cutoff.
                # Their own request timeout is also shrunk to the same absolute
                # deadline, so they should terminate shortly without delaying
                # the response sent to the browser.
                inner.shutdown(wait=False, cancel_futures=True)
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"monitor-{vendor_name}") as inner:
                    fmap = {inner.submit(timed_one, st): st for st in items}
                    for future in as_completed(fmap):
                        st, result, elapsed_ms, error = future.result()
                        station_timings.append({
                            "name": st.get("name"),
                            "id_logger": st.get("id_logger"),
                            "total_ms": elapsed_ms,
                            "ok": error is None,
                            **({"error": error} if error else {}),
                        })
                        if error is None and result is not None:
                            vendor_results.append(result)
                        else:
                            vendor_warnings.append(f"{vendor_name.title()} {st.get('name')}: {error}")
                            vendor_results.append({**st, "series": [], "fetch_failed": True})
        else:
            for item in items:
                st, result, elapsed_ms, error = timed_one(item)
                station_timings.append({
                    "name": st.get("name"),
                    "id_logger": st.get("id_logger"),
                    "total_ms": elapsed_ms,
                    "ok": error is None,
                    **({"error": error} if error else {}),
                })
                if error is None and result is not None:
                    vendor_results.append(result)
                else:
                    vendor_warnings.append(f"{vendor_name.title()} {st.get('name')}: {error}")
                    vendor_results.append({**st, "series": [], "fetch_failed": True})

        station_timings.sort(key=lambda item: float(item.get("total_ms") or 0), reverse=True)
        detail = {
            "station_count": len(items),
            "station_timings": station_timings,
            **({
                "transport": "GetChartDataAwlrArr_minute",
                "chart_5min_count": sum(1 for x in vendor_results if x.get("higertech_path") == "chart_5min"),
                "xlsx_fallback_count": sum(1 for x in vendor_results if x.get("higertech_path") == "xlsx_fallback"),
                "network_day_requests": sum(int(x.get("higertech_network_days") or 0) for x in vendor_results),
                "day_cache_hits": sum(int(x.get("higertech_cache_hits") or 0) for x in vendor_results),
                "raw_5min_points": sum(int(x.get("higertech_raw_points") or 0) for x in vendor_results),
            } if vendor_name == "higertech" else {}),
            **({
                "deadline_ms": round(MONITORING_TATONAS_VENDOR_DEADLINE * 1000.0, 1),
                "deadline_exceeded": vendor_deadline_exceeded,
                "timed_out_station_count": vendor_timed_out_count,
                "completed_station_count": max(0, len(items) - vendor_timed_out_count),
            } if vendor_name == "tatonas" else {}),
        }
        return vendor_results, vendor_warnings, round((time.perf_counter() - vendor_started) * 1000.0, 1), detail

    def run_beacon() -> tuple[list[dict[str, Any]], list[str], float, dict[str, Any]]:
        vendor_started = time.perf_counter()
        res, warn, detail = _monitor_fetch_beacon_group(catalog["beacon"], category, start_dt, end_dt)
        return res, warn, round((time.perf_counter() - vendor_started) * 1000.0, 1), detail

    # Run all vendor groups at the same time. This is important on Vercel: total
    # wall-clock duration becomes approximately the slowest vendor, not the sum
    # of Beacon + Higertech + Tatonas + Dashindo.
    vendor_timings: dict[str, dict[str, Any]] = {}
    jobs: list[tuple[str, list[dict[str, Any]], Any]] = []
    vendor_phase_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor-vendors") as executor:
        if catalog["beacon"]:
            jobs.append(("beacon", catalog["beacon"], executor.submit(run_beacon)))
        for vendor in ("higertech", "tatonas", "dashindo"):
            if catalog[vendor]:
                jobs.append((vendor, catalog[vendor], executor.submit(run_vendor, catalog[vendor])))
        for vendor, vendor_items, future in jobs:
            try:
                if vendor == "beacon":
                    res, warn, elapsed_ms, detail = future.result()
                    vendor_timings[vendor] = {"total_ms": elapsed_ms, **detail}
                else:
                    res, warn, elapsed_ms, detail = future.result()
                    vendor_timings[vendor] = {"total_ms": elapsed_ms, **detail}
                results.extend(res)
                warnings.extend(warn)
            except Exception as exc:
                vendor_timings[vendor] = {"total_ms": None, "station_count": len(vendor_items), "error": str(exc)}
                warnings.append(f"{vendor.title()}: {exc}")
                # Jika satu worker vendor gagal di level grup, tetap materialisasi
                # seluruh posnya sebagai Gagal agar status UI tidak salah menjadi 0.
                results.extend({**st, "series": [], "fetch_failed": True} for st in vendor_items)
    vendor_phase_ms = round((time.perf_counter() - vendor_phase_started) * 1000.0, 1)

    aggregate_started = time.perf_counter()
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
    aggregate_ms = round((time.perf_counter() - aggregate_started) * 1000.0, 1)
    performance = {
        "cache_hit": False,
        "request_total_ms": round((time.perf_counter() - request_started) * 1000.0, 1),
        "metadata_ms": metadata_ms,
        "metadata": metadata_timing,
        "vendor_phase_ms": vendor_phase_ms,
        "vendors": vendor_timings,
        "aggregate_ms": aggregate_ms,
        "result_station_count": len(station_display_names),
    }
    print("[monitoring-perf] " + json.dumps(performance, ensure_ascii=False, separators=(",", ":")))

    response = {
        "ok": True,
        "category": category,
        "resolution": resolution,
        "date_from": date_from,
        "date_to": date_to,
        "effective_start": start_dt.strftime("%Y-%m-%d %H:%M"),
        "effective_end": end_dt.strftime("%Y-%m-%d %H:%M"),
        "hydrological_day": category == "rain",
        "selected_vendors": selected_vendors,
        "periods": selected_view["periods"],
        "period_keys": selected_view["period_keys"],
        "stations": selected_view["stations"],
        "views": views,
        "warnings": warnings[:50],
        "warning_count": len(warnings),
        "failed_count": sum(1 for st, _display_name in station_display_names if st.get("fetch_failed")),
        "performance": performance,
    }
    _MONITORING_CACHE[cache_key] = (time.time(), response)
    if len(_MONITORING_CACHE) > 16:
        oldest = min(_MONITORING_CACHE, key=lambda k: _MONITORING_CACHE[k][0])
        _MONITORING_CACHE.pop(oldest, None)
    return jsonify(response)


