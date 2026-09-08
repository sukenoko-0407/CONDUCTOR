from __future__ import annotations

import argparse
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pandas as pd


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.template_id = ""
        self.template_version = ""
        self._payload = False
        self.payload_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(str(values[key]))
        if values.get("data-template-id"):
            self.template_id = str(values["data-template-id"])
            self.template_version = str(values.get("data-template-version", ""))
        self._payload = tag == "script" and values.get("id") == "mmpPayload"

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._payload = False

    def handle_data(self, data: str) -> None:
        if self._payload:
            self.payload_text.append(data)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _local_links(document: Path, parser: _DocumentParser, root: Path) -> list[str]:
    failures: list[str] = []
    for link in parser.links:
        if link.startswith(("data:", "http:", "https:", "#", "javascript:")):
            continue
        clean = link.split("#", 1)[0].split("?", 1)[0]
        target = (document.parent / clean).resolve()
        if not _inside(root, target):
            failures.append(f"link escapes report root: {document.name} -> {link}")
        elif not target.is_file():
            failures.append(f"missing link: {document.name} -> {link}")
    return failures


def audit_output(output: Path) -> dict[str, Any]:
    output = output.resolve()
    failures: list[str] = []
    checks: list[str] = []
    audited_external_images: set[Path] = set()
    required = [
        output / "mmp_report_index.json",
        output / "mmp_target_registry.csv",
        output / "mmp_target_selection_sources.csv",
        output / "mmp_target_summary.csv",
        output / "transformation_summary.csv",
        output / "context_summary.csv",
        output / "two_cut_quality_summary.csv",
        output / "environment_summary.csv",
        output / "mmp_database_manifest.json",
        output / "mmp_report.html",
    ]
    for path in required:
        if not path.is_file():
            failures.append(f"missing required artifact: {path.name}")
    if failures:
        return {"status": "failed", "checks": checks, "failures": failures}

    index = json.loads(required[0].read_text(encoding="utf-8"))
    manifest = json.loads((output / "mmp_database_manifest.json").read_text(encoding="utf-8"))
    template_hashes = manifest.get("template_hashes", {})
    if not isinstance(template_hashes, dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(value))
        for value in template_hashes.values()
    ) or len(template_hashes) < 3:
        failures.append("manifest template hashes are missing or invalid")
    registry = pd.read_csv(required[1], dtype=str)
    sources = pd.read_csv(required[2], dtype=str)
    summary = pd.read_csv(required[3])
    if str(index.get("schema_version")) != "2.0.0":
        failures.append("mmp_report_index schema_version is not 2.0.0")
    if registry["target_compound_id"].nunique() != len(summary):
        failures.append("registry target count does not match summary rows")
    if set(registry["target_compound_id"]) != set(summary["target_compound_id"]):
        failures.append("registry and summary target identities differ")
    source_counts = sources.groupby("target_compound_id").size()
    index_counts = pd.Series(
        [str(row.get("target_compound_id", "")) for row in index.get("unit_reports", [])]
    ).value_counts()
    for target_id, count in source_counts.items():
        if int(index_counts.get(target_id, 0)) != int(count):
            failures.append(f"selection source count mismatch for {target_id}")
    checks.append("registry/index/source counts")

    for row in summary.to_dict(orient="records"):
        target_id = str(row["target_compound_id"])
        html_path = output / str(row["interactive_report_path"])
        svg_path = output / str(row["static_map_path"])
        evidence_path = output / str(row["evidence_csv_path"])
        for path in (html_path, svg_path, evidence_path):
            if not _inside(output, path) or not path.is_file():
                failures.append(f"invalid target artifact for {target_id}: {path}")
        if not all(path.is_file() for path in (html_path, svg_path, evidence_path)):
            continue
        if html_path.stat().st_size > 10 * 1024 * 1024:
            failures.append(
                f"Target HTML exceeds the 10 MiB contract for {target_id}: "
                f"{html_path.stat().st_size} bytes"
            )
        evidence = pd.read_csv(evidence_path)
        if "target_oriented_delta" not in evidence.columns:
            failures.append(f"Target-oriented signed delta is missing for {target_id}")
        pair_identity = "compound_pair_id" if "compound_pair_id" in evidence else "pair_id"
        report_eligible = evidence.loc[
            ~(
                evidence["cut_count"].eq(2)
                & evidence["two_cut_quality_class"].eq("2C-X")
            )
        ]
        expected_direct = int(
            report_eligible.loc[
                report_eligible["connection_scope"].eq("direct"), pair_identity
            ].nunique()
        )
        if int(row["direct_pair_count"]) != expected_direct:
            failures.append(f"direct pair count mismatch for {target_id}")
        canonical_direct = int(
            evidence.loc[evidence["connection_scope"].eq("direct"), pair_identity].nunique()
        )
        if int(row.get("canonical_direct_pair_count", canonical_direct)) != canonical_direct:
            failures.append(f"canonical direct pair count mismatch for {target_id}")
        delta = pd.to_numeric(report_eligible["target_oriented_delta"], errors="coerce")
        summary_rules = {
            "target_explanation_count": ("direct", delta.ge(0.10), pair_identity),
            "observed_improvement_count": ("direct", delta.le(-0.10), pair_identity),
            "transferred_explanation_count": ("transferred", delta.ge(0.10), "evidence_id"),
            "proposed_improvement_count": ("transferred", delta.le(-0.10), "evidence_id"),
        }
        for column, (scope, direction_mask, identity) in summary_rules.items():
            rows = report_eligible.loc[
                report_eligible["connection_scope"].eq(scope) & direction_mask
            ]
            expected = int(rows[identity].nunique())
            if int(row[column]) != expected:
                failures.append(f"{column} mismatch for {target_id}")

        parser = _DocumentParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        if parser.template_id != "A008-target-workspace" or parser.template_version != "0.1.11":
            failures.append(f"template marker mismatch for {target_id}")
        failures.extend(_local_links(html_path, parser, output))
        try:
            payload = json.loads("".join(parser.payload_text))
        except json.JSONDecodeError as error:
            failures.append(f"invalid HTML payload for {target_id}: {error}")
            payload = {"evidence": [], "assets": {}}
        payload_rows = payload.get("evidence", [])
        if int(row.get("canonical_evidence_row_count", len(evidence))) != len(evidence):
            failures.append(f"canonical evidence row count mismatch for {target_id}")
        if int(row.get("embedded_evidence_row_count", len(payload_rows))) != len(payload_rows):
            failures.append(f"embedded evidence row count mismatch for {target_id}")
        if (
            not bool(row.get("payload_truncated"))
            and len(payload_rows) != int(row.get("report_evidence_row_count", len(payload_rows)))
        ):
            failures.append(f"untruncated payload count mismatch for {target_id}")
        asset_ids = set(payload.get("assets", {}))
        for record in payload_rows:
            for column in (
                "target_image", "neighbor_image", "core_image", "before_image", "after_image",
                "target_core_image", "evidence_core_image",
                "counterpart_fragment_image", "target_fragment_image",
                "observed_from_fragment_image", "observed_to_fragment_image",
                "observed_counterpart_image", "observed_target_like_image",
                "observed_counterpart_fragment_image", "observed_target_like_fragment_image",
            ):
                value = str(record.get(column, ""))
                if value.startswith("@") and value[1:] not in asset_ids:
                    failures.append(f"missing payload image asset {value} for {target_id}")
                elif value and not value.startswith(("@", "data:")):
                    dynamic_path = (html_path.parent / value).resolve()
                    if not _inside(output, dynamic_path) or not dynamic_path.is_file():
                        failures.append(
                            f"missing external payload image {value} for {target_id}"
                        )
                    elif dynamic_path not in audited_external_images:
                        audited_external_images.add(dynamic_path)
                        try:
                            root = ET.parse(dynamic_path).getroot()
                            if not str(root.tag).endswith("svg"):
                                failures.append(
                                    f"external payload image is not SVG XML: {value}"
                                )
                        except (ET.ParseError, OSError) as error:
                            failures.append(
                                f"invalid external SVG payload image {value}: {error}"
                            )

        svg = svg_path.read_text(encoding="utf-8")
        core_count = len(re.findall(r'data-kind="core"', svg))
        neighbor_count = len(re.findall(r'data-kind="neighbor"', svg))
        group_count = len(re.findall(r'data-kind="neighbor-group"', svg))
        if core_count > 5 or neighbor_count > 25:
            failures.append(f"static map exceeds 5-core/5-neighbor-per-core portal bound for {target_id}")
        core_direct_total = sum(int(value) for value in re.findall(
            r'data-kind="core"[^>]*data-direct-count="(\d+)"', svg
        ))
        represented_neighbor_total = sum(int(value) for value in re.findall(
            r'data-kind="neighbor(?:-group)?"[^>]*data-neighbor-count="(\d+)"', svg
        ))
        if core_direct_total != represented_neighbor_total:
            failures.append(
                f"static map Neighbor accounting mismatch for {target_id}: "
                f"Core={core_direct_total}, represented={represented_neighbor_total}"
            )
        if group_count and "クリックして全件表示" not in svg:
            failures.append(f"aggregated Neighbor portal lacks a count label for {target_id}")
        if "#e07a24" not in svg or "#21834a" not in svg or "#173f67" not in svg:
            failures.append(f"static map role colors are incomplete for {target_id}")
        for token in (
            'xmlns="http://www.w3.org/2000/svg"', "<style>",
            ".target-box{stroke:#173f67}", ".core-box{stroke:#21834a}",
            ".neighbor-box{stroke:#e07a24}",
        ):
            if token not in svg:
                failures.append(
                    f"static map is not self-contained for {target_id}: missing {token}"
                )
        checks.append(f"target {target_id}: links/counts/payload/static-map")

    checks.append("external SVG files are decodable XML")

    overview_parser = _DocumentParser()
    overview_parser.feed((output / "mmp_report.html").read_text(encoding="utf-8"))
    failures.extend(_local_links(output / "mmp_report.html", overview_parser, output))
    checks.append("overview links")
    return {
        "status": "passed" if not failures else "failed",
        "checks": checks,
        "failures": failures,
        "target_count": int(len(summary)),
    }


