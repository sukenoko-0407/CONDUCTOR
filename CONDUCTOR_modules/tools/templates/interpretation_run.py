from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def _local_schema_registry() -> tuple[dict[str, dict[str, Any]], Any]:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Any]] = []
    registered_ids: set[str] = set()
    for path in sorted((SKILL_DIR / "schemas").glob("*.schema.json")):
        schema = read_json(path)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Bundled Schema has no $id: {path.name}")
        if schema_id in registered_ids:
            raise ValueError(f"Duplicate bundled Schema $id: {schema_id}")
        registered_ids.add(schema_id)
        schemas[path.name] = schema
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        resources.extend(((schema_id, resource), (path.resolve().as_uri(), resource)))
    return schemas, Registry().with_resources(resources)


def validate_schema(instance: dict[str, Any], schema_name: str) -> None:
    import jsonschema

    schemas, registry = _local_schema_registry()
    if schema_name not in schemas:
        raise FileNotFoundError(f"Bundled Schema is not registered: {schema_name}")
    schema = schemas[schema_name]
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(
        schema,
        registry=registry,
        format_checker=jsonschema.FormatChecker(),
    ).validate(instance)


def validate_context_schemas(context: dict[str, Any]) -> list[str]:
    import jsonschema

    issues: list[str] = []
    for index, card in enumerate(context.get("result_cards") or [], 1):
        try:
            validate_schema(card, "result_card.schema.json")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            issues.append(f"result_cards[{index}] schema error at {location}: {exc.message}")
    for index, bundle in enumerate(context.get("review_bundles") or [], 1):
        try:
            validate_schema(bundle, "review_bundle.schema.json")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            issues.append(f"review_bundles[{index}] schema error at {location}: {exc.message}")
        applicable = set(bundle.get("applicable_axes") or [])
        anchored = set((bundle.get("evaluation_anchors") or {}).keys())
        if anchored != applicable:
            issues.append(
                f"review_bundles[{index}] evaluation_anchors must match applicable_axes exactly"
            )
    for index, profile in enumerate(context.get("interpretation_profiles") or [], 1):
        try:
            validate_schema(profile, "operator_interpretation_profile.schema.json")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            issues.append(f"interpretation_profiles[{index}] schema error at {location}: {exc.message}")
        if set((profile.get("anchors") or {}).keys()) != set(profile.get("allowed_axes") or []):
            issues.append(
                f"interpretation_profiles[{index}] anchors must match allowed_axes exactly"
            )
    review_manifest = context.get("review_manifest")
    if review_manifest is not None:
        try:
            validate_schema(review_manifest, "interpretation_review_manifest.schema.json")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            issues.append(f"review_manifest schema error at {location}: {exc.message}")
    if context.get("mode") == "screening":
        try:
            validate_schema(context, "screening_batch.schema.json")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
            issues.append(f"screening context schema error at {location}: {exc.message}")
    return issues


