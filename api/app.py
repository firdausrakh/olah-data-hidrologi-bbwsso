"""Flask entry point.

The heavy telemetry adapters live in ``api.core`` while HTTP concerns are split
across ``api.routes``. Keeping this file small makes Vercel and local startup
predictable and keeps route changes isolated from vendor parsing logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ``python api/app.py`` places /api on sys.path, while package imports expect the
# repository root. Keep direct local execution backward compatible.
if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    root_text = str(ROOT_DIR)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

from api.core import app  # noqa: E402

# Importing the route modules registers their decorators on the shared app.
from api.routes import auth as _auth_routes  # noqa: E402,F401
from api.routes import telemetry as _telemetry_routes  # noqa: E402,F401
from api.routes import monitoring as _monitoring_routes  # noqa: E402,F401
from api.routes import download as _download_routes  # noqa: E402,F401


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
