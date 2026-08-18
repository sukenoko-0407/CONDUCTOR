from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


skill_dir = Path(__file__).resolve().parents[1]
env_dir = skill_dir / "env"
cache = env_dir / "cache"
locations = {"PIXI_HOME": env_dir / "pixi-home", "PIXI_CACHE_DIR": cache / "pixi", "UV_CACHE_DIR": cache / "uv", "XDG_CACHE_HOME": cache / "xdg", "TMPDIR": env_dir / "tmp", "TMP": env_dir / "tmp", "TEMP": env_dir / "tmp"}
for path in locations.values():
    path.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update({key: str(value.resolve()) for key, value in locations.items()})
env.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
shared = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared) if shared.is_file() and os.access(shared, os.X_OK) else shutil.which("pixi")
if not pixi:
    raise SystemExit("ERROR: pixi is required")
manifest = (env_dir / "pixi.toml").resolve()
lockfile = env_dir / "pixi.lock"
if not lockfile.is_file():
    subprocess.check_call([pixi, "install", "--manifest-path", str(manifest)], env=env)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str((skill_dir / "scripts" / "run.py").resolve()), *sys.argv[1:]]
raise SystemExit(subprocess.call(command, env=env))
