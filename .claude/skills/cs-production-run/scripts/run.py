from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
TOOLS = PROJECT_ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from production_run import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
