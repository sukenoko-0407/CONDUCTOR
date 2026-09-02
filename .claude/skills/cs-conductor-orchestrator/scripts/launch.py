from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run the stdlib-only Main-Agent wrapper through the one Runtime env."""
    skill_dir = Path(__file__).resolve().parents[1]
    runner = skill_dir / "scripts" / "run.py"
    if not runner.is_file():
        print(f"ERROR: Orchestrator wrapper is missing: {runner}", file=sys.stderr)
        return 127
    return subprocess.call([sys.executable, str(runner), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
