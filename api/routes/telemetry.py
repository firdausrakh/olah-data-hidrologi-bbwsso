"""Telemetry metadata and vendor data API routes."""
from __future__ import annotations

import time
from typing import Any

import requests
from flask import jsonify, request

from api.core import (
    BBWS_CLIENT_LOCK,
    CATALOG_WARMING,
    EmptyHistoricalData,
    PARAMETER_CACHE,
    PARAMETER_CACHE_TTL,
    _TATONAS_PARAMETER_CACHE,
    _catalog_ready,
    _higertech_station_by_device,
    _save_vendor_metadata,
    _tatonas_parameters_from_catalog,
    _tatonas_sensor_catalog,
    app,
    clean_text,
    dashindo_data,
    dashindo_parameters_for,
    dashindo_stations,
    get_bbws_client,
    higertech_data,
    higertech_parameters_for,
    higertech_stations,
    parameter_candidates_for_data_type,
    positions_for_data_type,
    source_positions,
    tatonas_data,
    tatonas_parameters,
    tatonas_stations,
)
from api.routes.auth import require_server_access

# ============================================================
# POSITIONS API
# ============================================================

@app.get(
    "/api/positions"
)
def positions():

    auth_error = (
        require_server_access()
    )

    if auth_error:
        return auth_error

    data_type = clean_text(
        request.args.get(
            "data_type",
            "",
        )
    )

    try:

        if data_type in {
            "rain",
            "tma",
        }:

            items = (
                positions_for_data_type(
                    data_type
                )
            )

            return jsonify(
                {
                    "ok": True,
                    "positions": items,
                    "ready": _catalog_ready(
                        data_type
                    ),
                    "warming": (
                        data_type
                        in CATALOG_WARMING
                    ),
                }
            )

        items = source_positions()

        return jsonify(
            {
                "ok": True,
                "positions": items,
                "ready": True,
                "warming": False,
            }
        )

    except Exception as exc:

        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500


# ============================================================
# PARAMETERS API
# ============================================================

@app.get(
    "/api/parameters"
)
def parameters():

    auth_error = (
        require_server_access()
    )

    if auth_error:
        return auth_error

    id_logger = clean_text(
        request.args.get(
            "id_logger",
            "",
        )
    )

    data_type = clean_text(
        request.args.get(
            "data_type",
            "",
        )
    )

    if not id_logger:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "id_logger wajib diisi."
                ),
            }
        ), 400

    # ========================================================
    # CACHE FIRST
    # ========================================================

    cached = PARAMETER_CACHE.get(
        id_logger
    )

    if cached:

        age = (
            time.time()
            - cached[0]
        )

        if age < PARAMETER_CACHE_TTL:

            all_params = cached[1]

            filtered = (
                parameter_candidates_for_data_type(
                    all_params,
                    data_type,
                )
            )

            return jsonify(
                {
                    "ok": True,
                    "parameters": filtered,
                    "all_parameters": all_params,
                    "cached": True,
                }
            )

    # ========================================================
    # LIVE DISCOVERY
    # ========================================================

    try:

        client = get_bbws_client()

        with BBWS_CLIENT_LOCK:

            all_params = (
                client.discover_parameters(
                    id_logger
                )
            )

        filtered = (
            parameter_candidates_for_data_type(
                all_params,
                data_type,
            )
        )

        return jsonify(
            {
                "ok": True,
                "parameters": filtered,
                "all_parameters": all_params,
                "cached": False,
            }
        )

    except requests.RequestException as exc:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Gagal mengakses "
                    f"server BBWS: {exc}"
                ),
            }
        ), 502

    except Exception as exc:

        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500


# ============================================================
# BEACON DATA
# ============================================================

