"""Unified monitoring data helpers shared by the monitoring routes."""
from __future__ import annotations

import html as html_lib
import base64
import json
import re
import threading
import time

import requests
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
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
    tatonas_parameters,
    tatonas_stations,
)

# ============================================================
# UNIFIED MONITORING (SEPARATE PAGE)
# ============================================================

_MONITORING_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
MONITORING_CACHE_TTL = int(get_config("MONITORING_CACHE_TTL", 5 * 60))
MONITORING_BEACON_WORKERS = max(1, min(5, int(get_config("MONITORING_BEACON_WORKERS", 4))))
MONITORING_BEACON_CHUNK_WORKERS = max(1, min(8, int(get_config("MONITORING_BEACON_CHUNK_WORKERS", 6))))
MONITORING_BEACON_BULK_DAYS = max(1, min(10, int(get_config("MONITORING_BEACON_BULK_DAYS", 7))))
MONITORING_BEACON_BULK_WORKERS = max(1, min(3, int(get_config("MONITORING_BEACON_BULK_WORKERS", 3))))
MONITORING_BEACON_BULK_LONG_THRESHOLD = max(8, min(31, int(get_config("MONITORING_BEACON_BULK_LONG_THRESHOLD", 15))))
MONITORING_BEACON_BULK_LONG_DAYS = max(4, min(10, int(get_config("MONITORING_BEACON_BULK_LONG_DAYS", 8))))
MONITORING_BEACON_BULK_LONG_WORKERS = max(2, min(5, int(get_config("MONITORING_BEACON_BULK_LONG_WORKERS", 4))))
MONITORING_BEACON_METADATA_TTL = max(60, int(get_config("MONITORING_BEACON_METADATA_TTL", 6 * 60 * 60)))
MONITORING_BEACON_SESSION_TTL = max(60, int(get_config("MONITORING_BEACON_SESSION_TTL", 15 * 60)))
MONITORING_BEACON_TOKEN_TTL = max(30, min(600, int(get_config("MONITORING_BEACON_TOKEN_TTL", 5 * 60))))

# Higertech Monitoring uses the lightweight chart endpoint with native 5-minute
# points. Pengolahan V26 now uses the same raw resolution through core.py, with
# its own cache/worker profile and XLSX reliability fallback.
MONITORING_HIGERTECH_DAY_WORKERS = max(1, min(8, int(get_config("MONITORING_HIGERTECH_DAY_WORKERS", 4))))
MONITORING_HIGERTECH_TIMEOUT = max(2.0, min(20.0, float(get_config("MONITORING_HIGERTECH_TIMEOUT", 8))))
MONITORING_HIGERTECH_DAY_CACHE_TTL = max(30, min(60 * 60, int(get_config("MONITORING_HIGERTECH_DAY_CACHE_TTL", 10 * 60))))
MONITORING_HIGERTECH_TODAY_CACHE_TTL = max(15, min(5 * 60, int(get_config("MONITORING_HIGERTECH_TODAY_CACHE_TTL", 60))))
HIGERTECH_MONITOR_CHART_URL = f"{core.HIGERTECH_BASE_URL}/Station/GetChartDataAwlrArr"

# Monitoring must fail fast when one Tatonas logger is slow/unavailable.
# These settings are deliberately separate from the Olah Data Tatonas adapter;
# api/core.py keeps its more patient retry/split behaviour unchanged.
MONITORING_TATONAS_WORKERS = max(1, min(4, int(get_config("MONITORING_TATONAS_WORKERS", 4))))
MONITORING_TATONAS_CONNECT_TIMEOUT = max(2.0, min(10.0, float(get_config("MONITORING_TATONAS_CONNECT_TIMEOUT", 4))))
MONITORING_TATONAS_TIMEOUT = max(5.0, min(30.0, float(get_config("MONITORING_TATONAS_TIMEOUT", 12))))
MONITORING_TATONAS_RETRIES = max(0, min(1, int(get_config("MONITORING_TATONAS_RETRIES", 0))))
MONITORING_TATONAS_VENDOR_DEADLINE = max(5.0, min(30.0, float(get_config("MONITORING_TATONAS_VENDOR_DEADLINE", 15))))

# Dashindo Monitoring uses persistent Engine.IO connections per worker batch.
# Pengolahan V26 separately uses raw get_n_data (not hourly) with CSV fallback.
MONITORING_DASHINDO_WORKERS = max(1, min(8, int(get_config("MONITORING_DASHINDO_WORKERS", 6))))
MONITORING_DASHINDO_CONNECT_TIMEOUT = max(2.0, min(10.0, float(get_config("MONITORING_DASHINDO_CONNECT_TIMEOUT", 4))))
MONITORING_DASHINDO_READ_TIMEOUT = max(4.0, min(20.0, float(get_config("MONITORING_DASHINDO_READ_TIMEOUT", 8))))
MONITORING_DASHINDO_EVENT_TIMEOUT = max(4.0, min(20.0, float(get_config("MONITORING_DASHINDO_EVENT_TIMEOUT", 8))))
MONITORING_DASHINDO_VENDOR_DEADLINE = max(8.0, min(30.0, float(get_config("MONITORING_DASHINDO_VENDOR_DEADLINE", 15))))

_BEACON_SELECTOR_LOCK = threading.RLock()
_BEACON_SELECTOR_CACHE: tuple[float, dict[tuple[str, str], str]] = (0.0, {})

# Monitoring-only Beacon auth cache.  This intentionally lives outside
# api/core.py so the proven Olah Data flow is not changed.  It is used only
# for a single native /monitoring bulk period where sharing one upstream
# session is safe; multi-chunk bulk still keeps isolated sessions because
# /monitoring category/date state is session-scoped.
_BEACON_MONITOR_AUTH_LOCK = threading.RLock()
_BEACON_MONITOR_AUTH_COOKIES: dict[str, str] = {}
_BEACON_MONITOR_AUTH_AT = 0.0

# Short-lived Monitoring-only token cache.  Tokens created by
# /analisa/set_sensordash are parameter-specific.  Cache entries are bound to
# the Monitoring auth epoch so a login refresh automatically invalidates them.
# Olah Data never reads this cache.
_BEACON_TOKEN_LOCK = threading.RLock()
_BEACON_TOKEN_CACHE: dict[tuple[str, str], tuple[float, float, str, str]] = {}

# Daily native 5-minute chart cache for Monitoring Higertech only. Historical
# days can be reused longer; today's partial day gets a short freshness TTL.
_HIGERTECH_MONITOR_DAY_LOCK = threading.RLock()
_HIGERTECH_MONITOR_DAY_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


def _beacon_monitor_cached_client(*, force: bool = False) -> BBWSSession:
    """Return a Monitoring-only authenticated Beacon client from warm cookies.

    On a warm Flask/Vercel instance this removes the GET /login + POST login
    round-trip from the common 1-7 day Monitoring request.  The cache may also
    seed itself from core._GLOBAL_BBWS_CLIENT if Olah Data already authenticated
    upstream.  The returned requests.Session is always a fresh local pool.
    """
    global _BEACON_MONITOR_AUTH_COOKIES, _BEACON_MONITOR_AUTH_AT, _BEACON_TOKEN_CACHE
    now = time.time()
    with _BEACON_MONITOR_AUTH_LOCK:
        if force:
            _BEACON_MONITOR_AUTH_COOKIES = {}
            _BEACON_MONITOR_AUTH_AT = 0.0
            with _BEACON_TOKEN_LOCK:
                _BEACON_TOKEN_CACHE = {}

        if not _BEACON_MONITOR_AUTH_COOKIES:
            warm = getattr(core, "_GLOBAL_BBWS_CLIENT", None)
            if (
                warm is not None
                and getattr(warm, "logged_in", False)
                and getattr(warm, "last_login_at", 0.0)
                and now - float(warm.last_login_at) < MONITORING_BEACON_SESSION_TTL
            ):
                _BEACON_MONITOR_AUTH_COOKIES = requests.utils.dict_from_cookiejar(warm.session.cookies)
                _BEACON_MONITOR_AUTH_AT = float(warm.last_login_at)

        if (
            not force
            and _BEACON_MONITOR_AUTH_COOKIES
            and now - _BEACON_MONITOR_AUTH_AT < MONITORING_BEACON_SESSION_TTL
        ):
            client = BBWSSession()
            client.session.cookies.update(_BEACON_MONITOR_AUTH_COOKIES)
            client.logged_in = True
            client.last_login_at = _BEACON_MONITOR_AUTH_AT
            client.current_url = f"{core.BASE_URL}/beranda"
            return client

        master = BBWSSession()
        master.login()
        _BEACON_MONITOR_AUTH_COOKIES = requests.utils.dict_from_cookiejar(master.session.cookies)
        _BEACON_MONITOR_AUTH_AT = time.time()
        return master


def _beacon_token_cache_get(logger_id: str, param_id: str) -> tuple[str, str] | None:
    now = time.time()
    key = (str(logger_id), str(param_id))
    with _BEACON_TOKEN_LOCK:
        item = _BEACON_TOKEN_CACHE.get(key)
        if not item:
            return None
        created_at, auth_at, token, current_url = item
        if (
            now - created_at >= MONITORING_BEACON_TOKEN_TTL
            or not _BEACON_MONITOR_AUTH_AT
            or abs(auth_at - _BEACON_MONITOR_AUTH_AT) > 0.001
        ):
            _BEACON_TOKEN_CACHE.pop(key, None)
            return None
        return token, current_url


