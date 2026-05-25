from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(data: Any, *, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(json.dumps(data, default=str))


def emit_error(message: str, *, code: int = 1) -> None:
    print(json.dumps({"error": message}), file=sys.stderr)
    raise SystemExit(code)
