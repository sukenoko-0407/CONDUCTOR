from __future__ import annotations

import subprocess
import sys
from pathlib import Path


arguments = sys.argv[1:]
if not arguments or arguments[0] not in {"inspect", "cancel", "disable-result"}:
    raise SystemExit("Usage: run.py inspect|cancel|disable-result ...")
operation = arguments.pop(0)
try:
    run_root = Path(arguments[arguments.index("--run-root") + 1]).resolve()
except (ValueError, IndexError) as exc:
    raise SystemExit("ERROR: --run-root is required") from exc
for candidate in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents, Path.cwd(), *Path.cwd().parents]:
    controller = candidate / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
    if controller.is_file():
        break
else:
    raise SystemExit("ERROR: Runtime Controller not found")
runtime_command = {"inspect": "node-inspect", "cancel": "node-cancel", "disable-result": "result-disable"}[operation]
if operation != "inspect":
    key = (run_root / "runtime" / "dispatcher.key").read_text(encoding="utf-8").strip()
    arguments += ["--dispatcher-key", key]
raise SystemExit(subprocess.call([sys.executable, str(controller), runtime_command, *arguments]))
