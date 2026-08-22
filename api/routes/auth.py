"""Application access, index, session authentication, and health routes."""
from __future__ import annotations

import hmac
from datetime import datetime

from flask import jsonify, render_template, request, session

from api import core

app = core.app
AUTH_SESSION_VERSION = '2026-08-v7'


def is_server_authenticated() -> bool:
    return session.get('telemetry_access') is True and session.get('telemetry_auth_version') == AUTH_SESSION_VERSION


@app.context_processor
def inject_ui_auth_state():
    """Expose the current telemetry auth state to every rendered template."""
    return {
        "ui_authenticated": is_server_authenticated(),
        "ui_auth_configured": bool(core.APP_PASSWORDS),
    }


def _password_matches(supplied: str) -> bool:
    """Compare against every configured application password without short-circuiting."""
    if not supplied or not core.APP_PASSWORDS:
        return False
    matched = False
    for expected in core.APP_PASSWORDS:
        matched = hmac.compare_digest(supplied, expected) or matched
    return matched


@app.get("/")
def index():
    return render_template(
        "index.html",
        chunk_config={
            "beacon_days": core.BEACON_CHUNK_DAYS,
            "tatonas_months": core.TATONAS_CHUNK_MONTHS,
            "higertech_months": core.HIGERTECH_CHUNK_MONTHS,
            "dashindo_months": core.DASHINDO_CHUNK_MONTHS,
        },
    )


@app.get("/spasial")
def spatial_page():
    return render_template("spatial.html")


def require_server_access():
    if not core.APP_PASSWORDS:
        return jsonify(
            {
                "ok": False,
                "error": "Kata sandi aplikasi belum dikonfigurasi di server.",
            }
        ), 503

    if is_server_authenticated():
        return None

    return jsonify(
        {
            "ok": False,
            "error": "Akses Server Telemetri memerlukan autentikasi aplikasi.",
            "auth_required": True,
        }
    ), 401


@app.get("/api/auth/status")
def auth_status():
    return jsonify(
        {
            "ok": True,
            "authenticated": is_server_authenticated(),
            "configured": bool(core.APP_PASSWORDS),
        }
    )


@app.post("/api/auth/login")
def auth_login():
    if not core.APP_PASSWORDS:
        return jsonify(
            {
                "ok": False,
                "error": "APP_PASSWORDS belum dikonfigurasi.",
            }
        ), 503

    payload = request.get_json(silent=True) or {}
    supplied = str(payload.get("password", ""))

    if not _password_matches(supplied):
        session.pop("telemetry_access", None)
        return jsonify({"ok": False, "error": "Kata sandi aplikasi salah"}), 401

    session.clear()
    session.permanent = False
    session["telemetry_access"] = True
    session["telemetry_auth_version"] = AUTH_SESSION_VERSION
    session["telemetry_access_at"] = datetime.utcnow().isoformat()
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "source": core.BASE_URL,
            "higertech_source": core.HIGERTECH_BASE_URL,
            "credentials_configured": bool(
                core.USERNAME
                and core.PASSWORD
                and not core.USERNAME.startswith("ISI_")
            ),
            "app_access_configured": bool(core.APP_PASSWORDS),
            "parameter_catalog_loaded": len(core.PARAMETER_CACHE),
            "bbws_session_alive": bool(
                core._GLOBAL_BBWS_CLIENT and core._GLOBAL_BBWS_CLIENT.logged_in
            ),
            "performance": {
                "higertech_parallel_workers": core.HIGERTECH_PARALLEL_WORKERS,
                "higertech_export_cache_entries": len(core._HIGERTECH_EXPORT_CACHE),
                "higertech_station_cached": bool(core._HIGERTECH_STATION_CACHE),
                "tatonas_station_cached": bool(core._TATONAS_STATION_CACHE),
                "tatonas_sensor_catalog_cached": bool(core._TATONAS_SENSOR_CATALOG_CACHE),
                "dashindo_station_cached": bool(core._DASHINDO_STATION_CACHE),
                "dashindo_session_cached": bool(core._DASHINDO_AUTH_COOKIES),
                "chunk_limits": {
                    "beacon_days": core.BEACON_CHUNK_DAYS,
                    "tatonas_months": core.TATONAS_CHUNK_MONTHS,
                    "higertech_months": core.HIGERTECH_CHUNK_MONTHS,
                    "dashindo_months": core.DASHINDO_CHUNK_MONTHS,
                },
            },
        }
    )
