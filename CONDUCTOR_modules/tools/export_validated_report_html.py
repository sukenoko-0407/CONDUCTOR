"""Export HTML from an accepted P06 manifest without changing the Run root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PACKAGE = PROJECT_ROOT / ".claude" / "skills" / "cs-report" / "python"
if str(REPORT_PACKAGE) not in sys.path:
    sys.path.insert(0, str(REPORT_PACKAGE))

from conductor_report import render_html_report  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(manifest: dict[str, Any], role: str) -> dict[str, Any]:
    matches = [item for item in manifest.get("artifacts", []) if item.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"P06 manifest must contain exactly one {role!r} artifact")
    return matches[0]


def _verified_path(base: Path, artifact: dict[str, Any]) -> Path:
    path = (base / str(artifact["path"])).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes P06 output directory: {path}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Artifact does not exist: {path}")
    actual = _sha256(path)
    if actual != artifact.get("sha256"):
        raise ValueError(
            f"Artifact hash mismatch for {path.name}: expected {artifact.get('sha256')}, "
            f"actual {actual}"
        )
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a self-contained HTML report from an accepted P06 manifest"
    )
    parser.add_argument("--artifact-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.artifact_manifest).resolve()
    output_path = Path(args.output).resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "succeeded":
        raise ValueError("Only a succeeded P06 artifact manifest can be exported")
    producer = manifest.get("producer") or {}
    if producer.get("skill_name") != "cs-report":
        raise ValueError("Artifact manifest was not produced by cs-report")

    base = manifest_path.parent.resolve()
    report_path = _verified_path(base, _artifact(manifest, "report_json"))
    findings_path = _verified_path(base, _artifact(manifest, "final_findings"))
    validation_path = _verified_path(base, _artifact(manifest, "citation_validation"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    findings = _read_jsonl(findings_path)
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if report.get("status") != "succeeded" or validation.get("status") != "succeeded":
        raise ValueError("Report and citation validation must both be succeeded")

    rendered = render_html_report(
        report,
        findings,
        validation,
        run_id=str(producer.get("run_id", report.get("run_id", ""))),
        created_at=str(manifest.get("created_at", report.get("created_at", ""))),
    )
    _atomic_write(output_path, rendered)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "output": str(output_path),
                "sha256": _sha256(output_path),
                "source_manifest": str(manifest_path),
                "run_root_modified": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
