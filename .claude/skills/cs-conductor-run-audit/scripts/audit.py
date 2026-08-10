from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


SKILL_DIR=Path(__file__).resolve().parents[1]


def workspace()->Path:
    for root in [SKILL_DIR,*SKILL_DIR.parents,Path.cwd(),*Path.cwd().parents]:
        if (root/"CONDUCTOR_modules"/"tools"/"templates"/"state_manager.py").is_file():return root
    raise FileNotFoundError("CONDUCTOR package root not found")


def runtime_module():
    path=workspace()/"CONDUCTOR_modules"/"tools"/"templates"/"state_manager.py"
    spec=importlib.util.spec_from_file_location("conductor_audit_runtime",path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module);return module


def main()->int:
    parser=argparse.ArgumentParser(description="Read-only Quick/Full audit of an explicit CONDUCTOR State.")
    parser.add_argument("--state",required=True);parser.add_argument("--mode",choices=["quick","full"],default="full");args=parser.parse_args();state_path=Path(args.state).resolve();runtime=runtime_module();state=runtime.read_json(state_path);result=runtime.audit_state(state_path,state,args.mode);out=runtime.write_audit(state_path,result);print(json.dumps({"output_dir":str(out),"audit":result},ensure_ascii=False,indent=2));return 1 if result["status"]=="fail" else 0


if __name__=="__main__":
    try:raise SystemExit(main())
    except Exception as exc:print(f"ERROR: {exc}",file=sys.stderr);raise SystemExit(1)
