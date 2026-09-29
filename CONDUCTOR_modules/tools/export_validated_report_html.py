"""Export HTML from an accepted P06 manifest without changing the Run root."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PACKAGE = PROJECT_ROOT / ".claude" / "skills" / "cs-report" / "python"
if str(REPORT_PACKAGE) not in sys.path:
    sys.path.insert(0, str(REPORT_PACKAGE))

from conductor_report import render_finding_html, render_html_report  # noqa: E402
from conductor_stat_core import stable_id  # noqa: E402


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


def _verified_input_path(base: Path, artifact: dict[str, Any]) -> Path:
    candidate = Path(str(artifact["path"]))
    path = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input artifact does not exist: {path}")
    actual = _sha256(path)
    if actual != artifact.get("sha256"):
        raise ValueError(
            f"Input artifact hash mismatch for {path.name}: expected "
            f"{artifact.get('sha256')}, actual {actual}"
        )
    return path


def _evidence_rows(manifest: dict[str, Any], base: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for artifact in manifest.get("input_artifacts", []):
        if artifact.get("role") != "evidence_table":
            continue
        path = _verified_input_path(base, artifact)
        if path.suffix.lower() != ".csv":
            raise ValueError(f"Unsupported evidence table format for HTML export: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row_id = row.get("row_id")
                if row_id:
                    rows[f"{path.name}#row_id={row_id}"] = row
    return rows


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _source_artifact_path(manifest_path: Path, artifact: dict[str, Any]) -> Path:
    path = (manifest_path.parent / str(artifact["path"])).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source artifact does not exist: {path}")
    actual = _sha256(path)
    if actual != artifact.get("sha256"):
        raise ValueError(
            f"Source artifact hash mismatch for {path.name}: expected "
            f"{artifact.get('sha256')}, actual {actual}"
        )
    return path


def _visual_inputs(
    manifest: dict[str, Any], base: Path
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], dict[str, str]]:
    observation_paths: dict[Path, Path] = {}
    compound_paths: list[Path] = []
    database_paths: list[Path] = []
    for artifact in manifest.get("input_artifacts", []):
        role = artifact.get("role")
        if role == "score_observations":
            path = _verified_input_path(base, artifact)
            observation_paths[path] = path
        elif role == "compounds":
            compound_paths.append(_verified_input_path(base, artifact))
        elif role == "mmp_database":
            database_paths.append(_verified_input_path(base, artifact))
        elif role == "artifact_manifest":
            source_manifest_path = _verified_input_path(base, artifact)
            source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            if source_manifest.get("status") != "succeeded":
                raise ValueError(f"Source manifest is not succeeded: {source_manifest_path}")
            for source_artifact in source_manifest.get("artifacts", []):
                if source_artifact.get("role") == "score_observations":
                    path = _source_artifact_path(source_manifest_path, source_artifact)
                    observation_paths[path] = path
    observations: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(observation_paths):
        for row in _csv_rows(path):
            finding_key = row.get("finding_key")
            if finding_key:
                observations.setdefault(str(finding_key), []).append(row)
    compound_smiles: dict[str, str] = {}
    for path in compound_paths:
        for row in _csv_rows(path):
            compound_id = row.get("compound_id")
            canonical_smiles = row.get("canonical_smiles")
            if compound_id and canonical_smiles:
                compound_smiles[str(compound_id)] = str(canonical_smiles)
    if len(database_paths) > 1:
        raise ValueError("P06 manifest contains more than one mmp_database input")
    fragment_smiles: dict[str, str] = {}
    if database_paths:
        database_uri = database_paths[0].as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            rows = connection.execute(
                'SELECT DISTINCT "class",variable_smiles FROM fragmentations '
                "WHERE status='accepted' ORDER BY \"class\",variable_smiles"
            )
            for transform_class, variable_smiles in rows:
                fragment_id = stable_id(
                    "FRAG",
                    {
                        "schema_version": "0.2.1",
                        "class": str(transform_class),
                        "variable_smiles": str(variable_smiles),
                    },
                )
                previous = fragment_smiles.setdefault(fragment_id, str(variable_smiles))
                if previous != str(variable_smiles):
                    raise ValueError(f"Conflicting fragment structure for {fragment_id}")
    return observations, compound_smiles, fragment_smiles


def _finding_sort_key(finding: dict[str, Any]) -> tuple[Any, ...]:
    scores = finding.get("scores") or {}
    return (
        int(scores.get("rank")) if scores.get("rank") is not None else 2**31 - 1,
        -float(scores.get("composite") or 0.0),
        str(finding.get("finding_id", "")),
    )


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
    parser.add_argument(
        "--finding-id",
        help="Render one requested Finding instead of the overview and standard top pages",
    )
    parser.add_argument(
        "--finding-page-k",
        type=int,
        help="Override the number of ranked individual pages (default: report value or 20)",
    )
    parser.add_argument(
        "--overview-detail-k",
        type=int,
        help="Override fully explained overview entries (default: report value or 10)",
    )
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

    finding_page_k = max(
        0,
        int(
            args.finding_page_k
            if args.finding_page_k is not None
            else report.get("finding_page_k", 20)
        ),
    )
    overview_detail_k = max(
        0,
        min(
            finding_page_k,
            int(
                args.overview_detail_k
                if args.overview_detail_k is not None
                else report.get("overview_detail_k", 10)
            ),
        ),
    )
    report["finding_page_k"] = finding_page_k
    report["overview_detail_k"] = overview_detail_k
    report["report_layout_version"] = "ranked_pages_v1"

    evidence_by_ref = _evidence_rows(manifest, base)
    observations_by_finding, compound_smiles, fragment_smiles = _visual_inputs(
        manifest, base
    )
    run_id = str(producer.get("run_id", report.get("run_id", "")))
    created_at = str(manifest.get("created_at", report.get("created_at", "")))
    endpoint_id = str(report.get("endpoint_id", ""))
    generated: list[Path] = []
    if args.finding_id:
        matches = [item for item in findings if item.get("finding_id") == args.finding_id]
        if len(matches) != 1:
            raise ValueError(f"Finding ID must identify exactly one Finding: {args.finding_id}")
        rendered = render_finding_html(
            matches[0],
            validation,
            run_id=run_id,
            endpoint_id=endpoint_id,
            created_at=created_at,
            evidence_by_ref=evidence_by_ref,
            observations_by_finding=observations_by_finding,
            compound_smiles=compound_smiles,
            fragment_smiles=fragment_smiles,
        )
        _atomic_write(output_path, rendered)
        generated.append(output_path)
    else:
        reportable = sorted(
            [
                item
                for item in findings
                if (item.get("state") or {}).get("pipeline") == "reportable"
            ],
            key=_finding_sort_key,
        )
        important = reportable[:finding_page_k]
        detail_directory = output_path.parent / f"{output_path.stem}_findings"
        if important and detail_directory.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing Finding report directory: {detail_directory}"
            )
        detail_paths: dict[str, str] = {}
        for finding in important:
            finding_id = str(finding.get("finding_id", ""))
            if not finding_id or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for character in finding_id
            ):
                raise ValueError(f"Unsafe finding_id for HTML path: {finding_id!r}")
            detail_path = detail_directory / f"{finding_id}.html"
            detail_paths[finding_id] = f"{detail_directory.name}/{finding_id}.html"
            _atomic_write(
                detail_path,
                render_finding_html(
                    finding,
                    validation,
                    run_id=run_id,
                    endpoint_id=endpoint_id,
                    created_at=created_at,
                    evidence_by_ref=evidence_by_ref,
                    observations_by_finding=observations_by_finding,
                    compound_smiles=compound_smiles,
                    fragment_smiles=fragment_smiles,
                    overview_href=f"../{output_path.name}",
                ),
            )
            generated.append(detail_path)
        rendered = render_html_report(
            report,
            findings,
            validation,
            run_id=run_id,
            created_at=created_at,
            evidence_by_ref=evidence_by_ref,
            observations_by_finding=observations_by_finding,
            compound_smiles=compound_smiles,
            fragment_smiles=fragment_smiles,
            finding_report_paths=detail_paths,
        )
        _atomic_write(output_path, rendered)
        generated.insert(0, output_path)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "output": str(output_path),
                "sha256": _sha256(output_path),
                "generated_files": [str(path) for path in generated],
                "finding_report_count": max(0, len(generated) - (0 if args.finding_id else 1)),
                "overview_detail_count": 0 if args.finding_id else min(
                    overview_detail_k, max(0, len(generated) - 1)
                ),
                "report_layout_version": "ranked_pages_v1",
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
