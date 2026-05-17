from __future__ import annotations

import importlib
import sys

try:
    safe_module = importlib.import_module("pricing_logic_safe")
    sys.modules["pricing_logic_bulk"] = safe_module
except Exception:
    pass
