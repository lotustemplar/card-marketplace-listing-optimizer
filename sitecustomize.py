from __future__ import annotations

import importlib
import sys

try:
    live_module = importlib.import_module("pricing_logic_live")
    sys.modules["pricing_logic_bulk"] = live_module
except Exception:
    pass
