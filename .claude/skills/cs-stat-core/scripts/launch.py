from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache_root = env_dir / "cache"
    locations = {
        "PIXI_HOME": env_dir / "pixi-home",
        "PIXI_CACHE_DIR": cache_root / "pixi",
        "UV_CACHE_DIR": cache_root / "uv",
        "PIP_CACHE_DIR": cache_root / "pip",
        "XDG_CACHE_HOME": cache_root / "xdg",
        "XDG_CONFIG_HOME": env_dir / "config",
        "XDG_DATA_HOME": env_dir / "data",
        "XDG_STATE_HOME": env_dir / "state",
        "TMPDIR": env_dir / "tmp",
        "TMP": env_dir / "tmp",
        "TEMP": env_dir / "tmp",
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    result = os.environ.copy()
    result.update({name: str(path) for name, path in locations.items()})
    result["PIXI_NO_CONFIG"] = "1"
    return result


def _pixi() -> str:
    configured = os.environ.get("CONDUCTOR_PIXI")
    candidates = [
        configured,
        "/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi",
        shutil.which("pixi"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError("pixi was not found; set CONDUCTOR_PIXI or add pixi to PATH")


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    command = [
        _pixi(),
        "run",
        "--manifest-path",
        str(skill_dir / "env" / "pixi.toml"),
        "--locked",
        "python",
        str(skill_dir / "scripts" / "run.py"),
        *sys.argv[1:],
    ]
    return subprocess.run(command, env=_runtime_environment(skill_dir), check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(4)
