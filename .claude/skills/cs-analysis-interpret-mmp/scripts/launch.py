from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache_root = env_dir / "cache"
    pixi_cache = cache_root / "pixi"
    locations = {
        "PIXI_HOME": env_dir / "pixi-home",
        "PIXI_CACHE_DIR": pixi_cache,
        "PIXI_CACHE_CONDA_PACKAGES_DIR": pixi_cache / "conda-packages",
        "PIXI_CACHE_REPODATA_DIR": pixi_cache / "repodata",
        "PIXI_CACHE_PYPI_WHEELS_DIR": pixi_cache / "pypi-wheels",
        "PIXI_CACHE_PYPI_MAPPING_DIR": pixi_cache / "pypi-mapping",
        "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR": pixi_cache / "exec-environments",
        "PIXI_CACHE_BUILD_TOOL_ENVIRONMENTS_DIR": pixi_cache / "build-tool-environments",
        "PIXI_CACHE_DETACHED_ENVIRONMENTS_DIR": pixi_cache / "detached-environments",
        "RATTLER_CACHE_DIR": pixi_cache,
        "UV_CACHE_DIR": cache_root / "uv",
        "PIP_CACHE_DIR": cache_root / "pip",
        "XDG_CACHE_HOME": cache_root / "xdg",
        "XDG_CONFIG_HOME": env_dir / "config",
        "XDG_DATA_HOME": env_dir / "data",
        "XDG_STATE_HOME": env_dir / "state",
        "MPLCONFIGDIR": cache_root / "matplotlib",
        "NUMBA_CACHE_DIR": cache_root / "numba",
        "TMPDIR": env_dir / "tmp",
        "TMP": env_dir / "tmp",
        "TEMP": env_dir / "tmp",
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    value = os.environ.copy()
    value.update({name: str(path) for name, path in locations.items()})
    value.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
    return value


skill_dir = Path(__file__).resolve().parents[1]
manifest = (skill_dir / "env" / "pixi.toml").resolve()
lockfile = manifest.with_name("pixi.lock")
runner = skill_dir / "scripts" / "run.py"
shared_pixi = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared_pixi) if shared_pixi.is_file() and os.access(shared_pixi, os.X_OK) else shutil.which("pixi")
if not pixi:
    print("ERROR: pixi is required; the shared Linux binary was unavailable and pixi was not on PATH", file=sys.stderr)
    raise SystemExit(127)

environment = runtime_environment(skill_dir)
ready = manifest.parent / ".environment-ready"
bootstrap = manifest.parent / ".bootstrap.lock"
lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing"
if not (ready.is_file() and ready.read_text(encoding="utf-8").strip() == lock_hash):
    acquired = False
    for _ in range(600):
        try:
            bootstrap.mkdir()
            acquired = True
            break
        except FileExistsError:
            if ready.is_file() and ready.read_text(encoding="utf-8").strip() == lock_hash:
                break
            time.sleep(1)
    if acquired:
        try:
            command = [pixi, "install", "--manifest-path", str(manifest)]
            if lockfile.is_file():
                command.append("--locked")
            completed = subprocess.run(command, env=environment)
            if completed.returncode:
                raise SystemExit(completed.returncode)
            if not lockfile.is_file():
                raise RuntimeError("pixi did not create pixi.lock")
            lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest()
            ready.write_text(lock_hash + "\n", encoding="utf-8")
        finally:
            bootstrap.rmdir()
    elif not (ready.is_file() and ready.read_text(encoding="utf-8").strip() == lock_hash):
        raise RuntimeError("timed out waiting for the Skill environment bootstrap lock")

print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *sys.argv[1:]]
raise SystemExit(subprocess.call(command, env=environment))
