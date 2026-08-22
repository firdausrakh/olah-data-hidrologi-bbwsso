"""Configuration for local + Vercel/GitHub deployment.

For Vercel, set APP_PASSWORDS plus the vendor credentials (BEACON, HIGERTECH, TATONAS, DASHINDO) as Project Environment Variables.
For local use, you may also create a private .env-like shell configuration or
edit the fallback placeholders below, but do NOT commit real credentials.
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ===== CREDENTIALS =====
# Vercel/GitHub: set these in Vercel Project Settings > Environment Variables.
# Local: if environment variables are absent, replace placeholders locally.
BEACON_USERNAME = _env("BEACON_USERNAME", "ISI_USERNAME_BEACON")
BEACON_PASSWORD = _env("BEACON_PASSWORD", "ISI_PASSWORD_BEACON")

# ===== APP ACCESS =====
# Multiple passwords for internal access to the Server Telemetri feature.
# Preferred format: APP_PASSWORDS=password_1,password_2,password_3
# APP_PASSWORD remains a backward-compatible fallback for older deployments.
APP_PASSWORDS = _env("APP_PASSWORDS", _env("APP_PASSWORD", ""))
SESSION_SECRET = _env("SESSION_SECRET", "GANTI_SESSION_SECRET_YANG_PANJANG_DAN_ACAK")

BEACON_USERNAME_FIELD = _env("BEACON_USERNAME_FIELD", "username")
BEACON_PASSWORD_FIELD = _env("BEACON_PASSWORD_FIELD", "password")

# ===== SOURCE =====
BBWS_BASE_URL = _env("BBWS_BASE_URL", "https://bbwsso.monitoring4system.com")

# ===== PERFORMANCE =====
BBWS_TIMEOUT = int(_env("BBWS_TIMEOUT", "45"))
PARAMETER_CACHE_TTL = int(_env("PARAMETER_CACHE_TTL", "21600"))

# Beacon never sends one request larger than 25 days. MAX_QUERY_DAYS is kept
# only as a backward-compatible alias/fallback for older deployments.
BEACON_CHUNK_DAYS = int(_env("BEACON_CHUNK_DAYS", _env("MAX_QUERY_DAYS", "25")))
MAX_QUERY_DAYS = BEACON_CHUNK_DAYS
BEACON_PARALLEL_WORKERS = int(_env("BEACON_PARALLEL_WORKERS", "3"))
BEACON_PROCESS_TOKEN_TTL = int(_env("BEACON_PROCESS_TOKEN_TTL", "300"))

# Independent Higertech monthly exports may run in parallel. Keep conservative
# defaults to avoid overloading the vendor server / Vercel function.
HIGERTECH_PARALLEL_WORKERS = int(_env("HIGERTECH_PARALLEL_WORKERS", "3"))
HIGERTECH_EXPORT_CACHE_TTL = int(_env("HIGERTECH_EXPORT_CACHE_TTL", "900"))
HIGERTECH_EXPORT_CACHE_MAX = int(_env("HIGERTECH_EXPORT_CACHE_MAX", "12"))
# Upstream Higertech tetap export per bulan (default = 1 bulan).
HIGERTECH_CHUNK_MONTHS = int(_env("HIGERTECH_CHUNK_MONTHS", "1"))
HIGERTECH_EXPORT_TIMEOUT = int(_env("HIGERTECH_EXPORT_TIMEOUT", "120"))
# Pengolahan <= ~2 bulan: native JSON 5-menit per hari, paralel, XLSX fallback.
HIGERTECH_CHART_DAY_WORKERS = int(_env("HIGERTECH_CHART_DAY_WORKERS", "8"))
HIGERTECH_CHART_TIMEOUT = float(_env("HIGERTECH_CHART_TIMEOUT", "8"))
HIGERTECH_CHART_MAX_DAYS = int(_env("HIGERTECH_CHART_MAX_DAYS", "62"))
HIGERTECH_CHART_CACHE_TTL = int(_env("HIGERTECH_CHART_CACHE_TTL", "21600"))
HIGERTECH_CHART_TODAY_CACHE_TTL = int(_env("HIGERTECH_CHART_TODAY_CACHE_TTL", "60"))
HIGERTECH_CHART_CACHE_MAX = int(_env("HIGERTECH_CHART_CACHE_MAX", "256"))

# ===== HIGERTECH SOURCE =====
HIGERTECH_BASE_URL = _env("HIGERTECH_BASE_URL", "https://bbwsserayuopak.higertech.com")
# Higertech credentials are intentionally separate from Beacon credentials.
HIGERTECH_USERNAME = _env("HIGERTECH_USERNAME", "ISI_USERNAME_HIGERTECH")
HIGERTECH_PASSWORD = _env("HIGERTECH_PASSWORD", "ISI_PASSWORD_HIGERTECH")

# ===== TATONAS SOURCE =====
TATONAS_BASE_URL = "https://tatonas.co.id"
TATONAS_USERNAME = _env("TATONAS_USERNAME", "ISI_USERNAME_TATONAS")
TATONAS_PASSWORD = _env("TATONAS_PASSWORD", "ISI_PASSWORD_TATONAS")
TATONAS_PLANT = "028"
TATONAS_CHUNK_MONTHS = int(_env("TATONAS_CHUNK_MONTHS", "3"))
TATONAS_PARALLEL_WORKERS = int(_env("TATONAS_PARALLEL_WORKERS", "2"))


# ===== DASHINDO SOURCE =====
DASHINDO_BASE_URL = _env("DASHINDO_BASE_URL", "http://202.180.30.82")
DASHINDO_SOCKET_URL = _env("DASHINDO_SOCKET_URL", "http://202.180.30.82:8000")
DASHINDO_USERNAME = _env("DASHINDO_USERNAME", "ISI_USERNAME_DASHINDO")
DASHINDO_PASSWORD = _env("DASHINDO_PASSWORD", "ISI_PASSWORD_DASHINDO")
# Keep below Vercel api/app.py maxDuration (60 s).
DASHINDO_WAIT_TIMEOUT = int(_env("DASHINDO_WAIT_TIMEOUT", "45"))
DASHINDO_PARALLEL_WORKERS = int(_env("DASHINDO_PARALLEL_WORKERS", "3"))
DASHINDO_CHUNK_MONTHS = int(_env("DASHINDO_CHUNK_MONTHS", "3"))
DASHINDO_DIRECT_RAW_ENABLED = _env("DASHINDO_DIRECT_RAW_ENABLED", "1")

# ===== UNIFIED MONITORING =====
MONITORING_CACHE_TTL = int(_env("MONITORING_CACHE_TTL", "300"))
MONITORING_BEACON_WORKERS = int(_env("MONITORING_BEACON_WORKERS", "3"))
