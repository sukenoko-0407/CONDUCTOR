from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir=(skill_dir/"env").resolve();cache=env_dir/"cache";pixi_cache=cache/"pixi"
    locations={"PIXI_HOME":env_dir/"pixi-home","PIXI_CACHE_DIR":pixi_cache,"PIXI_CACHE_CONDA_PACKAGES_DIR":pixi_cache/"conda-packages","PIXI_CACHE_REPODATA_DIR":pixi_cache/"repodata","PIXI_CACHE_PYPI_WHEELS_DIR":pixi_cache/"pypi-wheels","PIXI_CACHE_PYPI_MAPPING_DIR":pixi_cache/"pypi-mapping","PIXI_CACHE_EXEC_ENVIRONMENTS_DIR":pixi_cache/"exec-environments","RATTLER_CACHE_DIR":pixi_cache,"UV_CACHE_DIR":cache/"uv","PIP_CACHE_DIR":cache/"pip","XDG_CACHE_HOME":cache/"xdg","XDG_CONFIG_HOME":env_dir/"config","XDG_DATA_HOME":env_dir/"data","XDG_STATE_HOME":env_dir/"state","MPLCONFIGDIR":cache/"matplotlib","NUMBA_CACHE_DIR":cache/"numba","TMPDIR":env_dir/"tmp","TMP":env_dir/"tmp","TEMP":env_dir/"tmp"}
    for path in set(locations.values()):path.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update({k:str(v) for k,v in locations.items()});env.update({"PIXI_CACHE_NETFS_REDIRECT":"never","PIXI_NO_CONFIG":"1"});return env


skill_dir=Path(__file__).resolve().parents[1];arguments=sys.argv[1:]
if not arguments or arguments[0] not in {"catalog","state"}:
    print("Usage: launch.py catalog [args] | state [args]",file=sys.stderr);raise SystemExit(2)
script=skill_dir/"scripts"/("build_catalog.py" if arguments[0]=="catalog" else "state_manager.py");arguments=arguments[1:]
shared=Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi");pixi=str(shared) if shared.is_file() and os.access(shared,os.X_OK) else shutil.which("pixi")
if not pixi:print(f"ERROR: pixi is required; shared binary was not executable at {shared}.",file=sys.stderr);raise SystemExit(127)
manifest=(skill_dir/"env"/"pixi.toml").resolve();lockfile=manifest.with_name("pixi.lock");ready=manifest.parent/".environment-ready";mutex=manifest.parent/".bootstrap.lock";env=runtime_environment(skill_dir)
lock_hash=hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing";is_ready=ready.is_file() and ready.read_text(encoding="utf-8").strip()==lock_hash
if not is_ready:
    acquired=False
    for _ in range(600):
        try:mutex.mkdir();acquired=True;break
        except FileExistsError:
            if ready.is_file() and lockfile.is_file() and ready.read_text(encoding="utf-8").strip()==hashlib.sha256(lockfile.read_bytes()).hexdigest():break
            time.sleep(1)
    if acquired:
        try:
            command=[pixi,"install","--manifest-path",str(manifest)]+(["--locked"] if lockfile.is_file() else [])
            code=subprocess.call(command,env=env)
            if code:raise SystemExit(code)
            if not lockfile.is_file():print(f"ERROR: pixi did not create {lockfile}",file=sys.stderr);raise SystemExit(78)
            ready.write_text(hashlib.sha256(lockfile.read_bytes()).hexdigest()+"\n",encoding="utf-8")
        finally:mutex.rmdir()
    elif not (ready.is_file() and lockfile.is_file()):print("ERROR: timed out waiting for environment bootstrap",file=sys.stderr);raise SystemExit(75)
command=[pixi,"run","--manifest-path",str(manifest),"--locked","python",str(script),*arguments]
raise SystemExit(subprocess.call(command,env=env))