@app.post(
    "/api/beacon/data"
)
def beacon_data():

    auth_error = (
        require_server_access()
    )

    if auth_error:
        return auth_error

    payload = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    id_logger = clean_text(
        str(
            payload.get(
                "id_logger",
                "",
            )
        )
    )

    id_param = clean_text(
        str(
            payload.get(
                "id_param",
                "",
            )
        )
    )

    dari = clean_text(
        str(
            payload.get(
                "dari",
                "",
            )
        )
    )

    sampai = clean_text(
        str(
            payload.get(
                "sampai",
                "",
            )
        )
    )

    data_type = clean_text(
        str(
            payload.get(
                "data_type",
                "",
            )
        )
    )

    period_mode = clean_text(
        str(
            payload.get(
                "period_mode",
                "",
            )
        )
    )

    if not all(
        [
            id_logger,
            id_param,
            dari,
            sampai,
        ]
    ):

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Pos, parameter, "
                    "tanggal mulai, dan "
                    "tanggal akhir "
                    "wajib diisi."
                ),
            }
        ), 400

    try:

        # ====================================================
        # PARAMETER CACHE FIRST
        # ====================================================
        #
        # TIDAK lagi discover parameter
        # setiap pengambilan data.
        #
        # ====================================================

        cached = PARAMETER_CACHE.get(
            id_logger
        )

        if cached:

            all_params = cached[1]

        else:

            client = get_bbws_client()

            with BBWS_CLIENT_LOCK:

                all_params = (
                    client.discover_parameters(
                        id_logger
                    )
                )

        allowed = {
            p["id"]: p
            for p in all_params
        }

        if id_param not in allowed:

            raise RuntimeError(
                "Parameter yang dipilih "
                "tidak tersedia pada pos ini. "
                "Parameter tersedia: "
                + ", ".join(
                    p["name"]
                    for p in all_params
                )
            )

        # ====================================================
        # HISTORICAL
        # ====================================================

        client = get_bbws_client()

        with BBWS_CLIENT_LOCK:

            headers, rows, title = (
                client.fetch_historical(
                    id_logger=id_logger,
                    id_param=id_param,
                    dari=dari,
                    sampai=sampai,
                    period_mode=period_mode,
                    parameter_name=allowed[id_param]["name"],
                )
            )

        pos_name = next(
            (
                p["name"]
                for p in source_positions()
                if p["id_logger"]
                == id_logger
            ),
            id_logger,
        )

        return jsonify(
            {
                "ok": True,
                "headers": headers,
                "rows": rows,
                "title": title,
                "pos_name": pos_name,
                "parameter": allowed[
                    id_param
                ],
            }
        )

    except EmptyHistoricalData as exc:

        # EMPTY = 200 dengan flag empty.
        #
        # Bukan 500.
        # Bukan server error.

        return jsonify(
            {
                "ok": True,
                "empty": True,
                "headers": [],
                "rows": [],
                "title": (
                    "Tidak ada data"
                ),
                "message": str(exc),
            }
        )

    except requests.RequestException as exc:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Gagal terhubung "
                    "ke sumber BBWS: "
                    f"{exc}"
                ),
            }
        ), 502

    except Exception as exc:

        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500


# ============================================================
# HIGERTECH POSITIONS / PARAMETERS / DATA
# ============================================================

@app.get("/api/higertech/positions")
def higertech_positions_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    data_type = clean_text(request.args.get("data_type", ""))
    try:
        allowed_types = {"AWLR_ARR"}
        if data_type == "rain":
            allowed_types.update({"ARR", "AWS"})
        elif data_type == "tma":
            allowed_types.update({"AWLR"})
        items = [
            {
                "id_logger": station["deviceId"],
                "name": station["name"],
                "device_id": station["deviceId"],
                "station_type": station["type"],
                # Parameter Higertech bersifat statis per jenis data; embed agar
                # pemilihan pos tidak membutuhkan round-trip /parameters lagi.
                "parameters": higertech_parameters_for(data_type),
            }
            for station in higertech_stations()
            if station["type"] in allowed_types
        ]
        return jsonify({"ok": True, "positions": items, "ready": True, "warming": False})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/higertech/parameters")