def audit_database_output(output: Path, database_path: Path) -> dict[str, Any]:
    output = output.resolve()
    database_path = database_path.resolve()
    failures: list[str] = []
    checks: list[str] = []
    details_path = output / "mmp_pair_detail.csv"
    fragments_path = output / "mmp_fragmentations.csv"
    manifest_path = output / "mmp_database_manifest.json"
    report_path = output / "mmp_database_report.html"
    summary_paths = [
        output / "transformation_summary.csv",
        output / "context_summary.csv",
        output / "two_cut_quality_summary.csv",
        output / "environment_summary.csv",
    ]
    for path in (database_path, details_path, fragments_path, manifest_path, report_path, *summary_paths):
        if not path.is_file():
            failures.append(f"missing database artifact: {path.name}")
    if failures:
        return {"status": "failed", "checks": checks, "failures": failures}
    details = pd.read_csv(details_path)
    fragments = pd.read_csv(fragments_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template_hashes = manifest.get("template_hashes", {})
    if not isinstance(template_hashes, dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(value))
        for value in template_hashes.values()
    ) or len(template_hashes) < 3:
        failures.append("database manifest template hashes are missing or invalid")
    required_detail_columns = {
        "compound_pair_id", "pair_id", "pair_transformation_id", "cut_count",
        "transformation_family_id", "transformation_id", "core_id",
        "normalized_signed_delta", "effect_status",
    }
    missing_detail_columns = sorted(required_detail_columns - set(details.columns))
    if missing_detail_columns:
        failures.append(f"canonical detail is missing columns: {missing_detail_columns}")
    with closing(sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )}
        metadata = {
            key: json.loads(value) for key, value in connection.execute(
                "SELECT key,value_json FROM metadata"
            )
        }
        database_counts = {
            "all": connection.execute("SELECT count(*) FROM pair_transformations").fetchone()[0],
            "one_cut": connection.execute("SELECT count(*) FROM pair_transformations_1cut").fetchone()[0],
            "two_cut": connection.execute("SELECT count(*) FROM pair_transformations_2cut").fetchone()[0],
            "fragmentations": connection.execute("SELECT count(*) FROM fragmentations").fetchone()[0],
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    expected_counts = {
        "all": len(details),
        "one_cut": int(details["cut_count"].eq(1).sum()),
        "two_cut": int(details["cut_count"].eq(2).sum()),
        "fragmentations": len(fragments),
    }
    if database_counts != expected_counts:
        failures.append(f"database/CSV count mismatch: {database_counts} != {expected_counts}")
    if "targets" in names or metadata.get("target_independent") is not True:
        failures.append("canonical database contains Target state or lacks target_independent=true")
    if metadata.get("schema_version") != "2.0.0" or metadata.get("build_complete") is not True:
        failures.append("canonical database completion/version metadata is invalid")
    if integrity != "ok":
        failures.append(f"SQLite integrity check failed: {integrity}")
    if not missing_detail_columns and len(details):
        pair_scope = details.groupby("pair_id", dropna=False).agg(
            compound_pair_count=("compound_pair_id", "nunique"),
            cut_count_count=("cut_count", "nunique"),
        )
        if pair_scope["compound_pair_count"].gt(1).any() or pair_scope["cut_count_count"].gt(1).any():
            failures.append("pair_id is not scoped to exactly one compound_pair_id and cut_count")
        identity_columns = ["pair_id", "transformation_id", "core_id"]
        expected_identity_count = details[identity_columns].drop_duplicates().shape[0]
        actual_identity_count = details["pair_transformation_id"].nunique()
        if expected_identity_count != actual_identity_count:
            failures.append("pair_transformation_id does not match pair/transformation/core identity")
    checks.append("SQLite integrity, Target independence, 1/2-cut counts")
    transformation_summary = pd.read_csv(summary_paths[0])
    context_summary = pd.read_csv(summary_paths[1])
    quality_summary = pd.read_csv(summary_paths[2])
    expected_transformations = details[
        ["cut_count", "transformation_id"]
    ].drop_duplicates().shape[0]
    if len(transformation_summary) != expected_transformations:
        failures.append("transformation summary count does not match canonical detail")
    if len(context_summary) != details[["cut_count", "core_id"]].drop_duplicates().shape[0]:
        failures.append("context summary count does not match canonical detail")
    if int(quality_summary["pair_transformation_rows"].sum()) != int(details["cut_count"].eq(2).sum()):
        failures.append("2-cut quality summary does not cover every 2-cut detail row")
    checks.append("aggregate artifact counts")
    parser = _DocumentParser()
    parser.feed(report_path.read_text(encoding="utf-8"))
    if parser.template_id != "A008-database-summary" or parser.template_version != "0.1.11":
        failures.append("database report template marker mismatch")
    failures.extend(_local_links(report_path, parser, output))
    checks.append("database report links")
    return {
        "status": "passed" if not failures else "failed",
        "checks": checks,
        "failures": failures,
        "row_counts": database_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = audit_output(args.output)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
