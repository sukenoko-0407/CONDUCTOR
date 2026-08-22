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

from conductor_request_adapter import request_to_cli


def runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache = env_dir / "cache"
    tmp = Path(os.environ.get("CONDUCTOR_ATTEMPT_TMP", str(env_dir / "tmp"))).resolve()
    locations = {
        "PIXI_HOME": env_dir / "pixi-home",
        "PIXI_CACHE_DIR": cache / "pixi",
        "PIXI_CACHE_CONDA_PACKAGES_DIR": cache / "pixi" / "conda-packages",
        "PIXI_CACHE_REPODATA_DIR": cache / "pixi" / "repodata",
        "PIXI_CACHE_PYPI_WHEELS_DIR": cache / "pixi" / "pypi-wheels",
        "RATTLER_CACHE_DIR": cache / "pixi",
        "UV_CACHE_DIR": cache / "uv",
        "PIP_CACHE_DIR": cache / "pip",
        "XDG_CACHE_HOME": cache / "xdg",
        "XDG_CONFIG_HOME": env_dir / "config",
        "XDG_DATA_HOME": env_dir / "data",
        "XDG_STATE_HOME": env_dir / "state",
        "MPLCONFIGDIR": cache / "matplotlib",
        "JOBLIB_TEMP_FOLDER": tmp / "joblib",
        "TMPDIR": tmp,
        "TMP": tmp,
        "TEMP": tmp,
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({key: str(value) for key, value in locations.items()})
    env.update({"PIXI_CACHE_NETFS_REDIRECT": "never", "PIXI_NO_CONFIG": "1"})
    return env


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


def recover_stale_mutex(mutex: Path) -> bool:
    try:
        owner = json.loads((mutex / "owner.json").read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(owner["created_at"]))
        same_host = owner.get("host") == socket.gethostname()
        try:
            os.kill(int(owner.get("pid", -1)), 0)
            alive = True
        except OSError:
            alive = False
        stale = (same_host and not alive) or datetime.now(timezone.utc) - created > timedelta(hours=2)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            stale = time.time() - mutex.stat().st_mtime > 2 * 60 * 60
        except OSError:
            return False
    if stale:
        shutil.rmtree(mutex, ignore_errors=True)
    return stale


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    manifest = (skill_dir / "env" / "pixi.toml").resolve()
    shared = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
    pixi = str(shared) if shared.is_file() and os.access(shared, os.X_OK) else shutil.which("pixi")
    if not pixi:
        print(f"ERROR: pixi is required; shared binary is unavailable at {shared}", file=sys.stderr)
        return 127
    env = runtime_environment(skill_dir)
    lockfile = manifest.with_name("pixi.lock")
    ready = manifest.parent / ".environment-ready"
    mutex = manifest.parent / ".bootstrap.lock"
    environment = manifest.parent / ".pixi" / "envs" / "default"
    expected = environment_fingerprint(manifest, lockfile)
    if not (environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected):
        acquired = False
        for _ in range(600):
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
                if environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
                    break
                if recover_stale_mutex(mutex):
                    continue
                time.sleep(1)
        if acquired:
            try:
                command = [pixi, "install", "--manifest-path", str(manifest)]
                if lockfile.is_file():
                    command.append("--locked")
                result = subprocess.run(command, env=env)
                if result.returncode:
                    return result.returncode
                expected = environment_fingerprint(manifest, lockfile)
                if not expected:
                    raise RuntimeError(f"pixi did not create a lockfile: {lockfile}")
                ready.write_text(expected + "\n", encoding="utf-8")
            finally:
                shutil.rmtree(mutex, ignore_errors=True)
        elif not (environment.is_dir() and expected and ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected):
            print("ERROR: timed out waiting for Skill environment bootstrap", file=sys.stderr)
            return 75
    arguments = sys.argv[1:]
    capability = json.loads((skill_dir / "capability.json").read_text(encoding="utf-8"))
    if arguments[:1] == ["--conductor-request"]:
        if len(arguments) != 2:
            print("ERROR: --conductor-request accepts exactly one JSON path", file=sys.stderr)
            return 2
        try:
            arguments = request_to_cli(arguments[1], capability)
        except Exception as exc:
            print(f"ERROR: invalid CONDUCTOR Execution Request: {exc}", file=sys.stderr)
            return 2
    runner = skill_dir / "scripts" / "run.py"
    if arguments and arguments[0] == "render":
        runner = skill_dir / "scripts" / "render.py"
        arguments = arguments[1:]
    command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *arguments]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
