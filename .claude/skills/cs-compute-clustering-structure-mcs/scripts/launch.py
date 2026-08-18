from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import json
import hashlib
from pathlib import Path


def prepare_runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache_root = env_dir / "cache"
    pixi_cache = cache_root / "pixi"
    attempt_tmp = Path(os.environ.get("CONDUCTOR_ATTEMPT_TMP", str(env_dir / "tmp"))).resolve()
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
        "HF_HOME": cache_root / "huggingface",
        "TORCH_HOME": cache_root / "torch",
        "CUDA_CACHE_PATH": cache_root / "cuda",
        "TRITON_CACHE_DIR": cache_root / "triton",
        "TORCHINDUCTOR_CACHE_DIR": cache_root / "torchinductor",
        "JOBLIB_TEMP_FOLDER": attempt_tmp / "joblib",
        "TMPDIR": attempt_tmp,
        "TMP": attempt_tmp,
        "TEMP": attempt_tmp,
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    runtime_env = os.environ.copy()
    runtime_env.update({name: str(path) for name, path in locations.items()})
    runtime_env.update(
        {
            "PIXI_CACHE_NETFS_REDIRECT": "never",
            "PIXI_NO_CONFIG": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return runtime_env


skill_dir = Path(__file__).resolve().parents[1]
arguments = sys.argv[1:]
runner = skill_dir / "scripts" / "run.py"
if arguments and arguments[0] == "render" and (skill_dir / "scripts" / "render.py").is_file():
    runner = skill_dir / "scripts" / "render.py"
    arguments = arguments[1:]
manifest = (skill_dir / "env" / "pixi.toml").resolve()
shared_pixi = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared_pixi) if shared_pixi.is_file() and os.access(shared_pixi, os.X_OK) else shutil.which("pixi")
if not pixi:
    print(
        f"ERROR: pixi is required. Shared binary was not executable at {shared_pixi}; "
        "install pixi on PATH and rerun this launcher. "
        "pixi will create or reuse the Skill environment from env/pixi.toml.",
        file=sys.stderr,
    )
    raise SystemExit(127)
runtime_env = prepare_runtime_environment(skill_dir)
capability = json.loads((skill_dir / "capability.json").read_text(encoding="utf-8"))
if capability.get("implementation", {}).get("algorithm") == "chemberta_embedding":
    runtime_env["CUDA_VISIBLE_DEVICES"] = ""
print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
lockfile = manifest.with_name("pixi.lock")
ready_marker = manifest.parent / ".environment-ready"
bootstrap_lock = manifest.parent / ".bootstrap.lock"
lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing"
environment_ready = ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash
if not environment_ready:
    acquired = False
    for _ in range(600):
        try:
            bootstrap_lock.mkdir()
            acquired = True
            break
        except FileExistsError:
            if ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash:
                break
            time.sleep(1)
    if acquired:
        try:
            install = [pixi, "install", "--manifest-path", str(manifest)]
            if lockfile.is_file():
                install.append("--locked")
            completed = subprocess.run(install, env=runtime_env)
            if completed.returncode:
                raise SystemExit(completed.returncode)
            if not lockfile.is_file():
                print(f"ERROR: pixi did not create the expected lock file: {lockfile}", file=sys.stderr)
                raise SystemExit(78)
            lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest()
            ready_marker.write_text(lock_hash + "\n", encoding="utf-8")
        finally:
            bootstrap_lock.rmdir()
    elif not (ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash):
        print("ERROR: timed out waiting for the Skill environment bootstrap lock", file=sys.stderr)
        raise SystemExit(75)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *arguments]
raise SystemExit(subprocess.call(command, env=runtime_env))
