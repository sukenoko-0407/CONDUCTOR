"""Entity graph and fail-closed citation checks."""

from __future__ import annotations

import math
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from conductor_stat_core import ENTITY_KEYS, file_sha256, stable_id


NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")
MARKER = re.compile(r"\[\[([^\]]+)\]\]")


class CitationError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceRegistry:
    root: Path
    tables: dict[str, pd.DataFrame]
    paths: dict[str, Path]
    expected_hashes: dict[str, str]

    @classmethod
    def load(cls, root: Path, table_paths: Iterable[Path], expected_hashes: dict[str, str]) -> "EvidenceRegistry":
        resolved_root=root.resolve();tables={};paths={}
        for source in table_paths:
            path=source.resolve()
            try:path.relative_to(resolved_root)
            except ValueError as exc:raise CitationError(f"Evidence path escapes Run root: {path}") from exc
            name=path.name
            if name in tables:raise CitationError(f"Duplicate evidence table basename: {name}")
            expected=expected_hashes.get(name)
            if expected is None:raise CitationError(f"Evidence table is absent from supplied manifests: {name}")
            actual=file_sha256(path)
            if actual!=expected:raise CitationError(f"Evidence hash mismatch for {name}: expected {expected}, actual {actual}")
            frame=pd.read_csv(path,dtype={"row_id":"string","test_id":"string","compound_id":"string","pair_id":"string"})
            if "row_id" not in frame or frame["row_id"].astype(str).duplicated().any():raise CitationError(f"Evidence table requires unique row_id: {name}")
            tables[name]=frame;paths[name]=path
        return cls(resolved_root,tables,paths,expected_hashes)

    def row(self, table_ref: str) -> dict[str, Any]:
        if "#row_id=" not in table_ref:raise CitationError(f"Invalid table_ref: {table_ref}")
        name,row_id=table_ref.split("#row_id=",1)
        if Path(name).name!=name or name not in self.tables:raise CitationError(f"Unknown or unsafe table_ref: {table_ref}")
        frame=self.tables[name];selected=frame.loc[frame["row_id"].astype(str).eq(row_id)]
        if len(selected)!=1:raise CitationError(f"Citation row is missing or non-unique: {table_ref}")
        return selected.iloc[0].to_dict()


class _Disjoint:
    def __init__(self,values:list[str]):self.parent={value:value for value in values}
    def find(self,value:str)->str:
        while self.parent[value]!=value:self.parent[value]=self.parent[self.parent[value]];value=self.parent[value]
        return value
    def union(self,left:str,right:str)->None:
        a,b=self.find(left),self.find(right)
        if a!=b:self.parent[max(a,b)]=min(a,b)


def build_entity_components(findings: Iterable[dict[str,Any]]) -> list[list[str]]:
    rows=sorted((item for item in findings if item["state"]["pipeline"]=="reportable"),key=lambda item:item["finding_id"]);ids=[item["finding_id"] for item in rows];disjoint=_Disjoint(ids);seen:dict[tuple[str,str],str]={}
    for finding in rows:
        for kind in ENTITY_KEYS:
            for value in finding["entities"].get(kind,[]):
                entity=(kind,str(value))
                if entity in seen:disjoint.union(finding["finding_id"],seen[entity])
                else:seen[entity]=finding["finding_id"]
    groups:dict[str,list[str]]={}
    for identifier in ids:groups.setdefault(disjoint.find(identifier),[]).append(identifier)
    return [sorted(values) for _,values in sorted(groups.items())]


def _numeric_values(rows: list[dict[str,Any]]) -> list[float]:
    result=[]
    for row in rows:
        for value in row.values():
            try:number=float(value)
            except (TypeError,ValueError):continue
            if math.isfinite(number):result.append(number)
    return result