def higertech_parameters_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    device_id = clean_text(request.args.get("id_logger", ""))
    data_type = clean_text(request.args.get("data_type", ""))
    if not device_id:
        return jsonify({"ok": False, "error": "Device ID wajib diisi."}), 400
    try:
        _higertech_station_by_device(device_id)
        params = higertech_parameters_for(data_type)
        return jsonify({"ok": True, "parameters": params, "all_parameters": params, "cached": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/higertech/data")
def higertech_data_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or request.form
    device_id = clean_text(str(payload.get("id_logger", "")))
    id_param = clean_text(str(payload.get("id_param", "")))
    dari = clean_text(str(payload.get("dari", "")))
    sampai = clean_text(str(payload.get("sampai", "")))
    data_type = clean_text(str(payload.get("data_type", "")))
    if not all([device_id, id_param, dari, sampai]):
        return jsonify({"ok": False, "error": "Pos, parameter, dan periode wajib diisi."}), 400
    try:
        allowed = {p["id"]: p for p in higertech_parameters_for(data_type)}
        if id_param not in allowed:
            raise RuntimeError("Parameter Higertech tidak sesuai dengan jenis data yang dipilih.")
        headers, rows, station = higertech_data(device_id, dari, sampai, id_param)
        return jsonify({
            "ok": True,
            "empty": not bool(rows),
            "headers": headers,
            "rows": rows,
            "title": f'{station["name"]} - {allowed[id_param]["name"]}',
            "pos_name": station["name"],
            "parameter": allowed[id_param],
        })
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"Gagal terhubung ke Higertech: {exc}"}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500



# ============================================================
# DASHINDO POSITIONS / PARAMETERS / DATA
# ============================================================

@app.get("/api/dashindo/positions")
def dashindo_positions_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error

    data_type = clean_text(
        request.args.get("data_type", "")
    )
    try:
        # The identified Dashindo source is AWLR only.
        stations = (
            dashindo_stations()
            if data_type == "tma"
            else []
        )

        items = []
        for station in stations:
            params = dashindo_parameters_for(
                str(station["id"]),
                data_type,
            )
            items.append({
                # Sensor ID is unique and avoids the SOWL008/tma+tma2 collision.
                "id_logger": str(station["id"]),
                "name": station["name"],
                "device_id": station["device"],
                "station_type": "AWLR",
                "parameters": params,
            })

        return jsonify({
            "ok": True,
            "positions": items,
            "ready": True,
            "warming": False,
            "supported_data_types": ["tma"],
        })
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": (
                "Gagal terhubung ke Dashindo: "
                f"{exc}"
            ),
        }), 502
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.get("/api/dashindo/parameters")
def dashindo_parameters_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error

    sensor_id = clean_text(
        request.args.get("id_logger", "")
    )
    data_type = clean_text(
        request.args.get("data_type", "")
    )
    if not sensor_id:
        return jsonify({
            "ok": False,
            "error": "ID Sensor Dashindo wajib diisi.",
        }), 400

    try:
        params = dashindo_parameters_for(
            sensor_id,
            data_type,
        )
        return jsonify({
            "ok": True,
            "parameters": params,
            "all_parameters": params,
            "cached": True,
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.post("/api/dashindo/data")
def dashindo_data_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error

    payload = (
        request.get_json(silent=True)
        or request.form
    )
    sensor_id = clean_text(
        str(payload.get("id_logger", ""))
    )
    field = clean_text(
        str(payload.get("id_param", ""))
    )
    dari = clean_text(
        str(payload.get("dari", ""))
    )
    sampai = clean_text(
        str(payload.get("sampai", ""))
    )
    data_type = clean_text(
        str(payload.get("data_type", ""))
    )

    if not all([
        sensor_id,
        field,
        dari,
        sampai,
    ]):
        return jsonify({
            "ok": False,
            "error": (
                "Pos, parameter, dan periode "
                "Dashindo wajib diisi."
            ),
        }), 400

    if data_type != "tma":
        return jsonify({
            "ok": False,
            "error": (
                "Integrasi server Dashindo saat ini "
                "tersedia untuk Tinggi Muka Air (AWLR)."
            ),
        }), 400

    try:
        headers, rows, station, parameter = (
            dashindo_data(
                sensor_id=sensor_id,
                field=field,
                dari=dari,
                sampai=sampai,
            )
        )
        return jsonify({
            "ok": True,
            "empty": not bool(rows),
            "headers": headers,
            "rows": rows,
            "title": (
                f'{station["name"]} - '
                f'{parameter["name"]}'
            ),
            "pos_name": station["name"],
            "parameter": parameter,
        })
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": (
                "Gagal terhubung ke Dashindo: "
                f"{exc}"
            ),
        }), 502
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


