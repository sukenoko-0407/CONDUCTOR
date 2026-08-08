from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = MODULE_ROOT.parent


def ignored(directory: str, names: list[str]) -> set[str]:
    ignored_names = {"__pycache__", ".pytest_cache", "Archive"}
    if Path(directory).name == "env":
        ignored_names.update({".pixi", "cache", "config", "data", "state", "tmp", "pixi-home"})
    ignored_names.update(name for name in names if name.endswith(".pyc"))
    return ignored_names.intersection(names)


def copy_targets(target: Path) -> list[tuple[Path, Path]]:
    selection = json.loads((MODULE_ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
    pairs = [
        (
            SOURCE_ROOT / ".claude" / "agents" / name,
            target / ".claude" / "agents" / name,
        )
        for name in ["cs-conductor-orchestrator.md", "cs-conductor-interpreter.md", "cs-conductor-v430-migrator.md"]
    ]
    pairs.extend(
        (
            SOURCE_ROOT / ".claude" / "skills" / name,
            target / ".claude" / "skills" / name,
        )
        for name in [
            *selection["included_skills"],
            *selection.get("maintenance_skills", []),
            *selection.get("support_skills", []),
        ]
    )
    pairs.append((MODULE_ROOT, target / "CONDUCTOR_modules"))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the CONDUCTOR package into an existing Project root.")
    parser.add_argument("--target", required=True, help="Existing Project directory to receive the package.")
    parser.add_argument("--apply", action="store_true", help="Perform the copy; without this flag only show the plan.")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Target Project directory does not exist: {target}")
    if target == SOURCE_ROOT.resolve():
        raise ValueError("Target is the package source Project; no installation is needed")

    pairs = copy_targets(target)
    missing = [source for source, _destination in pairs if not source.exists()]
    conflicts = [destination for _source, destination in pairs if destination.exists()]
    if missing:
        raise FileNotFoundError("Package source is incomplete:\n" + "\n".join(str(path) for path in missing))
    if conflicts:
        raise FileExistsError(
            "Installation would overwrite existing CONDUCTOR paths. Resolve them manually first:\n"
            + "\n".join(str(path) for path in conflicts)
        )

    for source, destination in pairs:
        print(f"{source.relative_to(SOURCE_ROOT)} -> {destination}")
    if not args.apply:
        print("Dry run only; rerun with --apply to copy these paths")
        return 0

    for source, destination in pairs:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, ignore=ignored)
        else:
            shutil.copy2(source, destination)

    verifier = target / "CONDUCTOR_modules" / "tools" / "verify_package_layout.py"
    completed = subprocess.run([sys.executable, str(verifier)], cwd=target, check=False)
    if completed.returncode:
        raise RuntimeError("Files were copied, but package layout verification failed")
    print(f"Installed CONDUCTOR into {target}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
