from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


SHARED_PIXI = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")


def runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache = env_dir / "cache"
    pixi_cache = cache / "pixi"
    locations = {
        "PIXI_HOME": env_dir / "pixi-home",
        "PIXI_CACHE_DIR": pixi_cache,
        "PIXI_CACHE_CONDA_PACKAGES_DIR": pixi_cache / "conda-packages",
        "PIXI_CACHE_REPODATA_DIR": pixi_cache / "repodata",
        "PIXI_CACHE_PYPI_WHEELS_DIR": pixi_cache / "pypi-wheels",
        "PIXI_CACHE_PYPI_MAPPING_DIR": pixi_cache / "pypi-mapping",
        "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR": pixi_cache / "exec-environments",
        "RATTLER_CACHE_DIR": pixi_cache,
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
    environment.update({name: str(path) for name, path in locations.items()})
    environment.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
    return environment


def environment_fingerprint(manifest: Path, lockfile: Path) -> str | None:
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


def recover_stale_mutex(mutex: Path) -> bool:
    try:
        owner = json.loads((mutex / "owner.json").read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(owner["created_at"]))
        same_host = owner.get("host") == socket.gethostname()
        owner_alive = same_host and process_alive(int(owner.get("pid", -1)))
        stale = (same_host and not owner_alive) or (
            not same_host
            and datetime.now(timezone.utc) - created > timedelta(hours=8)
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            stale = time.time() - mutex.stat().st_mtime > 8 * 60 * 60
        except OSError:
            return False
    if stale:
        shutil.rmtree(mutex, ignore_errors=True)
    return stale


def ensure_environment(pixi: str, manifest: Path, environment: dict[str, str]) -> None:
    env_dir = manifest.parent
    lockfile = env_dir / "pixi.lock"
    ready = env_dir / ".environment-ready"
    mutex = env_dir / ".bootstrap.lock"
    pixi_environment = env_dir / ".pixi" / "envs" / "default"
    expected = environment_fingerprint(manifest, lockfile)
    if pixi_environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
        return
    acquired = False
    for _ in range(3600):
        try:
            mutex.mkdir()
            (mutex / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "created_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
            acquired = True
            break
        except FileExistsError:
            expected = environment_fingerprint(manifest, lockfile)
            if pixi_environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
                return
            if recover_stale_mutex(mutex):
                continue
            time.sleep(1)
    if not acquired:
        raise TimeoutError(f"Timed out waiting for Runtime environment bootstrap: {mutex}")
    try:
        command = [pixi, "install", "--manifest-path", str(manifest)]
        if lockfile.is_file():
            command.append("--locked")
        code = subprocess.call(command, env=environment)
        if code:
            raise SystemExit(code)
        expected = environment_fingerprint(manifest, lockfile)
        if not expected:
            raise RuntimeError(f"pixi did not create a lockfile: {lockfile}")
        ready.write_text(expected + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(mutex, ignore_errors=True)


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    arguments = sys.argv[1:]
    if not arguments or arguments[0] not in {"catalog", "state"}:
        print("Usage: launch.py catalog [args] | state [args]", file=sys.stderr)
        return 2
    script = skill_dir / "scripts" / ("build_catalog.py" if arguments[0] == "catalog" else "state_manager.py")
    arguments = arguments[1:]
    pixi = str(SHARED_PIXI) if SHARED_PIXI.is_file() and os.access(SHARED_PIXI, os.X_OK) else shutil.which("pixi")
    if not pixi:
        print(f"ERROR: pixi is required; shared binary was not executable at {SHARED_PIXI}.", file=sys.stderr)
        return 127
    manifest = (skill_dir / "env" / "pixi.toml").resolve()
    environment = runtime_environment(skill_dir)
    ensure_environment(pixi, manifest, environment)
    command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(script), *arguments]
    return subprocess.call(command, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
