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
    expected = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing"
    if not (ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected):
        acquired = False
        for _ in range(600):
            try:
                mutex.mkdir()
                acquired = True
                break
            except FileExistsError:
                if ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected:
                    break
                time.sleep(1)
        if acquired:
            try:
                command = [pixi, "install", "--manifest-path", str(manifest)]
                if lockfile.is_file():
                    command.append("--locked")
                result = subprocess.run(command, env=env)
                if result.returncode:
                    return result.returncode
                expected = hashlib.sha256(lockfile.read_bytes()).hexdigest()
                ready.write_text(expected + "\n", encoding="utf-8")
            finally:
                mutex.rmdir()
        elif not (ready.is_file() and ready.read_text(encoding="utf-8").strip() == expected):
            print("ERROR: timed out waiting for Skill environment bootstrap", file=sys.stderr)
            return 75
    arguments = sys.argv[1:]
    runner = skill_dir / "scripts" / "run.py"
    if arguments and arguments[0] == "render":
        runner = skill_dir / "scripts" / "render.py"
        arguments = arguments[1:]
    command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *arguments]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
