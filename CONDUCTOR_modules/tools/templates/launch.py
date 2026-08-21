from __future__ import annotations

import os
import shutil
import subprocess
import sys
import json
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
    runtime_env.update(
        {
            "PIXI_CACHE_NETFS_REDIRECT": "never",
            "PIXI_NO_CONFIG": "1",
        }
    )
    return runtime_env


def option_value(arguments: list[str], option: str, default: int) -> int:
    """Read a positive integer CLI option before importing the scientific stack."""
    try:
        position = arguments.index(option)
    except ValueError:
        return default
    if position + 1 >= len(arguments):
        return default
    try:
        value = int(arguments[position + 1])
    except ValueError:
        return default
    return value if value > 0 else default


def configure_xtb_process_environment(
    runtime_env: dict[str, str], arguments: list[str], capability: dict[str, object]
) -> None:
    """Set native thread limits before NumPy, BLAS, or tblite is imported."""
    implementation = capability.get("implementation", {})
    if not isinstance(implementation, dict) or implementation.get("algorithm") != "tblite_xtb":
        return
    default_threads = int(implementation.get("default_cores_per_compound", 4))
    threads = option_value(arguments, "--cores-per-compound", default_threads)
    runtime_env.update(
        {
            "OMP_NUM_THREADS": f"{threads},1",
            "OMP_THREAD_LIMIT": str(threads),
            "OMP_MAX_ACTIVE_LEVELS": "1",
            "OMP_DYNAMIC": "FALSE",
            "OMP_NESTED": "FALSE",
            "OPENBLAS_NUM_THREADS": "1",
            "BLIS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "MKL_NUM_THREADS": str(threads),
            "MKL_DYNAMIC": "FALSE",
        }
    )


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
configure_xtb_process_environment(runtime_env, arguments, capability)
print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
command = [pixi, "run", "--manifest-path", str(manifest), "python", str(runner), *arguments]
raise SystemExit(subprocess.call(command, env=runtime_env))