def _beacon_token_cache_put(logger_id: str, param_id: str, token: str, current_url: str) -> None:
    if not token or not _BEACON_MONITOR_AUTH_AT:
        return
    with _BEACON_TOKEN_LOCK:
        _BEACON_TOKEN_CACHE[(str(logger_id), str(param_id))] = (
            time.time(),
            _BEACON_MONITOR_AUTH_AT,
            str(token),
            str(current_url),
        )


def _beacon_token_cache_drop(logger_id: str, param_id: str) -> None:
    with _BEACON_TOKEN_LOCK:
        _BEACON_TOKEN_CACHE.pop((str(logger_id), str(param_id)), None)


def _beacon_selector_cached_only() -> dict[tuple[str, str], str]:
    """Return /beranda selector metadata only when already warm.

    Standard BBWS/PSDA selectors can be synthesized from logger+parameter IDs.
    Therefore Monitoring no longer blocks on an extra /beranda request during a
    cold supplement.  If a synthesized selector ever fails, exact fetch retries
    once using a real /beranda snapshot.
    """
    now = time.time()
    with _BEACON_SELECTOR_LOCK:
        cached_at, cached_map = _BEACON_SELECTOR_CACHE
        if cached_map and now - cached_at < MONITORING_BEACON_METADATA_TTL:
            return dict(cached_map)
    return {}


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