def validate_screening_draft(context: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    try:
        validate_schema(draft, "screening_draft.schema.json")
    except Exception as exc:
        return [f"screening draft schema error: {exc}"]
    if draft.get("batch_id") != context.get("batch_id"):
        issues.append("batch_id does not match the Runtime context")
    targets = list(context.get("target_bundle_ids") or [])
    rows = list(draft.get("assessments") or [])
    bundle_ids = [row.get("bundle_id") for row in rows]
    if len(bundle_ids) != len(set(bundle_ids)) or set(bundle_ids) != set(targets):
        issues.append("every target Review Bundle must be assessed exactly once")
    allowed = set(context.get("allowed_result_refs") or [])
    bundles = {bundle.get("bundle_id"): bundle for bundle in context.get("review_bundles") or []}
    for index, row in enumerate(rows, 1):
        status = row.get("assessment_status")
        scores = row.get("scores")
        related = set([*(row.get("supporting_result_refs") or []), *(row.get("counter_result_refs") or [])])
        if related - allowed:
            issues.append(f"assessments[{index}]: Result reference outside context")
        bundle_refs = set((bundles.get(row.get("bundle_id")) or {}).get("all_result_refs") or [])
        if related - bundle_refs:
            issues.append(f"assessments[{index}]: Result reference outside its Review Bundle")
        if status == "evaluated" and not isinstance(scores, dict):
            issues.append(f"assessments[{index}]: evaluated requires absolute axis scores")
        elif status == "evaluated":
            applicable = set((bundles.get(row.get("bundle_id")) or {}).get("applicable_axes") or [])
            for axis, value in scores.items():
                if axis in applicable and not isinstance(value, int):
                    issues.append(f"assessments[{index}]: applicable axis {axis} must be scored 0-3")
                if axis not in applicable and value != "not_applicable":
                    issues.append(f"assessments[{index}]: non-applicable axis {axis} must be not_applicable")
        if status == "not_scorable" and any(value is not None for value in (scores, row.get("effect_stability"), row.get("independence"))):
            issues.append(f"assessments[{index}]: not_scorable requires null scores and reliability judgments")
    return issues


def validate_draft(context: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    allowed = set(context.get("allowed_result_refs") or [])
    if not str(draft.get("title") or "").strip():
        issues.append("title is required")
    if not str(draft.get("executive_summary") or "").strip():
        issues.append("executive_summary is required")
    if not str(draft.get("coverage_summary") or "").strip():
        issues.append("coverage_summary is required")
    for index, item in enumerate(draft.get("insights") or [], 1):
        prefix = f"insights[{index}]"
        if "scope" in item or "analysis_subject" in item or "insight_id" in item:
            issues.append(f"{prefix}: scope, analysis_subject, and formal insight_id are Runtime-owned")
        bundle_ids = list(item.get("review_bundle_ids") or [])
        if not bundle_ids:
            issues.append(f"{prefix}: review_bundle_ids is required")
        allowed_bundles = set((context.get("review_manifest") or {}).get("selected_bundle_ids") or [])
        if set(bundle_ids) - allowed_bundles:
            issues.append(f"{prefix}: Review Bundle outside Runtime shortlist")
        supporting = list(item.get("supporting_results") or [])
        comparisons = list(item.get("comparison_results") or [])
        counter = list(item.get("counter_results") or [])
        refs = set([*supporting, *comparisons, *counter])
        if not supporting:
            issues.append(f"{prefix}: supporting_results is required")
        if refs - allowed:
            issues.append(f"{prefix}: Result refs outside context: {sorted(refs-allowed)}")
        if item.get("claim_kind") in {"difference", "agreement", "contradiction"} and not comparisons:
            issues.append(f"{prefix}: comparison claim requires comparison_results")
        limitations = item.get("limitations")
        if not isinstance(limitations, list):
            issues.append(f"{prefix}: limitations must be a JSON array of complete statements, even when there is only one limitation")
        elif not limitations or any(not isinstance(value, str) or not value.strip() for value in limitations):
            issues.append(f"{prefix}: limitations requires one or more non-empty strings")
        elif len(limitations) >= 2 and all(len(value.strip()) == 1 for value in limitations):
            issues.append(f"{prefix}: limitations contains character fragments instead of complete statements")
        for key in ("title", "observation", "interpretation"):
            if not str(item.get(key) or "").strip():
                issues.append(f"{prefix}: {key} is required")
    selected_bundle_ids = set((context.get("review_manifest") or {}).get("selected_bundle_ids") or [])
    dispositions = list(draft.get("bundle_dispositions") or [])
    disposition_ids = [str(item.get("bundle_id") or "") for item in dispositions]
    if len(disposition_ids) != len(set(disposition_ids)) or set(disposition_ids) != selected_bundle_ids:
        issues.append("bundle_dispositions must cover every selected Review Bundle exactly once")
    used_bundle_ids = {
        str(bundle_id)
        for item in draft.get("insights") or []
        for bundle_id in item.get("review_bundle_ids") or []
    }
    used_dispositions = {"reported_as_insight", "merged_into_insight"}
    omitted_dispositions = {"rejected_by_counterevidence", "redundant_evidence", "deferred_by_detail_limit", "not_reportable"}
    for index, item in enumerate(dispositions, 1):
        bundle_id = str(item.get("bundle_id") or "")
        disposition = str(item.get("disposition") or "")
        if disposition not in used_dispositions | omitted_dispositions:
            issues.append(f"bundle_dispositions[{index}]: invalid disposition")
        if not str(item.get("reason") or "").strip():
            issues.append(f"bundle_dispositions[{index}]: reason is required")
        if bundle_id in used_bundle_ids and disposition not in used_dispositions:
            issues.append(f"bundle_dispositions[{index}]: an Insight-used Bundle requires a reported/merged disposition")
        if bundle_id not in used_bundle_ids and disposition not in omitted_dispositions:
            issues.append(f"bundle_dispositions[{index}]: an omitted Bundle requires an omission disposition")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a CONDUCTOR 0.1.8 Review Bundle assessment or ID-free Interpretation draft.")
    parser.add_argument("--context", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    context = read_json(Path(args.context))
    draft = read_json(Path(args.draft))
    screening = context.get("mode") == "screening"
    issues = [*validate_context_schemas(context), *(validate_screening_draft(context, draft) if screening else validate_draft(context, draft))]
    output = Path(args.output_dir)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    write_json(output / "validation.json", {"schema_version": "1.0.0", "status": "fail" if issues else "pass", "issues": issues})
    if issues:
        print(json.dumps({"status": "fail", "issues": issues}, ensure_ascii=False, indent=2))
        return 1
    shutil.copy2(args.draft, output / "validated_draft.json")
    if screening:
        rows = draft.get("assessments") or []
        lines = ["# Result Screening draft preview", "", f"- Batch: `{draft['batch_id']}`", f"- Assessments: {len(rows)}", ""]
        lines.extend(f"- `{row['bundle_id']}`: {row['assessment_status']} — {row['reason']}" for row in rows)
        (output / "preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        cards = "".join(f"<article><h2>{html.escape(row['bundle_id'])}</h2><p>{html.escape(row['assessment_status'])}: {html.escape(row['reason'])}</p></article>" for row in rows)
        (output / "preview.html").write_text(f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>body{{max-width:960px;margin:auto;font-family:system-ui;background:#f2f1ed;color:#29363a}}article{{background:#fff;padding:16px;margin:12px 0;border-left:5px solid #60777c}}</style></head><body><h1>Result Screening</h1>{cards}</body></html>", encoding="utf-8")
        print(json.dumps({"status": "pass", "mode": "screening", "output_dir": str(output)}, ensure_ascii=False, indent=2))
        return 0
    lines = ["# Interpretation draft preview", "", draft["executive_summary"], ""]
    cards = []
    for index, item in enumerate(draft.get("insights") or [], 1):
        refs = ", ".join(item.get("supporting_results") or [])
        lines += [f"## Draft {index}: {item['title']}", "", f"- Claim: {item.get('claim_kind', 'single_scope_observation')}", f"- Supporting Results: {refs}", "", item["observation"], "", item["interpretation"], ""]
        cards.append(f"<article><h2>Draft {index}: {html.escape(item['title'])}</h2><p>{html.escape(item['observation'])}</p><p>{html.escape(item['interpretation'])}</p><small>{html.escape(refs)}</small></article>")
    (output / "preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "preview.html").write_text(f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>body{{max-width:960px;margin:auto;font-family:system-ui;background:#f2f1ed;color:#29363a}}article{{background:#fff;padding:20px;margin:18px 0;border-left:6px solid #60777c}}</style></head><body><h1>{html.escape(draft['title'])}</h1><p>{html.escape(draft['executive_summary'])}</p>{''.join(cards)}</body></html>", encoding="utf-8")
    print(json.dumps({"status": "pass", "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
