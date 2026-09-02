from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def workspace() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / ".claude" / "skills").is_dir() and (candidate / "CONDUCTOR_modules" / "VERSION").is_file():
            return candidate
    raise FileNotFoundError("CONDUCTOR workspace was not found")


def selected_names(selection: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("description_skills", "clustering_skills", "analysis_skills", "interpretation_skills", "support_skills"):
        values = selection.get(key)
        if not isinstance(values, list): raise ValueError(f"included_skills.json requires array {key}")
        names.extend(str(value) for value in values)
    if len(names) != len(set(names)): raise ValueError("included_skills.json contains duplicate Skill names")
    return names


def render(catalog: dict[str, Any]) -> str:
    lines = ["# CONDUCTOR Skill Catalog", "", "> 収載対象は人間管理の`included_skills.json`、実行範囲は`analysis_profile.json`を正本とする。", "", f"CONDUCTOR: `{catalog['conductor_version']}`", ""]
    for stage in ("description", "clustering", "analysis", "interpretation", "orchestration"):
        entries = [item for item in catalog["capabilities"] if item.get("stage") == stage]
        if not entries: continue
        lines += [f"## {stage.title()}", "", "| ID | 名称 | 主な役割 | Cost |", "|---|---|---|---|"]
        for item in entries:
            lines.append(f"| {item['capability_id']} | {item['display_name']} | {item.get('description','')} | {item.get('cost',{}).get('class','-')} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(root: Path) -> tuple[dict[str, Any], str]:
    modules = root / "CONDUCTOR_modules"; version = (modules / "VERSION").read_text(encoding="utf-8").strip()
    selection_path = modules / "catalog" / "included_skills.json"; selection = json.loads(selection_path.read_text(encoding="utf-8")); names = selected_names(selection)
    profile_path = modules / "catalog" / "analysis_profile.json"; profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("conductor_version") != version: raise ValueError("analysis_profile conductor_version differs from VERSION")
    capabilities=[]
    for name in names:
        path=root/".claude"/"skills"/name/"capability.json"
        if not path.is_file(): raise FileNotFoundError(f"Selected Skill has no capability.json: {name}")
        value=json.loads(path.read_text(encoding="utf-8"))
        for key in ("capability_id","skill_name","display_name","stage"):
            if not value.get(key): raise ValueError(f"{name}: capability metadata lacks {key}")
        if value["skill_name"] != name: raise ValueError(f"{name}: skill_name mismatch")
        capabilities.append(value)
    capabilities.sort(key=lambda item:(item.get("stage",""),item["capability_id"]))
    ids=[item["capability_id"] for item in capabilities]
    if len(ids)!=len(set(ids)): raise ValueError("Selected capability IDs are not unique")
    catalog={"schema_version":"1.0.0","conductor_version":version,"profile_id":profile["profile_id"],"profile_hash":hashlib.sha256(profile_path.read_bytes()).hexdigest(),"selection_hash":hashlib.sha256(selection_path.read_bytes()).hexdigest(),"generated_at":datetime.now(timezone.utc).isoformat(),"capabilities":capabilities}
    return catalog,render(catalog)


def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--write",action="store_true"); parser.add_argument("--check",action="store_true"); args=parser.parse_args(); root=workspace(); modules=root/"CONDUCTOR_modules"; catalog,markdown=build(root); cp=modules/"catalog"/"catalog.json"; mp=modules/"docs"/"CONDUCTOR_skill_catalog.md"
    if args.write:
        cp.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); mp.write_text(markdown,encoding="utf-8")
    else:
        if not cp.is_file() or not mp.is_file(): raise FileNotFoundError("Generated Catalog is missing; run --write")
        old=json.loads(cp.read_text(encoding="utf-8")); old.pop("generated_at",None); current=dict(catalog); current.pop("generated_at",None)
        if old!=current or mp.read_text(encoding="utf-8")!=render({**catalog,"generated_at":json.loads(cp.read_text(encoding="utf-8")).get("generated_at")}): raise ValueError("Generated Catalog is stale; run --write")
    print(json.dumps({"status":"ok","capability_count":len(catalog["capabilities"])},ensure_ascii=False)); return 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(1)