def _monitor_station_catalog(
    category: str,
    selected_vendors: set[str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build only selected vendor catalogs and report wall-clock timings.

    The Monitoring logger filter is a request filter, not merely a display
    filter: vendors excluded here are never contacted for metadata or data.
    """
    started = time.perf_counter()
    catalog: dict[str, list[dict[str, Any]]] = {"beacon": [], "higertech": [], "tatonas": [], "dashindo": []}
    vendor_timings: dict[str, float] = {}

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
                # Monitoring-only transport hints.  Keeping these here avoids
                # another station lookup before each Socket.IO download.
                "dashindo_device": st.get("device"),
                "dashindo_field": st.get("field"),
                "dashindo_unit": st.get("unit") or "m",
            })
        return out

    builders = {
        "beacon": beacon_catalog, "higertech": higer_catalog,
        "tatonas": tatonas_catalog, "dashindo": dashindo_catalog,
    }
    enabled = set(builders) if selected_vendors is None else {v for v in selected_vendors if v in builders}
    builders = {vendor: fn for vendor, fn in builders.items() if vendor in enabled}

    def timed_builder(fn: Any) -> tuple[list[dict[str, Any]], float, str | None]:
        t0 = time.perf_counter()
        try:
            return fn(), (time.perf_counter() - t0) * 1000.0, None
        except Exception as exc:
            return [], (time.perf_counter() - t0) * 1000.0, str(exc)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor-meta") as executor:
        futures = {executor.submit(timed_builder, fn): vendor for vendor, fn in builders.items()}
        for future in as_completed(futures):
            vendor = futures[future]
            items, elapsed_ms, error = future.result()
            vendor_timings[vendor] = round(elapsed_ms, 1)
            if error:
                # Keep one vendor metadata failure from hiding all other vendors.
                print(f"Metadata monitoring {vendor} gagal: {error}")
                catalog[vendor] = []
            else:
                catalog[vendor] = items

    for items in catalog.values():
        items.sort(key=lambda x: str(x.get("name", "")).casefold())
    timing = {
        "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "vendors_ms": vendor_timings,
        "counts": {vendor: len(items) for vendor, items in catalog.items()},
        "selected_vendors": sorted(enabled),
    }
    return catalog, timing


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


def _monitor_fetch_tatonas_fast(
    st: dict[str, Any],
    category: str,
    start_dt: datetime,
    end_dt: datetime,
    param: dict[str, Any],
    *,
    deadline_at: float | None = None,
) -> dict[str, Any]:
    """Monitoring-only Tatonas fetch with a short timeout and no recursive split.

    Olah Data continues to call api.core.tatonas_data(), including its existing
    retry and timeout-splitting behaviour.  Monitoring instead prioritises a
    partial result: a slow logger is marked failed quickly so it cannot keep the
    whole multi-vendor dashboard waiting for minutes.
    """
    hw = str(st["id_logger"])
    requested = core._tatonas_slug(param.get("id"))
    chunks = core._split_datetime_month_chunks(start_dt, end_dt, core.TATONAS_CHUNK_MONTHS)
    rows: list[list[Any]] = []
    returned_param = dict(param)

    for chunk_start, chunk_end in chunks:
        safe_from, safe_to = core._tatonas_clamp_range(
            chunk_start.strftime("%Y-%m-%d %H:%M"),
            chunk_end.strftime("%Y-%m-%d %H:%M"),
        )
        query = {
            "hw": hw,
            "plant": core.TATONAS_PLANT,
            "t1": core._tatonas_format_datetime(safe_from),
            "t2": core._tatonas_format_datetime(safe_to),
            "vq": "Perjam",
        }

        last_exc: Exception | None = None
        payload: Any = None
        for attempt in range(MONITORING_TATONAS_RETRIES + 1):
            # A request-level timeout alone is not enough when many Tatonas
            # stations are queued.  Respect the vendor-wide Monitoring deadline
            # as well, and shrink the HTTP timeout to the time still available.
            if deadline_at is not None:
                remaining = deadline_at - time.perf_counter()
                if remaining < 1.0:
                    raise RuntimeError(
                        f"Tatonas melewati batas waktu total Monitoring "
                        f"{MONITORING_TATONAS_VENDOR_DEADLINE:g} dtk."
                    )
                connect_timeout = min(
                    MONITORING_TATONAS_CONNECT_TIMEOUT,
                    max(0.25, remaining * 0.25),
                )
                read_timeout = min(
                    MONITORING_TATONAS_TIMEOUT,
                    max(0.5, remaining - connect_timeout),
                )
            else:
                connect_timeout = MONITORING_TATONAS_CONNECT_TIMEOUT
                read_timeout = MONITORING_TATONAS_TIMEOUT

            try:
                client = core._tatonas_clone_authenticated_session()
                response = client.get(
                    core.TATONAS_DATA_URL,
                    params=query,
                    headers=core._tatonas_ajax_headers(
                        client,
                        "",
                        json_accept=True,
                        referer_url=core.TATONAS_RAW_PAGE_URL,
                    ),
                    timeout=(connect_timeout, read_timeout),
                    allow_redirects=True,
                )
                if response.status_code in (401, 403) or core._tatonas_is_login_page(response.text, response.url):
                    raise RuntimeError("Sesi Tatonas kedaluwarsa pada Monitoring.")
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError("Response data Tatonas bukan JSON.") from exc
                last_exc = None
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = RuntimeError(
                    f"Tatonas fast-fail setelah {MONITORING_TATONAS_TIMEOUT:g} dtk: {exc}"
                )
            except Exception as exc:
                last_exc = exc
            if attempt < MONITORING_TATONAS_RETRIES:
                if deadline_at is not None and deadline_at - time.perf_counter() <= 0.2:
                    break
                time.sleep(0.15)

        if last_exc is not None:
            raise last_exc

        sensors, timestamps = core._tatonas_normalize_sensor_payload(payload, query["t1"], "Perjam")
        selected = next(
            (
                sensor for sensor in sensors
                if requested in {
                    core._tatonas_slug(sensor.get("id")),
                    core._tatonas_slug(sensor.get("sensor_code")),
                }
            ),
            None,
        )
        if selected is None and requested in {"rainfall", "curahhujan", "curah_hujan", "rain", "precipitation"}:
            selected = next(
                (
                    sensor for sensor in sensors
                    if core._tatonas_slug((sensor.get("properties") or {}).get("kd_type")) == "rain"
                    or core._tatonas_slug(sensor.get("sensor_code")) in {"rainfall", "curahhujan"}
                ),
                None,
            )

        # Metadata is the source of truth for channel availability.  A sparse
        # period may legitimately omit a valid channel, so that chunk is empty
        # rather than an error.
        if selected is None:
            continue

        label = clean_text(str(selected.get("name") or param.get("name") or param.get("id") or "Data"))
        source_unit = clean_text(str(selected.get("unit") or param.get("source_unit") or param.get("unit") or ""))
        returned_param = {
            **param,
            "id": selected.get("id") or param.get("id"),
            "name": "Tinggi Muka Air" if category == "tma" else label,
            "type": "tma" if category == "tma" else param.get("type", "sensor"),
            "unit": "m" if category == "tma" else (selected.get("unit") or param.get("unit") or ""),
            # Preserve cm so _monitor_parse_rows performs the same one-time
            # conversion as the existing Tatonas monitoring path.
            "source_unit": param.get("source_unit") or ("cm" if category == "tma" else source_unit),
        }

        values = selected.get("values") or []
        count = min(len(timestamps), len(values))
        for idx in range(count):
            value = values[idx]
            if value is None or clean_text(str(value)) == "":
                continue
            dt = _parse_any_datetime(timestamps[idx])
            stamp = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else clean_text(str(timestamps[idx]))
            rows.append([stamp, value])

    series = _monitor_parse_rows(rows, category, "tatonas", returned_param)
    return {**st, "parameter": returned_param, "series": series, "tatonas_path": "monitor_fast_fail"}



class _MonitorDashindoEngineIO(core._DashindoEngineIO):
    """Monitoring-only Engine.IO client with short request timeouts."""

    def open(self) -> None:
        self._log("handshake EIO=4 (monitor)")
        response = self.http.get(
            f"{core.DASHINDO_SOCKET_URL}/socket.io/",
            params=self._params(include_sid=False),
            headers=self._headers(),
            timeout=(MONITORING_DASHINDO_CONNECT_TIMEOUT, MONITORING_DASHINDO_READ_TIMEOUT),
        )
        response.raise_for_status()
        text = response.text.lstrip("\ufeff").strip()
        if not text.startswith("0"):
            raise core.DashindoError(
                "Handshake Engine.IO Dashindo tidak valid. "
                f"Body awal: {text[:160]!r}"
            )
        try:
            payload = json.loads(text[1:])
        except Exception as exc:
            raise core.DashindoError("Handshake Engine.IO Dashindo tidak dapat diparse.") from exc
        sid = payload.get("sid")
        if not sid:
            raise core.DashindoError("Handshake Engine.IO Dashindo tidak memiliki SID.")
        self.sid = str(sid)
        self.ping_interval_ms = int(payload.get("pingInterval", 25000))
        self.ping_timeout_ms = int(payload.get("pingTimeout", 20000))
        self._log("SID diterima (monitor)")

    def post_raw(self, packet: str) -> None:
        if not self.sid:
            raise core.DashindoError("Engine.IO Dashindo belum memiliki SID.")
        response = self.http.post(
            f"{core.DASHINDO_SOCKET_URL}/socket.io/",
            params=self._params(),
            data=packet.encode("utf-8"),
            headers=self._headers(post=True),
            timeout=(MONITORING_DASHINDO_CONNECT_TIMEOUT, MONITORING_DASHINDO_READ_TIMEOUT),
        )
        response.raise_for_status()

    def get_raw(self, timeout: int) -> str:
        if not self.sid:
            raise core.DashindoError("Engine.IO Dashindo belum memiliki SID.")
        read_timeout = max(1.0, min(float(timeout), MONITORING_DASHINDO_READ_TIMEOUT))
        response = self.http.get(
            f"{core.DASHINDO_SOCKET_URL}/socket.io/",
            params=self._params(),
            headers=self._headers(),
            timeout=(MONITORING_DASHINDO_CONNECT_TIMEOUT, read_timeout),
        )
        response.raise_for_status()
        return response.text.lstrip("\ufeff")


def _monitor_dashindo_auth(client: requests.Session, key: str) -> Any:
    response = client.post(
        f"{core.DASHINDO_BASE_URL}/dashboard/API/websocket-auth.php",
        data={"s": key},
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": core.DASHINDO_BASE_URL,
            "Referer": f"{core.DASHINDO_BASE_URL}/dashboard/awlr.php",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=(MONITORING_DASHINDO_CONNECT_TIMEOUT, MONITORING_DASHINDO_READ_TIMEOUT),
    )
    response.raise_for_status()
    payload = core._dashindo_json_lenient(response.text)
    if not isinstance(payload, dict) or "data" not in payload:
        raise core.DashindoError("websocket-auth.php Dashindo tidak mengembalikan data autentikasi.")
    return payload["data"]


def _monitor_dashindo_open_engine(deadline_at: float) -> tuple[requests.Session, _MonitorDashindoEngineIO]:
    if time.monotonic() >= deadline_at:
        raise core.DashindoError("Batas waktu total Dashindo Monitoring tercapai sebelum koneksi dibuka.")
    client = core._dashindo_login()
    engine = _MonitorDashindoEngineIO(client, [])
    engine.open()
    engine.post_raw("40")
    event_deadline = min(deadline_at, time.monotonic() + MONITORING_DASHINDO_EVENT_TIMEOUT)
    _event, ehlo = engine.poll_until({"ehlo"}, event_deadline)
    if not isinstance(ehlo, dict) or not ehlo.get("key"):
        raise core.DashindoError("Event ehlo Dashindo tidak memiliki key.")
    auth_data = _monitor_dashindo_auth(client, str(ehlo["key"]))
    engine.send_event("message", auth_data)
    engine.poll_until({"auth"}, min(deadline_at, time.monotonic() + MONITORING_DASHINDO_EVENT_TIMEOUT))
    return client, engine


def _monitor_dashindo_station_device_field(st: dict[str, Any]) -> tuple[str, str]:
    """Resolve the Dashindo device/field pair without touching Olah Data."""
    device = clean_text(str(st.get("dashindo_device") or ""))
    field = clean_text(str(st.get("dashindo_field") or (st.get("parameter") or {}).get("id") or ""))
    if not device or not field:
        station = core._dashindo_station(str(st.get("id_logger") or ""))
        device = clean_text(str(station.get("device") or ""))
        field = clean_text(str(station.get("field") or ""))
    if not device or not field:
        raise core.DashindoError("Device/field Dashindo Monitoring tidak tersedia.")
    return device, field


def _monitor_dashindo_rows_from_n_data(
    data: Any,
    *,
    start_dt: datetime,
    end_dt: datetime,
) -> list[list[Any]]:
    """Convert Dashindo's direct ``n_data`` payload to Monitoring rows.

    The vendor's sensor-table JavaScript renders ``message.times`` directly in
    the UI (no timezone conversion), so Monitoring keeps these timestamps as
    delivered.  This is intentionally different from the CSV export adapter in
    api/core.py, whose raw ``_time`` column is UTC-naive and converted to WIB.
    """
    if not isinstance(data, dict):
        raise core.DashindoError("Payload n_data Dashindo tidak valid.")
    times = data.get("times")
    values = data.get("values")
    if not isinstance(times, list) or not isinstance(values, list):
        raise core.DashindoError("Payload n_data Dashindo tidak memiliki times/values.")

    rows: list[list[Any]] = []
    seen: set[str] = set()
    for raw_time, raw_value in zip(times, values):
        dt = _parse_any_datetime(raw_time)
        if dt is None or dt < start_dt or dt > end_dt:
            continue
        try:
            value = float(str(raw_value).strip().replace(",", "."))
        except (TypeError, ValueError):
            continue
        stamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        if stamp in seen:
            continue
        seen.add(stamp)
        rows.append([stamp, value])
    rows.sort(key=lambda row: str(row[0]))
    return rows


def _monitor_dashindo_fetch_hourly_on_engine(
    engine: _MonitorDashindoEngineIO,
    st: dict[str, Any],
    start_dt: datetime,
    end_dt: datetime,
    deadline_at: float,
) -> list[list[Any]]:
    """Monitoring fast path: direct server-side hourly data, no CSV export.

    Dashindo's own ``index-socket.js`` emits:
      get_n_data_hourly(device, field, [tss, tse])
    and receives the regular ``n_data`` event with ``times`` + ``values``.
    The browser accepts date-only tss/tse and the upstream returns the complete
    requested days, so this route avoids raw-minute transfer, Base64 decoding,
    and CSV parsing.
    """
    device, field = _monitor_dashindo_station_device_field(st)
    if time.monotonic() >= deadline_at:
        raise core.DashindoError("Batas waktu total Dashindo Monitoring tercapai.")

    # The vendor UI itself sends the visible local dates to get_n_data_hourly.
    # One request can cover multi-day periods (the supplied HAR shows the same
    # get_n_data family called with an 18-day [tss, tse] range).
    tss = start_dt.strftime("%Y-%m-%d")
    tse = end_dt.strftime("%Y-%m-%d")
    engine.send_event("get_n_data_hourly", device, field, [tss, tse])
    _event, data = engine.poll_until(
        {"n_data"},
        min(deadline_at, time.monotonic() + MONITORING_DASHINDO_EVENT_TIMEOUT),
    )
    return _monitor_dashindo_rows_from_n_data(data, start_dt=start_dt, end_dt=end_dt)


def _monitor_dashindo_fetch_csv_on_engine(
    engine: _MonitorDashindoEngineIO,
    st: dict[str, Any],
    start_dt: datetime,
    end_dt: datetime,
    deadline_at: float,
) -> list[list[Any]]:
    """Reliable Monitoring fallback retained from V21's persistent CSV path."""
    device, field = _monitor_dashindo_station_device_field(st)
    start_utc = start_dt - timedelta(hours=core.DASHINDO_TZ_OFFSET_HOURS)
    end_utc = end_dt - timedelta(hours=core.DASHINDO_TZ_OFFSET_HOURS)
    chunks = core._split_date_month_chunks(start_utc.date(), end_utc.date(), core.DASHINDO_CHUNK_MONTHS)
    rows: list[list[Any]] = []
    seen: set[tuple[str, str]] = set()

    for tss, tse in chunks:
        if time.monotonic() >= deadline_at:
            raise core.DashindoError("Batas waktu total Dashindo Monitoring tercapai.")
        engine.send_event("downloadcsv", device, field, tss, tse)
        _event, data = engine.poll_until(
            {"download_csv"},
            min(deadline_at, time.monotonic() + MONITORING_DASHINDO_EVENT_TIMEOUT),
        )
        if not isinstance(data, dict):
            raise core.DashindoError("Payload download_csv Dashindo tidak valid.")
        content = data.get("content")
        raw = b"id,_field,_time,_value\n" if not content else base64.b64decode(content)
        part = core._dashindo_csv_rows(
            raw_csv=raw,
            expected_device=device,
            expected_field=field,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        for row in part:
            key = (str(row[0]), str(row[1] if len(row) > 1 else ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda row: str(row[0]))
    return rows


def _monitor_fetch_dashindo_group(
    items: list[dict[str, Any]],
    category: str,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Fetch Dashindo with one authenticated Engine.IO connection per batch.

    V22 keeps V21's persistent authenticated connections, but each station now
    requests Dashindo's native ``get_n_data_hourly`` event first.  The server
    returns ``n_data`` (times + values), avoiding CSV generation/Base64/parsing.
    A fresh connection + V21 CSV path is retained only as fallback. Pengolahan
    uses ``core.dashindo_data`` with raw ``get_n_data`` (not hourly) in V26.
    """
    started = time.perf_counter()
    deadline_at = time.monotonic() + MONITORING_DASHINDO_VENDOR_DEADLINE
    worker_count = min(max(1, MONITORING_DASHINDO_WORKERS), len(items) or 1)
    groups: list[list[dict[str, Any]]] = [[] for _ in range(worker_count)]
    for idx, st in enumerate(items):
        groups[idx % worker_count].append(st)

    def worker(group: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], int]:
        output: list[dict[str, Any]] = []
        warnings: list[str] = []
        timings: list[dict[str, Any]] = []
        reconnects = 0
        engine: _MonitorDashindoEngineIO | None = None
        client: requests.Session | None = None

        def connect() -> None:
            nonlocal client, engine, reconnects
            if engine is not None:
                try:
                    engine.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            client, engine = _monitor_dashindo_open_engine(deadline_at)
            reconnects += 1

        try:
            connect()
            for st in group:
                t0 = time.perf_counter()
                error: str | None = None
                result: dict[str, Any] | None = None
                if time.monotonic() >= deadline_at:
                    error = f"Batas waktu total Dashindo {MONITORING_DASHINDO_VENDOR_DEADLINE:g} dtk tercapai."
                else:
                    try:
                        assert engine is not None
                        rows = _monitor_dashindo_fetch_hourly_on_engine(engine, st, start_dt, end_dt, deadline_at)
                        param = st.get("parameter") or {}
                        result = {
                            **st,
                            "parameter": param,
                            "series": _monitor_parse_rows(rows, category, "dashindo", param),
                            "dashindo_path": "persistent_hourly_n_data",
                        }
                    except Exception as exc:
                        # A failed hourly long-poll can leave a late n_data packet
                        # in the connection. Reconnect before using the proven
                        # CSV fallback so the next event cannot be mismatched.
                        first_error = str(exc)
                        try:
                            if time.monotonic() + 1.0 < deadline_at:
                                connect()
                                assert engine is not None
                                # Reconnect before fallback so a late n_data packet from the
                                # failed hourly request cannot be mistaken for another station.
                                rows = _monitor_dashindo_fetch_csv_on_engine(engine, st, start_dt, end_dt, deadline_at)
                                param = st.get("parameter") or {}
                                result = {
                                    **st,
                                    "parameter": param,
                                    "series": _monitor_parse_rows(rows, category, "dashindo", param),
                                    "dashindo_path": "persistent_csv_fallback",
                                }
                            else:
                                error = first_error
                        except Exception as retry_exc:
                            error = f"{first_error}; retry: {retry_exc}"

                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                timings.append({
                    "name": st.get("name"),
                    "id_logger": st.get("id_logger"),
                    "total_ms": elapsed_ms,
                    "ok": error is None and result is not None,
                    "path": (result or {}).get("dashindo_path") if result is not None else None,
                    **({"error": error} if error else {}),
                })
                if result is not None:
                    output.append(result)
                else:
                    warnings.append(f"Dashindo {st.get('name')}: {error or 'gagal mengambil data'}")
                    output.append({**st, "series": [], "fetch_failed": True})
        except Exception as exc:
            # Connection bootstrap failure: materialize every unprocessed item
            # as failed instead of silently dropping it.
            processed_ids = {str(x.get("id_logger")) for x in output}
            for st in group:
                if str(st.get("id_logger")) in processed_ids:
                    continue
                msg = str(exc)
                timings.append({
                    "name": st.get("name"),
                    "id_logger": st.get("id_logger"),
                    "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    "ok": False,
                    "error": msg,
                })
                warnings.append(f"Dashindo {st.get('name')}: {msg}")
                output.append({**st, "series": [], "fetch_failed": True})
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        return output, warnings, timings, reconnects

    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    station_timings: list[dict[str, Any]] = []
    reconnect_count = 0
    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="monitor-dashindo-batch")
    fmap = {executor.submit(worker, group): group for group in groups if group}
    from concurrent.futures import wait as _wait
    remaining = max(0.0, deadline_at - time.monotonic())
    done, pending = _wait(fmap, timeout=remaining)
    for future in done:
        try:
            res, warn, timing_rows, reconnects = future.result()
            results.extend(res)
            warnings.extend(warn)
            station_timings.extend(timing_rows)
            reconnect_count += reconnects
        except Exception as exc:
            for st in fmap[future]:
                warnings.append(f"Dashindo {st.get('name')}: {exc}")
                results.append({**st, "series": [], "fetch_failed": True})
    if pending:
        cutoff_ms = round((time.perf_counter() - started) * 1000.0, 1)
        existing = {str(x.get("id_logger")) for x in results}
        for future in pending:
            future.cancel()
            for st in fmap[future]:
                if str(st.get("id_logger")) in existing:
                    continue
                msg = f"Batas waktu total Dashindo {MONITORING_DASHINDO_VENDOR_DEADLINE:g} dtk tercapai."
                warnings.append(f"Dashindo {st.get('name')}: {msg}")
                results.append({**st, "series": [], "fetch_failed": True})
                station_timings.append({
                    "name": st.get("name"),
                    "id_logger": st.get("id_logger"),
                    "total_ms": cutoff_ms,
                    "ok": False,
                    "deadline_exceeded": True,
                    "error": msg,
                })
    executor.shutdown(wait=False, cancel_futures=True)

    station_timings.sort(key=lambda row: float(row.get("total_ms") or 0), reverse=True)
    detail = {
        "station_count": len(items),
        "station_timings": station_timings,
        "transport": "persistent_engineio_hourly_n_data",
        "worker_count": worker_count,
        "engine_connection_count": reconnect_count,
        "deadline_ms": round(MONITORING_DASHINDO_VENDOR_DEADLINE * 1000.0, 1),
        "deadline_exceeded": bool(pending),
        "timed_out_station_count": sum(1 for x in station_timings if x.get("deadline_exceeded")),
        "hourly_direct_count": sum(1 for x in results if x.get("dashindo_path") == "persistent_hourly_n_data"),
        "csv_fallback_count": sum(1 for x in results if x.get("dashindo_path") == "persistent_csv_fallback"),
    }
    return results, warnings, detail


def _higertech_monitor_cache_get(device_id: str, day_key: str) -> list[dict[str, Any]] | None:
    now = time.time()
    today_key = core.now_wib_naive().date().isoformat()
    ttl = MONITORING_HIGERTECH_TODAY_CACHE_TTL if day_key == today_key else MONITORING_HIGERTECH_DAY_CACHE_TTL
    key = (str(device_id), str(day_key))
    with _HIGERTECH_MONITOR_DAY_LOCK:
        cached = _HIGERTECH_MONITOR_DAY_CACHE.get(key)
        if not cached:
            return None
        created_at, rows = cached
        if now - created_at >= ttl:
            _HIGERTECH_MONITOR_DAY_CACHE.pop(key, None)
            return None
        # Keep cache content immutable to callers.
        return [dict(row) for row in rows]


def _higertech_monitor_cache_put(device_id: str, day_key: str, rows: list[dict[str, Any]]) -> None:
    key = (str(device_id), str(day_key))
    with _HIGERTECH_MONITOR_DAY_LOCK:
        _HIGERTECH_MONITOR_DAY_CACHE[key] = (time.time(), [dict(row) for row in rows])
        # Bound opportunistic warm-instance memory usage.
        if len(_HIGERTECH_MONITOR_DAY_CACHE) > 128:
            oldest = min(_HIGERTECH_MONITOR_DAY_CACHE, key=lambda k: _HIGERTECH_MONITOR_DAY_CACHE[k][0])
            _HIGERTECH_MONITOR_DAY_CACHE.pop(oldest, None)


def _higertech_monitor_day(device_id: str, day_key: str) -> tuple[list[dict[str, Any]], str]:
    """Fetch one calendar day of native 5-minute chart data.

    Higertech's ``readingAt`` is observed as local WIB wall-clock time even
    though the serialized string ends in ``Z``.  ``readingAtUtc`` is exactly
    seven hours behind it in the captured upstream traffic.  Parsing therefore
    intentionally preserves the wall-clock value from ``readingAt``.
    """
    cached = _higertech_monitor_cache_get(device_id, day_key)
    if cached is not None:
        return cached, "hit"

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": core.HIGERTECH_BASE_URL,
        "Referer": f"{core.HIGERTECH_BASE_URL}/Station",
    }
    payload = {
        "deviceId": str(device_id),
        "selectedTime": "minute",
        "filterDate": str(day_key),
    }

    def request_once(*, force_login: bool = False) -> requests.Response:
        if force_login:
            core._higertech_login(force=True)
        client = core._higertech_clone_authenticated_session()
        return client.post(
            HIGERTECH_MONITOR_CHART_URL,
            data=payload,
            headers=headers,
            timeout=MONITORING_HIGERTECH_TIMEOUT,
            allow_redirects=True,
        )

    response = request_once()
    if response.status_code in (401, 403) or "/account/login" in response.url.lower():
        response = request_once(force_login=True)
    response.raise_for_status()

    text = response.text.strip()
    # Some dates without telemetry are returned as an empty 200 response.
    if not text:
        rows: list[dict[str, Any]] = []
    else:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype or "/account/login" in response.url.lower():
            # One final auth refresh protects warm instances with stale cookies.
            response = request_once(force_login=True)
            response.raise_for_status()
            text = response.text.strip()
            if not text:
                rows = []
            else:
                ctype = (response.headers.get("Content-Type") or "").lower()
                if "text/html" in ctype:
                    raise RuntimeError("Higertech mengembalikan HTML saat meminta data chart 5 menit.")
                payload_json = response.json()
                rows = payload_json.get("data") or [] if isinstance(payload_json, dict) else []
        else:
            payload_json = response.json()
            rows = payload_json.get("data") or [] if isinstance(payload_json, dict) else []

    if not isinstance(rows, list):
        raise RuntimeError("Format data chart 5 menit Higertech tidak valid.")
    cleaned = [row for row in rows if isinstance(row, dict)]
    _higertech_monitor_cache_put(device_id, day_key, cleaned)
    return cleaned, "miss"


def _parse_higertech_monitor_local_time(row: dict[str, Any]) -> datetime | None:
    raw = clean_text(str(row.get("readingAt") or ""))
    if raw:
        # Upstream emits local WIB wall time with a misleading trailing Z.
        try:
            return datetime.fromisoformat(raw[:-1] if raw.endswith("Z") else raw).replace(tzinfo=None)
        except ValueError:
            pass
    raw_utc = clean_text(str(row.get("readingAtUtc") or ""))
    if raw_utc:
        try:
            utc_naive = datetime.fromisoformat(raw_utc[:-1] if raw_utc.endswith("Z") else raw_utc).replace(tzinfo=None)
            return utc_naive + timedelta(hours=7)
        except ValueError:
            pass
    return None


def _monitor_fetch_higertech_chart(
    st: dict[str, Any],
    category: str,
    start_dt: datetime,
    end_dt: datetime,
    param: dict[str, Any],
) -> dict[str, Any]:
    """Monitoring-only Higertech path using native 5-minute JSON chart data.

    One request is made per calendar day with ``selectedTime=minute``. Days are
    parallelised conservatively, then raw 5-minute points are left intact so the
    shared Monitoring aggregator performs hourly/daily TMA averages and rainfall
    sums itself. Pengolahan has a separate core.py fast path using the same raw
    chart resolution and falls back to XLSX when needed.
    """
    device_id = str(st["id_logger"])
    days: list[str] = []
    cursor = start_dt.date()
    last = end_dt.date()
    while cursor <= last:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    parts: dict[str, tuple[list[dict[str, Any]], str]] = {}
    workers = min(MONITORING_HIGERTECH_DAY_WORKERS, len(days) or 1)
    if workers > 1 and len(days) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="monitor-higertech-day") as executor:
            fmap = {executor.submit(_higertech_monitor_day, device_id, day): day for day in days}
            for future in as_completed(fmap):
                day = fmap[future]
                parts[day] = future.result()
    else:
        for day in days:
            parts[day] = _higertech_monitor_day(device_id, day)

    value_key = "rainfall" if category == "rain" else "waterLevel"
    series_map: dict[datetime, float] = {}
    cache_hits = 0
    network_days = 0
    raw_count = 0
    for day in days:
        raw_rows, cache_status = parts.get(day, ([], "miss"))
        if cache_status == "hit":
            cache_hits += 1
        else:
            network_days += 1
        for row in raw_rows:
            dt = _parse_higertech_monitor_local_time(row)
            if dt is None or dt < start_dt or dt > end_dt:
                continue
            raw_value = row.get(value_key)
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            series_map[dt] = value
            raw_count += 1

    return {
        **st,
        "parameter": param,
        "series": sorted(series_map.items(), key=lambda pair: pair[0]),
        "higertech_path": "chart_5min",
        "higertech_day_count": len(days),
        "higertech_network_days": network_days,
        "higertech_cache_hits": cache_hits,
        "higertech_raw_points": raw_count,
    }


def _monitor_fetch_nonbeacon(
    st: dict[str, Any],
    category: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    deadline_at: float | None = None,
) -> dict[str, Any]:
    vendor = st["vendor"]
    param = st.get("parameter")
    if not param:
        raise RuntimeError("Parameter yang sesuai tidak ditemukan.")
    dari = start_dt.strftime("%Y-%m-%d %H:%M")
    sampai = end_dt.strftime("%Y-%m-%d %H:%M")
    if vendor == "higertech":
        try:
            return _monitor_fetch_higertech_chart(st, category, start_dt, end_dt, param)
        except Exception as direct_exc:
            # Reliability fallback only. core.higertech_data itself now prefers
            # raw chart data for Pengolahan and retains XLSX as the final fallback.
            _headers, rows, _station = higertech_data(
                st["id_logger"], dari, sampai, str(param["id"]), isolated_session=True
            )
            return {
                **st,
                "parameter": param,
                "series": _monitor_parse_rows(rows, category, vendor, param),
                "higertech_path": "xlsx_fallback",
                "higertech_direct_error": str(direct_exc),
            }
    elif vendor == "tatonas":
        return _monitor_fetch_tatonas_fast(st, category, start_dt, end_dt, param, deadline_at=deadline_at)
    elif vendor == "dashindo":
        _headers, rows, _station, returned_param = dashindo_data(st["id_logger"], str(param["id"]), dari, sampai)
        param = returned_param or param
    else:
        raise RuntimeError(f"Vendor monitoring tidak dikenal: {vendor}")
    return {**st, "parameter": param, "series": _monitor_parse_rows(rows, category, vendor, param)}


def _beacon_parameter_for(logger_id: str, param_id: str) -> dict[str, Any] | None:
    cached = PARAMETER_CACHE.get(str(logger_id))
    params = cached[1] if cached else []
    for param in params:
        if clean_text(str(param.get("id") or "")) == clean_text(str(param_id)):
            return param
    return None


def _beacon_preferred_parameter(st: dict[str, Any], category: str) -> dict[str, Any] | None:
    cached = PARAMETER_CACHE.get(str(st.get("id_logger") or ""))
    params = cached[1] if cached else []
    return _preferred_monitor_parameter(params, category)


def _beacon_selector_snapshot(client: BBWSSession | None = None, force: bool = False) -> dict[tuple[str, str], str]:
    """Read exact Beacon set_sensordash selectors from /beranda for Monitoring only.

    This cache is deliberately local to the Monitoring service.  The Olah Data
    workflow in api/core.py is left untouched and keeps the proven set_token
    algorithm from the input repository.
    """
    global _BEACON_SELECTOR_CACHE
    now = time.time()
    with _BEACON_SELECTOR_LOCK:
        cached_at, cached_map = _BEACON_SELECTOR_CACHE
        if cached_map and not force and now - cached_at < MONITORING_BEACON_METADATA_TTL:
            return dict(cached_map)

    owns_client = client is None
    client = client or BBWSSession()
    if not client.logged_in:
        client.login()

    response = client._get(
        f"{core.BASE_URL}/beranda",
        referer=client.current_url or core.LOGIN_URL,
    )
    if core.looks_like_login(response.text, response.url):
        raise RuntimeError("Sesi Beacon kedaluwarsa saat membaca metadata /beranda.")

    # Index catalog by owner+parameter.  BBWS parameter ids are generally
    # unique; grouped sensors are resolved by the grp query and logger suffix.
    by_owner_param: dict[tuple[str, str], list[str]] = {}
    for logger_id, cached in PARAMETER_CACHE.items():
        lid = str(logger_id).lower()
        owner = "bbws" if "_bbws" in lid else "psda" if "_psda" in lid else ""
        if not owner:
            continue
        for param in cached[1]:
            pid = clean_text(str(param.get("id") or ""))
            if pid:
                by_owner_param.setdefault((owner, pid), []).append(str(logger_id))

    selectors: dict[tuple[str, str], str] = {}
    soup = core.parse_html(response.text)
    for anchor in soup.find_all("a", href=True):
        raw_href = clean_text(str(anchor.get("href") or ""))
        if "/analisa/set_sensordash" not in raw_href:
            continue
        absolute = urljoin(core.BASE_URL + "/", raw_href)
        parsed = urlparse(absolute)
        query = parse_qs(parsed.query)
        selector = clean_text((query.get("id_param") or [""])[0])
        if not selector:
            continue
        lowered = selector.lower()
        if lowered.endswith("_bbws"):
            owner, pid = "bbws", selector[:-5]
        elif lowered.endswith("_psda"):
            owner, pid = "psda", selector[:-5]
        else:
            continue

        logger_query = clean_text((query.get("id_logger") or [""])[0])
        grp = clean_text((query.get("grp") or [""])[0])
        candidates: list[str] = []
        if logger_query:
            direct = logger_query if f"_{owner}" in logger_query.lower() else f"{logger_query}_{owner}"
            candidates = [direct]
        else:
            candidates = list(by_owner_param.get((owner, pid), []))

        if grp:
            grouped = [lid for lid in candidates if lid.lower().endswith(f"_{owner}_{grp}".lower())]
            if grouped:
                candidates = grouped
        if len(candidates) == 1:
            selectors[(candidates[0], pid)] = absolute
        else:
            # Shared battery/temperature ids can occur on grouped logger rows.
            # grp disambiguates them even if the generic parameter index did not.
            if grp:
                for lid in PARAMETER_CACHE:
                    if str(lid).lower().endswith(f"_{owner}_{grp}".lower()) and _beacon_parameter_for(str(lid), pid):
                        selectors[(str(lid), pid)] = absolute

    with _BEACON_SELECTOR_LOCK:
        _BEACON_SELECTOR_CACHE = (time.time(), dict(selectors))
    return selectors


def _beacon_selector_url(logger_id: str, param_id: str, selectors: dict[tuple[str, str], str]) -> str:
    exact = selectors.get((str(logger_id), str(param_id)))
    if exact:
        return exact

    lid = clean_text(str(logger_id))
    pid = clean_text(str(param_id))
    lower = lid.lower()
    if "_bbws" in lower:
        grp_match = re.search(r"_bbws_(\d+)$", lower)
        suffix = f"&grp={quote_plus(grp_match.group(1))}" if grp_match else ""
        return f"{core.BASE_URL}/analisa/set_sensordash?id_param={quote_plus(pid + '_bbws')}{suffix}"
    if "_psda" in lower:
        raw_logger = re.sub(r"_psda(?:_.*)?$", "", lid, flags=re.I)
        return (
            f"{core.BASE_URL}/analisa/set_sensordash?"
            f"id_logger={quote_plus(raw_logger)}&id_param={quote_plus(pid + '_psda')}"
        )
    raise RuntimeError(f"Owner aset Beacon tidak dikenali: {logger_id}")


def _beacon_monitor_chunk_payload(client: BBWSSession, token: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Fetch one BBWS chunk and keep the epoch timestamp from JSON `data`."""
    http = client._clone_http_pool()
    response = http.post(
        core.DATA_CHUNK_URL,
        files={
            "token": (None, token),
            "start": (None, start.strftime("%Y-%m-%d %H:%M:%S")),
            "end": (None, end.strftime("%Y-%m-%d %H:%M:%S")),
        },
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": core.BASE_URL,
            "Referer": client.current_url or f"{core.BASE_URL}/analisa/data/{token}",
        },
        timeout=max(core.TIMEOUT, 60),
        allow_redirects=True,
    )
    response.raise_for_status()
    if core.looks_like_login(response.text, response.url):
        raise RuntimeError("Sesi Beacon kedaluwarsa saat mengambil supplement data_chunk.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Response supplement data_chunk Beacon bukan JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Payload supplement data_chunk Beacon tidak valid.")
    status = clean_text(str(payload.get("status") or "")).lower()
    raw_data = payload.get("data")
    if status and status not in {"ok", "success"} and not raw_data:
        msg = clean_text(str(payload.get("message") or payload.get("error") or status))
        if any(word in msg.lower() for word in ("no data", "tidak ada data", "empty", "kosong")):
            return []
        raise RuntimeError(f"data_chunk Beacon gagal: {msg}")

    out: list[tuple[datetime, float]] = []
    if isinstance(raw_data, list):
        for row in raw_data:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                # Beacon's table uses the UTC-formatted clock value directly;
                # utcfromtimestamp reproduces that displayed timestamp without
                # applying the host/Vercel timezone.
                dt = datetime.utcfromtimestamp(float(row[0]) / 1000.0)
                value = float(row[1])
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            out.append((dt, value))
    return out


def _beacon_monitor_period_chunks(start_dt: datetime, end_dt: datetime) -> list[tuple[datetime, datetime]]:
    """Split one exact BBWS sensor period using Beacon's proven chunk limit."""
    chunk_days = max(1, min(25, int(core.BEACON_CHUNK_DAYS)))
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start_dt
    while cursor <= end_dt:
        chunk_end = min(end_dt, cursor + timedelta(days=chunk_days) - timedelta(minutes=1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(minutes=1)
    return chunks


def _beacon_monitor_prepare_bbws_token(
    client: BBWSSession,
    st: dict[str, Any],
    param: dict[str, Any],
    selectors: dict[tuple[str, str], str],
    *,
    force_refresh: bool = False,
) -> tuple[str, str, str]:
    """Return ``(token, current_url, cache_status)`` for one BBWS sensor.

    Token creation is intentionally separate from data_chunk fetching so the
    Monitoring supplement can prepare sensors first and then flatten all
    historical chunks into one global request pool.
    """
    logger_id = str(st["id_logger"])
    param_id = str(param["id"])
    if force_refresh:
        _beacon_token_cache_drop(logger_id, param_id)
    else:
        cached = _beacon_token_cache_get(logger_id, param_id)
        if cached:
            cached_token, cached_url = cached
            current_url = cached_url or f"{core.BASE_URL}/analisa/data/{cached_token}"
            client.token = cached_token
            client.current_url = current_url
            return cached_token, current_url, "hit"

    selector_url = _beacon_selector_url(logger_id, param_id, selectors)

    def select(url: str) -> tuple[str, str | None]:
        # Monitoring needs the redirect token only; do not render the large
        # /analisa/data/<token> HTML page unless the upstream redirect format
        # unexpectedly changes.
        referer = client.current_url or f"{core.BASE_URL}/beranda"
        response = client.session.get(
            url,
            headers={"Referer": referer},
            timeout=max(core.TIMEOUT, 60),
            allow_redirects=False,
        )
        response.raise_for_status()
        location = clean_text(str(response.headers.get("Location") or ""))
        if location:
            absolute = urljoin(core.BASE_URL + "/", location)
            if "/login" in urlparse(absolute).path.lower():
                raise RuntimeError("Sesi Beacon kedaluwarsa saat set_sensordash.")
            match = re.search(r"/analisa/data/([^/?#]+)", absolute)
            if match:
                return absolute, match.group(1)

        followed = client._get(url, referer=referer)
        if core.looks_like_login(followed.text, followed.url):
            raise RuntimeError("Sesi Beacon kedaluwarsa saat set_sensordash.")
        return followed.url, core.extract_token(followed.text, followed.url)

    selected_url = ""
    token = None
    try:
        selected_url, token = select(selector_url)
    except Exception:
        # Synthesized selectors cover the normal path. Only pay for /beranda
        # metadata if the vendor rejects that selector.
        fresh_selectors = _beacon_selector_snapshot(client=client, force=True)
        selected_url, token = select(_beacon_selector_url(logger_id, param_id, fresh_selectors))
    if not token:
        fresh_selectors = _beacon_selector_snapshot(client=client, force=True)
        selected_url, token = select(_beacon_selector_url(logger_id, param_id, fresh_selectors))
    if not token:
        raise RuntimeError("Token Beacon tidak ditemukan setelah set_sensordash.")

    current_url = selected_url or f"{core.BASE_URL}/analisa/data/{token}"
    client.token = token
    client.current_url = current_url
    _beacon_token_cache_put(logger_id, param_id, token, current_url)
    return token, current_url, "miss"


def _beacon_monitor_exact_bbws(
    client: BBWSSession,
    st: dict[str, Any],
    param: dict[str, Any],
    start_dt: datetime,
    end_dt: datetime,
    selectors: dict[tuple[str, str], str],
) -> tuple[list[tuple[datetime, float]], str]:
    """Fetch one exact BBWS sensor; retained as a safe standalone fallback."""
    chunks = _beacon_monitor_period_chunks(start_dt, end_dt)

    def fetch_chunks(token: str) -> list[tuple[datetime, float]]:
        results: dict[int, list[tuple[datetime, float]]] = {}
        workers = min(max(1, MONITORING_BEACON_CHUNK_WORKERS), len(chunks) or 1)
        if workers > 1 and len(chunks) > 1:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="monitor-beacon-chunk") as executor:
                fmap = {
                    executor.submit(_beacon_monitor_chunk_payload, client, token, begin, finish): idx
                    for idx, (begin, finish) in enumerate(chunks)
                }
                for future in as_completed(fmap):
                    results[fmap[future]] = future.result()
        else:
            for idx, (begin, finish) in enumerate(chunks):
                results[idx] = _beacon_monitor_chunk_payload(client, token, begin, finish)

        merged: dict[datetime, float] = {}
        for idx in range(len(chunks)):
            for dt, value in results.get(idx, []):
                merged[dt] = value
        return sorted(merged.items(), key=lambda item: item[0])

    token, _current_url, cache_status = _beacon_monitor_prepare_bbws_token(
        client, st, param, selectors
    )
    try:
        return fetch_chunks(token), cache_status
    except Exception:
        if cache_status != "hit":
            raise
        token, _current_url, _ = _beacon_monitor_prepare_bbws_token(
            client, st, param, selectors, force_refresh=True
        )
        return fetch_chunks(token), "stale"

def _beacon_bulk_logger_id(item: dict[str, Any], station_ids: set[str]) -> str | None:
    raw_logger = clean_text(str(item.get("id_logger") or ""))
    link = clean_text(str(item.get("link") or ""))
    query = parse_qs(urlparse(link).query) if link else {}
    selector = clean_text((query.get("id_param") or [""])[0])
    owner = ""
    if selector.lower().endswith("_bbws"):
        owner = "bbws"
    elif selector.lower().endswith("_psda"):
        owner = "psda"
    grp = clean_text((query.get("grp") or [""])[0])
    query_logger = clean_text((query.get("id_logger") or [""])[0])
    base = query_logger or raw_logger
    candidates: list[str] = []
    if base and owner and grp:
        candidates.append(f"{base}_{owner}_{grp}")
    if base and owner:
        candidates.append(f"{base}_{owner}")
    if raw_logger and owner:
        candidates.extend(sorted(x for x in station_ids if x.lower().startswith(f"{raw_logger}_{owner}".lower())))
    for candidate in candidates:
        if candidate in station_ids:
            return candidate
    return None


def _beacon_parse_bulk_html(html: str, stations: list[dict[str, Any]], category: str) -> tuple[list[dict[str, Any]], set[str]]:
    soup = core.parse_html(html)
    input_node = soup.find("input", attrs={"name": "parameter"})
    raw = input_node.get("value") if input_node else None
    if not raw:
        raise RuntimeError("Payload parameter bulk Beacon tidak ditemukan pada /monitoring.")
    try:
        payload = json.loads(html_lib.unescape(str(raw)))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Payload parameter bulk Beacon tidak dapat dibaca.") from exc
    if not isinstance(payload, list):
        raise RuntimeError("Format payload bulk Beacon tidak valid.")

    station_map = {str(st["id_logger"]): st for st in stations}
    station_ids = set(station_map)
    merged: dict[str, dict[str, Any]] = {}
    covered: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        logger_id = _beacon_bulk_logger_id(item, station_ids)
        if not logger_id:
            continue
        st = station_map[logger_id]
        covered.add(logger_id)  # Present in native bulk, even when this period is empty.
        pid = clean_text(str(item.get("id_param") or ""))
        param = _beacon_parameter_for(logger_id, pid) or _beacon_preferred_parameter(st, category)
        series_map: dict[datetime, float] = {}
        for point in item.get("data") or []:
            if not isinstance(point, dict):
                continue
            dt = _parse_any_datetime(point.get("waktu"))
            raw_value = clean_text(str(point.get("nilai") if point.get("nilai") is not None else ""))
            if dt is None or raw_value in {"", "-"}:
                continue
            try:
                value = float(raw_value.replace(",", "."))
            except ValueError:
                continue
            series_map[dt] = value
        current = merged.get(logger_id)
        if current:
            for dt, value in current.get("series") or []:
                series_map.setdefault(dt, value)
        merged[logger_id] = {
            **st,
            "parameter": param,
            "series": sorted(series_map.items(), key=lambda pair: pair[0]),
            "beacon_path": "bulk",
        }
    return list(merged.values()), covered


def _beacon_bulk_period(
    category: str,
    stations: list[dict[str, Any]],
    start_dt: datetime,
    end_dt: datetime,
    *,
    reuse_monitor_session: bool = False,
) -> tuple[list[dict[str, Any]], set[str]]:
    category_id = "7" if category == "rain" else "2"
    timeout = max(core.TIMEOUT, 60)

    # A <= bulk-days request has only one session-scoped state mutation, so it
    # can safely reuse warm Monitoring cookies.  Multi-chunk requests keep one
    # independently logged-in upstream session per chunk to prevent set_tanggal
    # state collisions.
    attempts = 2 if reuse_monitor_session else 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            if reuse_monitor_session:
                client = _beacon_monitor_cached_client(force=attempt > 0)
            else:
                client = BBWSSession()
                client.login()

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": core.BASE_URL,
                "Referer": f"{core.BASE_URL}/monitoring",
            }
            # Do NOT follow these 303 responses. Following each redirect would
            # render a large /monitoring page twice before the actual range.
            for url, data in (
                (f"{core.BASE_URL}/monitoring/set_kategori", {"format": " ", "id_kategori": category_id}),
                (
                    f"{core.BASE_URL}/monitoring/set_tanggal",
                    {
                        "format": " ",
                        "tgl1": start_dt.strftime("%Y-%m-%d %H:%M"),
                        "tgl2": end_dt.strftime("%Y-%m-%d %H:%M"),
                    },
                ),
            ):
                response = client.session.post(url, data=data, headers=headers, timeout=timeout, allow_redirects=False)
                response.raise_for_status()
                if response.status_code not in {200, 302, 303, 307, 308}:
                    raise RuntimeError(f"Beacon monitoring state gagal: HTTP {response.status_code}")

            response = client.session.get(
                f"{core.BASE_URL}/monitoring?format=",
                headers={"Referer": f"{core.BASE_URL}/monitoring"},
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            if core.looks_like_login(response.text, response.url):
                raise RuntimeError("Sesi Beacon kedaluwarsa saat mengambil bulk /monitoring.")
            return _beacon_parse_bulk_html(response.text, stations, category)
        except Exception as exc:
            last_error = exc
            if not reuse_monitor_session or attempt + 1 >= attempts:
                raise
    assert last_error is not None
    raise last_error


def _beacon_fetch_bulk(
    stations: list[dict[str, Any]],
    category: str,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    """Fetch native Beacon Monitoring in isolated, bounded bulk chunks.

    Short ranges keep the proven V18/V23 profile.  Long ranges use a slightly
    larger chunk and one extra isolated session so a 30/31-day request usually
    completes in a single wave (four chunks) instead of two waves (five 7-day
    chunks on three workers).  Only bulk chunks overlap; exact supplement still
    starts *after* bulk completes, avoiding the V19 contention regression.
    """
    span_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
    long_range = span_days >= MONITORING_BEACON_BULK_LONG_THRESHOLD
    chunk_days = MONITORING_BEACON_BULK_LONG_DAYS if long_range else MONITORING_BEACON_BULK_DAYS
    worker_limit = MONITORING_BEACON_BULK_LONG_WORKERS if long_range else MONITORING_BEACON_BULK_WORKERS

    chunks: list[tuple[datetime, datetime]] = []
    cursor = start_dt
    while cursor <= end_dt:
        chunk_end = min(end_dt, cursor + timedelta(days=chunk_days) - timedelta(minutes=1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(minutes=1)

    parts: dict[int, tuple[list[dict[str, Any]], set[str]]] = {}
    chunk_timings: dict[int, dict[str, Any]] = {}
    workers = min(worker_limit, len(chunks) or 1)

    def timed_period(idx: int, begin: datetime, finish: datetime, *, reuse_monitor_session: bool = False):
        t0 = time.perf_counter()
        rows, chunk_covered = _beacon_bulk_period(
            category, stations, begin, finish, reuse_monitor_session=reuse_monitor_session
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return idx, rows, chunk_covered, {
            "index": idx + 1,
            "start": begin.strftime("%Y-%m-%d %H:%M"),
            "end": finish.strftime("%Y-%m-%d %H:%M"),
            "total_ms": elapsed_ms,
            "result_count": len(rows),
            "covered_count": len(chunk_covered),
        }

    if len(chunks) == 1:
        idx, rows, chunk_covered, detail = timed_period(
            0, chunks[0][0], chunks[0][1], reuse_monitor_session=True
        )
        parts[idx] = (rows, chunk_covered)
        chunk_timings[idx] = detail
    elif workers > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="monitor-beacon-bulk") as executor:
            fmap = {
                executor.submit(timed_period, idx, begin, finish): idx
                for idx, (begin, finish) in enumerate(chunks)
            }
            for future in as_completed(fmap):
                idx, rows, chunk_covered, detail = future.result()
                parts[idx] = (rows, chunk_covered)
                chunk_timings[idx] = detail
    else:
        for idx, (begin, finish) in enumerate(chunks):
            idx2, rows, chunk_covered, detail = timed_period(idx, begin, finish)
            parts[idx2] = (rows, chunk_covered)
            chunk_timings[idx2] = detail

    by_logger: dict[str, dict[str, Any]] = {}
    covered: set[str] = set()
    for idx in range(len(chunks)):
        rows, chunk_covered = parts[idx]
        covered.update(chunk_covered)
        for row in rows:
            logger_id = str(row["id_logger"])
            previous = by_logger.get(logger_id)
            combined: dict[datetime, float] = {}
            if previous:
                combined.update(previous.get("series") or [])
            combined.update(row.get("series") or [])
            by_logger[logger_id] = {
                **row,
                "series": sorted(combined.items(), key=lambda pair: pair[0]),
            }

    detail = {
        "bulk_span_days": span_days,
        "bulk_long_range": long_range,
        "bulk_chunk_days": chunk_days,
        "bulk_worker_count": workers,
        "bulk_chunk_count": len(chunks),
        "bulk_chunk_timings": [chunk_timings[i] for i in range(len(chunks)) if i in chunk_timings],
    }
    return list(by_logger.values()), covered, detail


def _monitor_fetch_beacon_group(stations: list[dict[str, Any]], category: str, start_dt: datetime, end_dt: datetime) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Beacon Monitoring = native bulk first, exact-sensor supplement second.

    V25 keeps bulk and supplement sequential, but flattens every BBWS
    ``data_chunk`` request in the supplement into one bounded global pool. This
    avoids per-station nested executors and keeps the long-range tail balanced.
    PSDA retains its proven HTML historical path and may run alongside BBWS
    supplement work. Olah Data does not call this function.
    """
    started = time.perf_counter()
    if not stations:
        return [], [], {"total_ms": 0.0, "bulk_ms": 0.0, "selector_metadata_ms": 0.0, "supplement_ms": 0.0}

    warnings: list[str] = []
    bulk_results: list[dict[str, Any]] = []
    covered: set[str] = set()
    bulk_detail: dict[str, Any] = {}
    bulk_started = time.perf_counter()
    try:
        bulk_results, covered, bulk_detail = _beacon_fetch_bulk(stations, category, start_dt, end_dt)
    except Exception as exc:
        warnings.append(f"Beacon bulk /monitoring gagal, memakai fallback exact: {exc}")
    bulk_ms = (time.perf_counter() - bulk_started) * 1000.0

    missing = [st for st in stations if str(st["id_logger"]) not in covered]
    if not missing:
        timing = {
            "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "bulk_ms": round(bulk_ms, 1),
            "selector_metadata_ms": 0.0,
            "supplement_ms": 0.0,
            "station_count": len(stations),
            "bulk_result_count": len(bulk_results),
            "covered_count": len(covered),
            "supplement_requested": 0,
            "supplement_failed": 0,
            "supplement_bbws_count": 0,
            "supplement_psda_count": 0,
            "supplement_chunk_workers": 0,
            "supplement_chunk_requests": 0,
            "supplement_chunk_retry_requests": 0,
            "supplement_chunk_ms": 0.0,
            "token_cache_hits": 0,
            "token_cache_misses": 0,
            "token_cache_stale": 0,
            "token_cache_ttl_s": MONITORING_BEACON_TOKEN_TTL,
            **bulk_detail,
        }
        return bulk_results, warnings, timing

    selector_started = time.perf_counter()
    selectors = _beacon_selector_cached_only()
    selector_metadata_ms = (time.perf_counter() - selector_started) * 1000.0

    missing_bbws = [st for st in missing if "_bbws" in str(st.get("id_logger") or "").lower()]
    missing_psda = [st for st in missing if st not in missing_bbws]
    supplement_results: list[dict[str, Any]] = []
    supplement_started = time.perf_counter()

    def resolve_parameter(client: BBWSSession, st: dict[str, Any]) -> dict[str, Any]:
        param = _beacon_preferred_parameter(st, category)
        if not param:
            params = client.discover_parameters(str(st["id_logger"]))
            param = _preferred_monitor_parameter(params, category)
        if not param:
            raise RuntimeError("Parameter monitoring tidak ditemukan.")
        return param

    # PSDA data_chunk is unsupported upstream. Start these few legacy HTML
    # fetches early so their latency can overlap the BBWS token/chunk pipeline.
    psda_workers = min(2, len(missing_psda)) if missing_psda else 0
    psda_executor = ThreadPoolExecutor(max_workers=psda_workers, thread_name_prefix="monitor-beacon-psda") if psda_workers else None
    psda_futures = []

    def fetch_psda(st: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            client = _beacon_monitor_cached_client()
            param = resolve_parameter(client, st)
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
            series = _monitor_parse_rows(rows, category, "beacon", param)
            return {**st, "parameter": param, "series": series, "beacon_path": "supplement_psda"}, None
        except Exception as exc:
            return {**st, "parameter": None, "series": [], "fetch_failed": True}, f"Beacon {st.get('name')}: {exc}"

    if psda_executor:
        psda_futures = [psda_executor.submit(fetch_psda, st) for st in missing_psda]

    # Prepare one independent client + parameter-specific token per BBWS sensor.
    # Token creation stays bounded; after this phase every historical chunk is
    # flattened into one global pool below.
    prepared: dict[str, dict[str, Any]] = {}
    prep_failures: list[dict[str, Any]] = []

    def prepare_bbws(st: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
        try:
            client = _beacon_monitor_cached_client()
            param = resolve_parameter(client, st)
            token, current_url, cache_status = _beacon_monitor_prepare_bbws_token(
                client, st, param, selectors
            )
            return {
                "station": st,
                "param": param,
                "client": client,
                "token": token,
                "current_url": current_url,
                "cache_status": cache_status,
                "chunks": _beacon_monitor_period_chunks(start_dt, end_dt),
            }, None, None
        except Exception as exc:
            failed = {**st, "parameter": None, "series": [], "fetch_failed": True}
            return None, failed, f"Beacon {st.get('name')}: {exc}"

    prep_workers = min(MONITORING_BEACON_WORKERS, len(missing_bbws)) if missing_bbws else 0
    if prep_workers:
        with ThreadPoolExecutor(max_workers=prep_workers, thread_name_prefix="monitor-beacon-prepare") as executor:
            fmap = {executor.submit(prepare_bbws, st): st for st in missing_bbws}
            for future in as_completed(fmap):
                item, failed, warn = future.result()
                if item:
                    prepared[str(item["station"]["id_logger"])] = item
                if failed:
                    prep_failures.append(failed)
                if warn:
                    warnings.append(warn)

    supplement_results.extend(prep_failures)

    chunk_started = time.perf_counter()
    initial_chunk_requests = sum(len(item["chunks"]) for item in prepared.values())
    chunk_workers = min(MONITORING_BEACON_CHUNK_WORKERS, initial_chunk_requests) if initial_chunk_requests else 0
    chunk_results: dict[str, dict[int, list[tuple[datetime, float]]]] = {
        logger_id: {} for logger_id in prepared
    }
    chunk_errors: dict[str, list[str]] = {}

    def run_chunk_batch(items: list[tuple[str, int, datetime, datetime]], workers: int) -> None:
        if not items:
            return
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items))), thread_name_prefix="monitor-beacon-flat-chunk") as executor:
            fmap = {}
            for logger_id, chunk_idx, begin, finish in items:
                item = prepared[logger_id]
                future = executor.submit(
                    _beacon_monitor_chunk_payload,
                    item["client"],
                    item["token"],
                    begin,
                    finish,
                )
                fmap[future] = (logger_id, chunk_idx)
            for future in as_completed(fmap):
                logger_id, chunk_idx = fmap[future]
                try:
                    chunk_results.setdefault(logger_id, {})[chunk_idx] = future.result()
                except Exception as exc:
                    chunk_errors.setdefault(logger_id, []).append(str(exc))

    initial_tasks: list[tuple[str, int, datetime, datetime]] = []
    for logger_id, item in prepared.items():
        for idx, (begin, finish) in enumerate(item["chunks"]):
            initial_tasks.append((logger_id, idx, begin, finish))
    if initial_tasks:
        run_chunk_batch(initial_tasks, chunk_workers)

    # Cached tokens are fail-safe. If any chunk rejects a cached token, refresh
    # that sensor once and retry all of its chunks through the same flat pool.
    stale_ids = [
        logger_id
        for logger_id in chunk_errors
        if prepared.get(logger_id, {}).get("cache_status") == "hit"
    ]
    retry_tasks: list[tuple[str, int, datetime, datetime]] = []
    permanent_errors = {logger_id for logger_id in chunk_errors if logger_id not in stale_ids}

    def refresh_stale(logger_id: str) -> tuple[str, str | None]:
        item = prepared[logger_id]
        try:
            token, current_url, _ = _beacon_monitor_prepare_bbws_token(
                item["client"], item["station"], item["param"], selectors, force_refresh=True
            )
            item["token"] = token
            item["current_url"] = current_url
            item["cache_status"] = "stale"
            chunk_results[logger_id] = {}
            chunk_errors.pop(logger_id, None)
            return logger_id, None
        except Exception as exc:
            return logger_id, str(exc)

    if stale_ids:
        refresh_workers = min(MONITORING_BEACON_WORKERS, len(stale_ids))
        with ThreadPoolExecutor(max_workers=refresh_workers, thread_name_prefix="monitor-beacon-refresh-token") as executor:
            fmap = {executor.submit(refresh_stale, logger_id): logger_id for logger_id in stale_ids}
            for future in as_completed(fmap):
                logger_id, error = future.result()
                if error:
                    permanent_errors.add(logger_id)
                    chunk_errors.setdefault(logger_id, []).append(error)
                else:
                    for idx, (begin, finish) in enumerate(prepared[logger_id]["chunks"]):
                        retry_tasks.append((logger_id, idx, begin, finish))

    if retry_tasks:
        run_chunk_batch(retry_tasks, min(MONITORING_BEACON_CHUNK_WORKERS, len(retry_tasks)))
        for logger_id in {task[0] for task in retry_tasks}:
            if logger_id in chunk_errors:
                permanent_errors.add(logger_id)

    supplement_chunk_ms = (time.perf_counter() - chunk_started) * 1000.0

    for logger_id, item in prepared.items():
        st = item["station"]
        param = item["param"]
        if logger_id in permanent_errors or logger_id in chunk_errors:
            detail = "; ".join(chunk_errors.get(logger_id, [])) or "data_chunk gagal"
            warnings.append(f"Beacon {st.get('name')}: {detail}")
            supplement_results.append({**st, "parameter": None, "series": [], "fetch_failed": True})
            continue
        merged: dict[datetime, float] = {}
        for idx in range(len(item["chunks"])):
            for dt, value in chunk_results.get(logger_id, {}).get(idx, []):
                merged[dt] = value
        supplement_results.append({
            **st,
            "parameter": param,
            "series": sorted(merged.items(), key=lambda pair: pair[0]),
            "beacon_path": "supplement",
        })

    if psda_futures:
        for future in as_completed(psda_futures):
            row, warn = future.result()
            supplement_results.append(row)
            if warn:
                warnings.append(warn)
    if psda_executor:
        psda_executor.shutdown(wait=True)

    supplement_ms = (time.perf_counter() - supplement_started) * 1000.0
    cache_statuses = [item.get("cache_status") for item in prepared.values()]
    timing = {
        "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "bulk_ms": round(bulk_ms, 1),
        "selector_metadata_ms": round(selector_metadata_ms, 1),
        "supplement_ms": round(supplement_ms, 1),
        "station_count": len(stations),
        "bulk_result_count": len(bulk_results),
        "covered_count": len(covered),
        "supplement_requested": len(missing),
        "supplement_failed": sum(1 for item in supplement_results if item.get("fetch_failed")),
        "supplement_bbws_count": len(missing_bbws),
        "supplement_psda_count": len(missing_psda),
        "supplement_chunk_workers": chunk_workers,
        "supplement_chunk_requests": initial_chunk_requests,
        "supplement_chunk_retry_requests": len(retry_tasks),
        "supplement_chunk_ms": round(supplement_chunk_ms, 1),
        "token_cache_hits": sum(1 for status in cache_statuses if status == "hit"),
        "token_cache_misses": sum(1 for status in cache_statuses if status == "miss"),
        "token_cache_stale": sum(1 for status in cache_statuses if status == "stale"),
        "token_cache_ttl_s": MONITORING_BEACON_TOKEN_TTL,
        **bulk_detail,
    }
    return bulk_results + supplement_results, warnings, timing

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


