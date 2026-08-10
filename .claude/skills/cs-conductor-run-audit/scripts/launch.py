from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def prepare_runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache = env_dir / "cache"
    pixi_cache = cache / "pixi"
    locations = {
        "PIXI_HOME": env_dir / "pixi-home", "PIXI_CACHE_DIR": pixi_cache,
        "PIXI_CACHE_CONDA_PACKAGES_DIR": pixi_cache / "conda-packages",
        "PIXI_CACHE_REPODATA_DIR": pixi_cache / "repodata",
        "PIXI_CACHE_PYPI_WHEELS_DIR": pixi_cache / "pypi-wheels",
        "PIXI_CACHE_PYPI_MAPPING_DIR": pixi_cache / "pypi-mapping",
        "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR": pixi_cache / "exec-environments",
        "PIXI_CACHE_BUILD_TOOL_ENVIRONMENTS_DIR": pixi_cache / "build-tool-environments",
        "PIXI_CACHE_DETACHED_ENVIRONMENTS_DIR": pixi_cache / "detached-environments",
        "RATTLER_CACHE_DIR": pixi_cache, "UV_CACHE_DIR": cache / "uv",
        "PIP_CACHE_DIR": cache / "pip", "XDG_CACHE_HOME": cache / "xdg",
        "XDG_CONFIG_HOME": env_dir / "config", "XDG_DATA_HOME": env_dir / "data",
        "XDG_STATE_HOME": env_dir / "state", "TMPDIR": env_dir / "tmp",
        "TMP": env_dir / "tmp", "TEMP": env_dir / "tmp",
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    result = os.environ.copy()
    result.update({key: str(value) for key, value in locations.items()})
    result.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
    return result


skill_dir = Path(__file__).resolve().parents[1]
shared = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared) if shared.is_file() and os.access(shared, os.X_OK) else shutil.which("pixi")
if not pixi:
    print(f"ERROR: pixi is required; shared binary was not executable at {shared}", file=sys.stderr)
    raise SystemExit(127)
runtime_env = prepare_runtime_environment(skill_dir)
manifest=(skill_dir/"env"/"pixi.toml").resolve();lockfile=manifest.with_name("pixi.lock")
if not lockfile.is_file():
    subprocess.check_call([pixi,"install","--manifest-path",str(manifest)],env=runtime_env)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(skill_dir / "scripts" / "audit.py"), *sys.argv[1:]]
raise SystemExit(subprocess.call(command, env=runtime_env))
