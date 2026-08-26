from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


skill_dir = Path(__file__).resolve().parents[1]
env_dir = (skill_dir / "env").resolve()
cache = env_dir / "cache"
locations = {
    "PIXI_HOME": env_dir / "pixi-home",
    "PIXI_CACHE_DIR": cache / "pixi",
    "PIXI_CACHE_CONDA_PACKAGES_DIR": cache / "pixi" / "conda-packages",
    "PIXI_CACHE_REPODATA_DIR": cache / "pixi" / "repodata",
    "PIXI_CACHE_PYPI_WHEELS_DIR": cache / "pixi" / "pypi-wheels",
    "PIXI_CACHE_PYPI_MAPPING_DIR": cache / "pixi" / "pypi-mapping",
    "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR": cache / "pixi" / "exec-environments",
    "RATTLER_CACHE_DIR": cache / "pixi",
    "UV_CACHE_DIR": cache / "uv",
    "PIP_CACHE_DIR": cache / "pip",
    "XDG_CACHE_HOME": cache / "xdg",
    "XDG_CONFIG_HOME": env_dir / "config",
    "XDG_DATA_HOME": env_dir / "data",
    "XDG_STATE_HOME": env_dir / "state",
    "MPLCONFIGDIR": cache / "matplotlib",
    "NUMBA_CACHE_DIR": cache / "numba",
    "TMPDIR": env_dir / "tmp",
    "TMP": env_dir / "tmp",
    "TEMP": env_dir / "tmp",
}
for path in set(locations.values()):
    path.mkdir(parents=True, exist_ok=True)
environment = os.environ.copy()
environment.update({key: str(path) for key, path in locations.items()})
environment.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
shared = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared) if shared.is_file() and os.access(shared, os.X_OK) else shutil.which("pixi")
if not pixi:
    raise SystemExit(f"ERROR: pixi is required; shared binary was not executable at {shared}.")
manifest = (env_dir / "pixi.toml").resolve()
lockfile = env_dir / "pixi.lock"
ready = env_dir / ".environment-ready"
mutex = env_dir / ".bootstrap.lock"
lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing"
if not (ready.is_file() and ready.read_text(encoding="utf-8").strip() == lock_hash):
    acquired = False
    for _ in range(600):
        try:
            mutex.mkdir()
            acquired = True
            break
        except FileExistsError:
            if ready.is_file() and lockfile.is_file() and ready.read_text(encoding="utf-8").strip() == hashlib.sha256(lockfile.read_bytes()).hexdigest():
                break
            time.sleep(1)
    if acquired:
        try:
            command = [pixi, "install", "--manifest-path", str(manifest)] + (["--locked"] if lockfile.is_file() else [])
            code = subprocess.call(command, env=environment)
            if code:
                raise SystemExit(code)
            ready.write_text(hashlib.sha256(lockfile.read_bytes()).hexdigest() + "\n", encoding="utf-8")
        finally:
            mutex.rmdir()
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str((skill_dir / "scripts" / "run.py").resolve()), *sys.argv[1:]]
raise SystemExit(subprocess.call(command, env=environment))

