"""Excel download route."""
from __future__ import annotations

import re

import requests
from flask import jsonify, request, send_file

from api.core import (
    BBWS_CLIENT_LOCK,
    EmptyHistoricalData,
    PARAMETER_CACHE,
    app,
    build_xlsx,
    clean_text,
    get_bbws_client,
    source_positions,
)
from api.routes.auth import require_server_access

# ============================================================
# DOWNLOAD
# ============================================================

@app.post(
    "/api/download"
)
def download():

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
        # CACHE FIRST
        # ====================================================

        cached = PARAMETER_CACHE.get(
            id_logger
        )

        if cached:

            params = cached[1]

        else:

            client = get_bbws_client()

            with BBWS_CLIENT_LOCK:

                params = (
                    client.discover_parameters(
                        id_logger
                    )
                )

        allowed = {
            p["id"]: p
            for p in params
        }

        if id_param not in allowed:

            raise RuntimeError(
                "Parameter yang dipilih "
                "tidak tersedia pada pos ini. "
                "Parameter tersedia: "
                + ", ".join(
                    p["name"]
                    for p in params
                )
            )

        # ====================================================
        # FETCH
        # ====================================================

        client = get_bbws_client()

        with BBWS_CLIENT_LOCK:

            headers, rows, title = (
                client.fetch_historical(
                    id_logger=id_logger,
                    id_param=id_param,
                    dari=dari,
                    sampai=sampai,
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

        param_name = allowed[
            id_param
        ]["name"]

        file_obj = build_xlsx(
            pos_name,
            param_name,
            dari,
            sampai,
            title,
            headers,
            rows,
        )

        safe_pos = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            pos_name.replace(
                "Pos ",
                "",
            ),
        )

        safe_param = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            param_name,
        )

        filename = (
            f"{safe_pos}_"
            f"{safe_param}_"
            f"{dari[:10]}_"
            f"{sampai[:10]}.xlsx"
        )

        return send_file(
            file_obj,
            as_attachment=True,
            download_name=filename,
            mimetype=(
                "application/vnd."
                "openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    except EmptyHistoricalData as exc:

        return jsonify(
            {
                "ok": False,
                "empty": True,
                "error": str(exc),
            }
        ), 404

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


