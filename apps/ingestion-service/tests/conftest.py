from __future__ import annotations

import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]

for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        mod = sys.modules.get(name)
        mod_file = getattr(mod, "__file__", "") if mod is not None else ""
        if "ingestion-service" not in str(mod_file):
            sys.modules.pop(name, None)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
