from __future__ import annotations
import json, os, shutil, subprocess, sys
from pathlib import Path

def main() -> int:
    skill=Path(__file__).resolve().parents[1]; shared=Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi"); pixi=next((str(Path(candidate).resolve()) for candidate in (os.environ.get("CONDUCTOR_PIXI"),str(shared),shutil.which("pixi")) if candidate and Path(candidate).is_file()),None)
    if not pixi: raise FileNotFoundError("pixi was not found; set CONDUCTOR_PIXI or add pixi to PATH")
    env=os.environ.copy()
    for name,relative in {"PIXI_HOME":"pixi-home","PIXI_CACHE_DIR":"cache/pixi","UV_CACHE_DIR":"cache/uv","PIP_CACHE_DIR":"cache/pip","XDG_CACHE_HOME":"cache/xdg","XDG_CONFIG_HOME":"config","XDG_DATA_HOME":"data","XDG_STATE_HOME":"state","TMPDIR":"tmp","TMP":"tmp","TEMP":"tmp"}.items():
        path=skill/"env"/relative; path.mkdir(parents=True,exist_ok=True); env[name]=str(path.resolve())
    env["PIXI_NO_CONFIG"]="1"; return subprocess.run([str(Path(pixi).resolve()),"run","--manifest-path",str(skill/"env"/"pixi.toml"),"--locked","python",str(skill/"scripts"/"run.py"),*sys.argv[1:]],env=env,check=False).returncode

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc: print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr); raise SystemExit(4)
