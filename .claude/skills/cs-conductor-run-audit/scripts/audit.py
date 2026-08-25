from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / "CONDUCTOR_modules" / "tools" / "runtime_controller.py").is_file():
            return candidate
    raise FileNotFoundError("CONDUCTOR package root not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CONDUCTOR 0.1.6/0.1.7 audit")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--mode", choices=("quick", "full"), default="full")
    args = parser.parse_args()
    controller = project_root() / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
    return subprocess.call([sys.executable, str(controller), "audit", "--run-root", args.run_root, "--mode", args.mode], cwd=project_root())


if __name__ == "__main__":
    raise SystemExit(main())
