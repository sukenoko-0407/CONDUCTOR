from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / "CONDUCTOR_modules" / "tools" / "runtime_controller.py").is_file():
            return candidate
    raise FileNotFoundError("CONDUCTOR Project root was not found")


arguments = sys.argv[1:]
if not arguments:
    raise SystemExit("Usage: run.py <runtime-dispatch-command> ...")
command_name = arguments[0]
needs_authority = command_name in {"authorize-round", "resume-round", "continue-round", "revise-report", "accept-round", "approve-high-cost", "request-checkpoint"} or (command_name == "verify-return" and "--confirm-returned" in arguments)
if needs_authority and "--dispatcher-key" not in arguments:
    try:
        run_root = Path(arguments[arguments.index("--run-root") + 1]).resolve()
    except (ValueError, IndexError) as exc:
        raise SystemExit("ERROR: --run-root is required") from exc
    key = (run_root / "runtime" / "dispatcher.key").read_text(encoding="utf-8").strip()
    arguments += ["--dispatcher-key", key]
controller = project_root() / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
raise SystemExit(subprocess.call([sys.executable, str(controller), *arguments], cwd=project_root()))
