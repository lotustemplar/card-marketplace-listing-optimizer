from __future__ import annotations

import importlib
import sys

try:
    api_module = importlib.import_module("pricing_logic_api")
    sys.modules["pricing_logic_bulk"] = api_module
except Exception:
    pass