# ============================================================
# TATONAS POSITIONS / PARAMETERS / DATA
# ============================================================

@app.get("/api/tatonas/positions")
def tatonas_positions_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    data_type = clean_text(request.args.get("data_type", ""))
    try:
        stations = tatonas_stations()
        if data_type == "tma":
            stations = [s for s in stations if s.get("station_type") == "water_level"]
        elif data_type == "rain":
            stations = [s for s in stations if s.get("station_type") != "water_level"]

        # One plant-level metadata request is enough for every current/future
        # station. Embedding the small parameter list lets the browser switch
        # Tatonas positions without another round trip.
        catalog: list[dict[str, Any]] = []
        missing_param_metadata = any(str(st.get("kd_hardware")) not in _TATONAS_PARAMETER_CACHE for st in stations)
        if missing_param_metadata:
            try:
                catalog = _tatonas_sensor_catalog()
            except Exception:
                # Persisted per-station metadata remains usable when upstream
                # metadata is temporarily unavailable.
                catalog = []

        items = []
        for station in stations:
            hw = str(station["kd_hardware"])
            cached_params = _TATONAS_PARAMETER_CACHE.get(hw)
            params = cached_params[1] if cached_params else (
                _tatonas_parameters_from_catalog(hw, catalog, station=station) if catalog else []
            )
            if params:
                _TATONAS_PARAMETER_CACHE[hw] = (time.time(), params)
            items.append({
                "id_logger": hw,
                "name": station.get("name") or hw,
                "device_id": hw,
                "station_type": station.get("station_type", "unknown"),
                "parameters": params,
            })
        if _TATONAS_PARAMETER_CACHE:
            _save_vendor_metadata(
                "tatonas", "parameter_catalog.json",
                {key: value[1] for key, value in _TATONAS_PARAMETER_CACHE.items()},
            )
        return jsonify({"ok": True, "positions": items, "ready": True, "warming": False})
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"Gagal terhubung ke Tatonas: {exc}"}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/tatonas/parameters")
def tatonas_parameters_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    hw = clean_text(request.args.get("id_logger", ""))
    dari = clean_text(request.args.get("dari", ""))
    sampai = clean_text(request.args.get("sampai", ""))
    if not hw:
        return jsonify({"ok": False, "error": "Hardware Tatonas wajib diisi."}), 400
    try:
        params = tatonas_parameters(hw, dari=dari, sampai=sampai)
        return jsonify({"ok": True, "parameters": params, "all_parameters": params, "cached": hw in _TATONAS_PARAMETER_CACHE})
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"Gagal terhubung ke Tatonas: {exc}"}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/tatonas/data")
def tatonas_data_api():
    auth_error = require_server_access()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or request.form
    hw = clean_text(str(payload.get("id_logger", "")))
    sensor_id = clean_text(str(payload.get("id_param", "")))
    dari = clean_text(str(payload.get("dari", "")))
    sampai = clean_text(str(payload.get("sampai", "")))
    if not all([hw, sensor_id, dari, sampai]):
        return jsonify({"ok": False, "error": "Pos, parameter, dan periode wajib diisi."}), 400
    try:
        headers, rows, station, parameter = tatonas_data(hw, dari, sampai, sensor_id)
        return jsonify({
            "ok": True,
            "empty": not bool(rows),
            "headers": headers,
            "rows": rows,
            "title": f'{station.get("name", hw)} - {parameter["name"]}',
            "pos_name": station.get("name", hw),
            "parameter": parameter,
        })
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"Gagal terhubung ke Tatonas: {exc}"}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500



