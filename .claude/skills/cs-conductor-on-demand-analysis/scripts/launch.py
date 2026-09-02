from __future__ import annotations

import os
import shutil
import subprocess
import sys
import hashlib
import json
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def prepare_runtime_environment(skill_dir: Path) -> dict[str, str]:
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
        "HF_HOME": cache_root / "huggingface",
        "TORCH_HOME": cache_root / "torch",
        "CUDA_CACHE_PATH": cache_root / "cuda",
        "TRITON_CACHE_DIR": cache_root / "triton",
        "TORCHINDUCTOR_CACHE_DIR": cache_root / "torchinductor",
        "JOBLIB_TEMP_FOLDER": env_dir / "tmp" / "joblib",
        "TMPDIR": env_dir / "tmp",
        "TMP": env_dir / "tmp",
        "TEMP": env_dir / "tmp",
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    runtime_env = os.environ.copy()
    runtime_env.update({name: str(path) for name, path in locations.items()})
    runtime_env.update({
        "PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1",
        "PIP_NO_INDEX": "1", "UV_OFFLINE": "1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    return runtime_env


def ensure_environment(pixi: str, manifest: Path, runtime_env: dict[str, str]) -> None:
    """Build the shared On-demand environment once under concurrent requests."""
    env_dir = manifest.parent
    lockfile = manifest.with_name("pixi.lock")
    ready = env_dir / ".environment-ready"
    mutex = env_dir / ".bootstrap.lock"
    environment = env_dir / ".pixi" / "envs" / "default"

    def fingerprint() -> str | None:
        if not lockfile.is_file():
            return None
        digest = hashlib.sha256()
        digest.update(manifest.read_bytes())
        digest.update(b"\0")
        digest.update(lockfile.read_bytes())
        digest.update(b"\0")
        digest.update(sys.platform.encode("utf-8"))
        return digest.hexdigest()

    def process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == 259
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def recover_stale_mutex() -> bool:
        try:
            owner = json.loads((mutex / "owner.json").read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(owner["created_at"]))
            same_host = owner.get("host") == socket.gethostname()
            owner_alive = same_host and process_alive(int(owner.get("pid", -1)))
            stale = (same_host and not owner_alive) or (
                not same_host and datetime.now(timezone.utc) - created > timedelta(hours=8)
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            try:
                stale = time.time() - mutex.stat().st_mtime > 8 * 60 * 60
            except OSError:
                return False
        if stale:
            shutil.rmtree(mutex, ignore_errors=True)
        return stale

    expected = fingerprint()
    if environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
        return
    acquired = False
    for _ in range(3600):
        try:
            mutex.mkdir()
            (mutex / "owner.json").write_text(
                json.dumps({
                    "pid": os.getpid(), "host": socket.gethostname(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }),
                encoding="utf-8",
            )
            acquired = True
            break
        except FileExistsError:
            expected = fingerprint()
            if environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
                return
            if recover_stale_mutex():
                continue
            time.sleep(1)
    if not acquired:
        raise TimeoutError(f"Timed out waiting for On-demand environment bootstrap: {mutex}")
    try:
        install = [pixi, "install", "--manifest-path", str(manifest)]
        if lockfile.is_file():
            install.append("--locked")
        completed = subprocess.run(install, env=runtime_env)
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)
        expected = fingerprint()
        if not expected:
            raise RuntimeError(f"pixi did not create a lockfile: {lockfile}")
        ready.write_text(expected + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(mutex, ignore_errors=True)


skill_dir = Path(__file__).resolve().parents[1]
manifest = (skill_dir / "env" / "pixi.toml").resolve()
runner = skill_dir / "scripts" / "run.py"
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
print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
ensure_environment(pixi, manifest, runtime_env)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *sys.argv[1:]]
raise SystemExit(subprocess.call(command, env=runtime_env))
