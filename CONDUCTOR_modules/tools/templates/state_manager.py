from __future__ import annotations

import runpy
from pathlib import Path


here = Path(__file__).resolve()
for candidate in [here.parent, *here.parents, Path.cwd(), *Path.cwd().parents]:
    controller = candidate / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
    if controller.is_file():
        runpy.run_path(str(controller), run_name="__main__")
        break
else:
    raise SystemExit("ERROR: CONDUCTOR_modules/tools/runtime_controller.py was not found")