def validate_component_narrative(narrative_id: str,text: str,citation_ids: list[str],available: dict[str,str],registry: EvidenceRegistry,*,relative_tolerance: float=0.01) -> list[str]:
    markers=MARKER.findall(text);unknown=sorted(set(markers+list(citation_ids))-set(available))
    if unknown:raise CitationError(f"{narrative_id}: unknown citation IDs {unknown}")
    if set(markers)-set(citation_ids):raise CitationError(f"{narrative_id}: narrative markers are absent from citations array")
    rows=[registry.row(available[value]) for value in citation_ids];numbers=_numeric_values(rows);stripped=MARKER.sub("",text)
    for token in NUMBER.findall(stripped):
        actual=float(token)
        if not any(abs(actual-expected)<=relative_tolerance*max(abs(expected),1e-12) for expected in numbers):
            refs=[available[value] for value in citation_ids]
            raise CitationError(f"{narrative_id}: numeric token {token} does not match cited rows {refs} within relative tolerance {relative_tolerance}")
    return sorted(set(citation_ids)-set(markers))


def _registered_values(frame: pd.DataFrame, kind: str) -> set[str]:
    values: set[str] = set()
    singular = {"compound_id", "compound_from", "compound_to", "source_compound_id"} if kind == "compound" else {"pair_id"}
    for column in frame.columns:
        if column in singular:
            values.update(str(value) for value in frame[column].dropna())
        elif column.endswith("_json") and f"{kind}_ids" in column:
            for raw in frame[column].dropna():
                try: decoded=json.loads(str(raw))
                except json.JSONDecodeError as exc:raise CitationError(f"Invalid identifier JSON in {column}") from exc
                if not isinstance(decoded,list):raise CitationError(f"Identifier JSON must be an array in {column}")
                values.update(str(value) for value in decoded)
    return values


def validate_finding_tests(findings: Iterable[dict[str,Any]],registry: EvidenceRegistry,entity_ids: set[str],pair_ids: set[str] | None = None) -> None:
    test_rows={}
    for name,frame in registry.tables.items():
        if "test_id" not in frame:continue
        for row in frame.to_dict(orient="records"):
            identifier=str(row["test_id"])
            if identifier in test_rows:raise CitationError(f"Duplicate test_id across evidence tables: {identifier}")
            test_rows[identifier]=(name,row)
    for finding in findings:
        for kind in ("compound_ids","transformation_ids","fragment_ids","scaffold_ids","context_ids"):
            for value in finding["entities"].get(kind,[]):
                if kind=="compound_ids" and str(value) not in entity_ids:raise CitationError(f"{finding['finding_id']}: unknown compound_id {value}")
        for citation in finding["citations"]:registry.row(citation["table_ref"])
        for test in finding["tests"]:
            identifier=str(test["test_id"])
            if identifier not in test_rows:raise CitationError(f"{finding['finding_id']}: test_id not found: {identifier}")
            name,row=test_rows[identifier]
            for field in ("statistic","p_value","q_value"):
                expected=test.get(field);actual=row.get(field)
                if expected is None and pd.isna(actual):continue
                if expected is None or pd.isna(actual) or not np.isclose(float(expected),float(actual),rtol=1e-12,atol=1e-15):raise CitationError(f"{finding['finding_id']}: {field} mismatch for {identifier} in {name}: expected {expected}, actual {actual}")
    cited_compounds=set().union(*(_registered_values(frame,"compound") for frame in registry.tables.values())) if registry.tables else set()
    unknown_compounds=sorted(cited_compounds-entity_ids)
    if unknown_compounds:raise CitationError(f"Evidence contains compound IDs absent from Run registry: {unknown_compounds[:10]}")
    cited_pairs=set().union(*(_registered_values(frame,"pair") for frame in registry.tables.values())) if registry.tables else set()
    if cited_pairs and pair_ids is None:raise CitationError("Evidence contains pair IDs but no mmp_database Run registry was supplied")
    unknown_pairs=sorted(cited_pairs-(pair_ids or set()))
    if unknown_pairs:raise CitationError(f"Evidence contains pair IDs absent from Run registry: {unknown_pairs[:10]}")


def component_id(finding_ids: list[str]) -> str:
    return stable_id("COMPONENT",{"finding_ids":sorted(finding_ids)})
