from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from csv import DictReader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"


class RepositoryContractTests(unittest.TestCase):
    def test_conductor_is_packaged_without_extra_project_root_modules(self) -> None:
        for name in ["catalog", "docs", "schemas", "tests", "tools"]:
            self.assertTrue((MODULE_ROOT / name).is_dir(), name)
            legacy = ROOT / name
            self.assertFalse(legacy.is_dir() and any(path.is_file() for path in legacy.rglob("*")), name)
        self.assertTrue((MODULE_ROOT / "README.md").is_file())
        self.assertTrue((MODULE_ROOT / "tools" / "install_into_project.py").is_file())
        self.assertTrue((MODULE_ROOT / "tools" / "verify_package_layout.py").is_file())
        catalog = json.loads((MODULE_ROOT / "catalog" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual("CONDUCTOR_modules/catalog/included_skills.json", catalog["selection_path"])
        for agent_name in ["cs-conductor-orchestrator.md", "cs-conductor-interpreter.md"]:
            text = (ROOT / ".claude" / "agents" / agent_name).read_text(encoding="utf-8")
            self.assertIn("CONDUCTOR_modules/", text)

    def test_human_readmes_are_present_and_concise(self) -> None:
        required_sections = [
            "## SKILLの目的",
            "## 想定利用シーン",
            "## 環境構築",
            "## 利用例",
            "## 制約事項",
            "## 変更履歴",
        ]
        skill_directories = sorted(path for path in SKILLS.iterdir() if path.is_dir())
        self.assertEqual(42, len(skill_directories))
        for skill in skill_directories:
            readme = skill / "README.md"
            self.assertTrue(readme.is_file(), skill.name)
            text = readme.read_text(encoding="utf-8")
            for section in required_sections:
                self.assertEqual(1, text.count(section), f"{skill.name}: {section}")
            self.assertIn("scripts/launch.py", text, skill.name)
            self.assertIn("| Version | 変更内容 |", text, skill.name)
            self.assertIn("| 1.0.0 |", text, skill.name)
            self.assertLessEqual(len(text.splitlines()), 60, skill.name)

    def test_allowlisted_skills_are_self_contained(self) -> None:
        import jsonschema

        selection = json.loads((MODULE_ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
        capability_schema = json.loads((MODULE_ROOT / "schemas" / "capability.schema.json").read_text(encoding="utf-8"))
        names = selection["included_skills"]
        self.assertEqual(42, len(names))
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            skill = SKILLS / name
            self.assertTrue((skill / "SKILL.md").is_file(), name)
            self.assertTrue((skill / "capability.json").is_file(), name)
            self.assertTrue((skill / "scripts").is_dir(), name)
            self.assertTrue((skill / "env" / "pixi.toml").is_file(), name)
            capability = json.loads((skill / "capability.json").read_text(encoding="utf-8"))
            jsonschema.validate(capability, capability_schema)
            self.assertEqual(name, capability["skill_name"])
            self.assertLess(len(name), 64)
            self.assertRegex(name, r"^[a-z0-9-]+$")
            manifest = tomllib.loads((skill / "env" / "pixi.toml").read_text(encoding="utf-8"))
            platforms = [item["platform"] if isinstance(item, dict) else item for item in manifest["workspace"]["platforms"]]
            self.assertEqual(["linux-64", "win-64"], platforms)
            runner_files = list((skill / "scripts").glob("*.py"))
            self.assertTrue(runner_files, name)
            combined = "\n".join(path.read_text(encoding="utf-8") for path in runner_files)
            self.assertNotIn("src.conductor", combined)
            self.assertNotIn(".claude.skills", combined)
            launcher = (skill / "scripts" / "launch.py").read_text(encoding="utf-8")
            instructions = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("PIXI_CACHE", instructions, name)
            self.assertIn("UV_CACHE_DIR", instructions, name)
            self.assertIn("pixi is required", launcher)
            self.assertIn("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi", launcher)
            self.assertIn('"--manifest-path"', launcher)
            self.assertIn("skill_dir", launcher)
            self.assertIn("prepare_runtime_environment", launcher)
            self.assertIn("env=runtime_env", launcher)
            for variable in (
                "PIXI_HOME",
                "PIXI_CACHE_DIR",
                "PIXI_CACHE_CONDA_PACKAGES_DIR",
                "PIXI_CACHE_REPODATA_DIR",
                "PIXI_CACHE_PYPI_WHEELS_DIR",
                "PIXI_CACHE_PYPI_MAPPING_DIR",
                "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR",
                "PIXI_CACHE_BUILD_TOOL_ENVIRONMENTS_DIR",
                "PIXI_CACHE_DETACHED_ENVIRONMENTS_DIR",
                "PIXI_CACHE_NETFS_REDIRECT",
                "PIXI_NO_CONFIG",
                "UV_CACHE_DIR",
                "PIP_CACHE_DIR",
                "XDG_CACHE_HOME",
                "TMPDIR",
            ):
                self.assertIn(f'"{variable}"', launcher, f"{name}: {variable}")
            self.assertNotIn("command = [sys.executable", launcher)
            if capability["stage"] in {"description", "grouping", "analysis", "interpretation"}:
                self.assertIn("Mode selection", instructions, name)
                self.assertIn("General mode", instructions, name)
                self.assertIn("CONDUCTOR mode", instructions, name)
                self.assertIn("--project PROJECT --run-id RUN_ID --node-id NODE_ID", instructions, name)
                runner = (skill / "scripts" / "run.py").read_text(encoding="utf-8")
                self.assertNotIn('"--metadata"', runner, name)
                self.assertIn('skill_candidates = [SKILL_DIR, *SKILL_DIR.parents]', runner, name)
                self.assertIn('installed_skill = candidate / ".claude" / "skills" / SKILL_DIR.name', runner, name)
                self.assertIn('candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json"', runner, name)
                self.assertIn("--conductor requires --project, --run-id, and --node-id", runner, name)
                self.assertIn("--project and --node-id are valid only with --conductor", runner, name)
                self.assertIn('str(args.node_id).replace(":", "-")', runner, name)
                self.assertIn("<node-id-safe>", instructions, name)
                self.assertIn("Algorithm-specific options", instructions, name)
            if capability["stage"] in {"description", "grouping", "analysis"}:
                self.assertTrue((skill / "schemas" / "artifact_manifest.schema.json").is_file(), name)

    def test_catalog_matches_human_allowlist(self) -> None:
        selection = json.loads((MODULE_ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
        catalog = json.loads((MODULE_ROOT / "catalog" / "catalog.json").read_text(encoding="utf-8"))
        selected = selection["included_skills"]
        catalog_names = [entry["skill_name"] for entry in catalog["capabilities"]]
        self.assertEqual(set(selected), set(catalog_names))
        ids = [entry["capability_id"] for entry in catalog["capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))
        by_id = {entry["capability_id"]: entry for entry in catalog["capabilities"]}
        preauthorized = []
        for entry in catalog["capabilities"]:
            if entry.get("approval_policy") == "preauthorized_initial":
                preauthorized.append(entry["capability_id"])
                self.assertIn(entry["cost"]["class"], {"high", "very_high"})
                self.assertFalse(entry["cost"]["human_approval_required"])
                self.assertTrue(entry["default_wide_shallow"])
            elif entry["cost"]["class"] in {"high", "very_high"}:
                self.assertTrue(entry["cost"]["human_approval_required"])
        self.assertEqual(["C002"], preauthorized)
        self.assertEqual(
            {"min_cluster_size": 3, "max_pairs": 1000, "max_core_groups": 300, "random_seed": 61453},
            by_id["C002"]["default_parameters"],
        )
        self.assertEqual({"standard", "chiral"}, {item["id"] for item in by_id["D002"]["variants"]})
        self.assertEqual({"folded", "svd"}, {item["id"] for item in by_id["D017"]["variants"]})
        self.assertEqual({"D001", "D002", "D003", "D004", "D007", "D013", "D017"}, {entry["capability_id"] for entry in catalog["capabilities"] if entry["stage"] == "description" and entry.get("default_wide_shallow")})
        self.assertEqual({"C001", "C002", "C003", "C005", "C006", "C007", "C009"}, {entry["capability_id"] for entry in catalog["capabilities"] if entry["stage"] == "grouping" and entry.get("default_wide_shallow")})
        self.assertEqual({f"A{index:03d}" for index in range(1, 11)}, {entry["capability_id"] for entry in catalog["capabilities"] if entry["stage"] == "analysis" and entry.get("default_wide_shallow")})
        self.assertEqual({"description": ["D002"]}, by_id["C005"]["wide_shallow_sources"])
        self.assertEqual({"description": ["D001", "D013", "D017"]}, by_id["C006"]["wide_shallow_sources"])
        self.assertEqual({"description": ["D001"]}, by_id["C007"]["wide_shallow_sources"])
        self.assertEqual({"description": ["D002"]}, by_id["C009"]["wide_shallow_sources"])
        self.assertEqual(
            {"description": {"D004": {"metric": "cosine"}, "D007": {"metric": "tanimoto"}}},
            by_id["A005"]["wide_shallow_parameter_overrides"],
        )
        self.assertEqual(
            {"description": {"D002": {"metric": "tanimoto"}, "D013": {"metric": "manhattan"}, "D017": {"metric": "tanimoto"}}},
            by_id["A006"]["wide_shallow_parameter_overrides"],
        )
        self.assertEqual(["global", "within-group"], by_id["A002"]["scope_support"])
        self.assertEqual(["global", "within-group", "between-groups"], by_id["A006"]["scope_support"])
        self.assertEqual(["global"], by_id["A009"]["scope_support"])
        self.assertEqual({"grouping": ["C002", "C003"]}, by_id["A009"]["wide_shallow_sources"])
        groupings = [entry for entry in catalog["capabilities"] if entry["stage"] == "grouping"]
        self.assertEqual([f"C{index:03d}" for index in range(1, 13)], sorted(entry["capability_id"] for entry in groupings))
        direct = [entry for entry in groupings if entry["grouping_kind"] == "direct_structure"]
        vectors = [entry for entry in groupings if entry["grouping_kind"] == "description_vector"]
        self.assertEqual(4, len(direct))
        self.assertEqual(6, len(vectors))
        self.assertTrue(all(entry["input_contract"] == ["compound_id_smiles_csv"] and not entry["dependencies"] for entry in direct))
        self.assertTrue(all(entry["input_contract"] == ["description_vector_csv"] and entry["dependencies"] == ["description"] for entry in vectors))
        self.assertTrue(all(entry["implementation"]["algorithm"] in {"structure_murcko", "structure_mcs", "structure_brics", "structure_recap"} for entry in direct))
        self.assertFalse(any((SKILLS / f"cs-compute-clustering-structure-{name}").exists() for name in ["butina", "hierarchical", "dbscan", "louvain", "leiden", "connected-components"]))
        self.assertFalse(by_id["I001"]["default_wide_shallow"])
        self.assertNotIn("D011", by_id)
        self.assertNotIn("D018", by_id)

    def test_json_schemas_parse(self) -> None:
        for path in (MODULE_ROOT / "schemas").glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("$schema", value, path.name)

    def test_claude_orchestrator_can_invoke_skills_and_request_approval(self) -> None:
        definition = (ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").read_text(encoding="utf-8")
        self.assertIn("Skill", definition)
        self.assertIn("AskUserQuestion", definition)
        self.assertIn("  - cs-conductor-orchestrator", definition)
        self.assertIn("C002 MCS is the sole initial exception", definition)
        self.assertIn("without asking for run-specific approval", definition)
        self.assertTrue((MODULE_ROOT / "pyproject.toml").is_file())
        self.assertTrue((MODULE_ROOT / "uv.lock").is_file())

    def test_interpretation_has_a_dedicated_policy_managed_terminal_agent(self) -> None:
        agent = (ROOT / ".claude" / "agents" / "cs-conductor-interpreter.md").read_text(encoding="utf-8")
        policy = (MODULE_ROOT / "docs" / "CONDUCTOR_v4_interpretation_policy.md").read_text(encoding="utf-8")
        snapshot = (SKILLS / "cs-analysis-interpret-evidence" / "references" / "interpretation_policy.md").read_text(encoding="utf-8")
        capability = json.loads((SKILLS / "cs-analysis-interpret-evidence" / "capability.json").read_text(encoding="utf-8"))
        self.assertEqual(policy, snapshot)
        self.assertIn("read-only terminal stage", agent)
        self.assertIn("Never request a computation whose signature already appears", agent)
        self.assertIn("falsification", agent.lower())
        self.assertIn("compound ID", agent)
        self.assertIn("exploration_plan", capability["output"])
        self.assertTrue((SKILLS / "cs-analysis-interpret-evidence" / "schemas" / "interpretation_exploration_plan.schema.json").is_file())


@unittest.skipUnless(__import__("importlib").util.find_spec("rdkit"), "RDKit is not installed")
class RuntimeSmokeTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "1"
        return subprocess.run([sys.executable, *arguments], cwd=ROOT, env=environment, check=True, text=True, capture_output=True)

    def test_description_multiple_smiles_general_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "description"
            self.run_cli(
                str(SKILLS / "cs-compute-description-morgan" / "scripts" / "run.py"),
                "--smiles", "CCO", "--smiles", "c1ccccc1", "--n-bits", "64",
                "--output-dir", str(outdir), "--run-id", "unit", "--overwrite",
            )
            self.assertTrue((outdir / "D002_morgan.csv").is_file())
            self.assertFalse((outdir / "description_manifest.json").exists())
            self.assertFalse((outdir / "warnings.json").exists())
            self.assertFalse((outdir / "execution_event.json").exists())

    def test_compound_ids_are_preserved_as_strings_across_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "leading-zero-ids.csv"
            source.write_text(
                "compound_id,smiles,pIC50\n0001,CCO,5.0\n0002,CCN,6.0\n0003,CCC,5.5\n",
                encoding="utf-8",
            )
            description_dir = temporary / "description"
            self.run_cli(
                str(SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"),
                "--input", str(source), "--output-dir", str(description_dir), "--run-id", "leading-zero", "--overwrite",
            )
            description_path = description_dir / "D001_rdkit_2d.csv"
            with description_path.open(encoding="utf-8", newline="") as handle:
                description_ids = [row["compound_id"] for row in DictReader(handle)]
            self.assertEqual(["0001", "0002", "0003"], description_ids)

            grouping_dir = temporary / "grouping"
            self.run_cli(
                str(SKILLS / "cs-compute-clustering-vector-hierarchical" / "scripts" / "run.py"),
                "--input", str(description_path), "--n-clusters", "1", "--min-cluster-size", "1",
                "--output-dir", str(grouping_dir), "--run-id", "leading-zero", "--overwrite",
            )
            with (grouping_dir / "cluster_membership.csv").open(encoding="utf-8", newline="") as handle:
                grouping_ids = {row["compound_id"] for row in DictReader(handle)}
            self.assertEqual({"0001", "0002", "0003"}, grouping_ids)

            analysis_dir = temporary / "analysis"
            self.run_cli(
                str(SKILLS / "cs-analysis-sali" / "scripts" / "run.py"),
                "--input", str(source), "--property-column", "pIC50", "--higher-is-better",
                "--description", str(description_path), "--evaluation-representation", "D001", "--k", "1",
                "--output-dir", str(analysis_dir), "--run-id", "leading-zero", "--overwrite",
            )
            with (analysis_dir / "A006_sali.csv").open(encoding="utf-8", newline="") as handle:
                analysis_ids = {row["compound_id"] for row in DictReader(handle)}
            self.assertEqual({"0001", "0002", "0003"}, analysis_ids)

    def test_description_variant_cli_is_scoped_and_general_outputs_remain_primary_only(self) -> None:
        cases = [
            ("cs-compute-description-rdkit-2d", [], ["--n-bits", "--include-chirality", "--reduction"]),
            ("cs-compute-description-morgan", ["--n-bits", "--include-chirality"], ["--reduction", "--svd-dim"]),
            ("cs-compute-description-gobbi-pharm2d", ["--n-bits", "--reduction", "--svd-dim"], ["--include-chirality", "--radius"]),
            ("cs-compute-description-pretrained-embedding", ["--model-dir", "--device", "--batch-size"], ["--n-bits", "--num-confs"]),
        ]
        for skill_name, present, absent in cases:
            with self.subTest(skill=skill_name):
                process = self.run_cli(str(SKILLS / skill_name / "scripts" / "run.py"), "--help")
                for option in present:
                    self.assertRegex(process.stdout, rf"(?<![\w-]){re.escape(option)}(?=[\s=,\]])")
                for option in absent:
                    self.assertNotRegex(process.stdout, rf"(?<![\w-]){re.escape(option)}(?=[\s=,\]])")

        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "chiral"
            self.run_cli(
                str(SKILLS / "cs-compute-description-morgan" / "scripts" / "run.py"),
                "--smiles", "C[C@H](O)Cl", "--include-chirality", "--n-bits", "64",
                "--output-dir", str(outdir), "--run-id", "chiral", "--overwrite",
            )
            with (outdir / "D002_morgan.csv").open(encoding="utf-8", newline="") as handle:
                columns = next(DictReader(handle)).keys()
            self.assertTrue(any(name.startswith("chiral_morgan_bit_") for name in columns))
            self.assertEqual(["D002_morgan.csv"], sorted(path.name for path in outdir.iterdir()))

    def test_clustering_and_analysis_cli_is_capability_scoped(self) -> None:
        cases = [
            ("cs-compute-clustering-structure-murcko", ["--input", "--min-cluster-size"], ["--smiles", "--compound-id", "--metric", "--similarity-threshold", "--max-core-groups"]),
            ("cs-compute-clustering-structure-mcs", ["--input", "--max-pairs", "--max-core-groups"], ["--smiles", "--compound-id", "--max-cores", "--metric"]),
            ("cs-compute-clustering-structure-brics", ["--input", "--min-cluster-size"], ["--smiles", "--compound-id", "--metric", "--max-pairs"]),
            ("cs-compute-clustering-structure-recap", ["--input", "--min-cluster-size"], ["--smiles", "--compound-id", "--metric", "--max-pairs"]),
            ("cs-compute-clustering-vector-butina", ["--metric", "--similarity-threshold"], ["--radius", "--eps"]),
            ("cs-analysis-descriptor-activity-correlation", ["--description", "--membership", "--scope-mode"], ["--k", "--max-pairs"]),
            ("cs-analysis-activity-cliff", ["--similarity-threshold", "--activity-delta-threshold", "--max-pairs", "--random-seed", "--membership", "--scope-mode"], ["--description", "--k"]),
        ]
        for skill_name, present, absent in cases:
            with self.subTest(skill=skill_name):
                process = self.run_cli(str(SKILLS / skill_name / "scripts" / "run.py"), "--help")
                for option in present:
                    self.assertRegex(process.stdout, rf"(?<![\w-]){re.escape(option)}(?=[\s=,\]])")
                for option in absent:
                    self.assertNotRegex(process.stdout, rf"(?<![\w-]){re.escape(option)}(?=[\s=,\]])")

        mcs_runner = str(SKILLS / "cs-compute-clustering-structure-mcs" / "scripts" / "run.py")
        rejected = subprocess.run(
            [sys.executable, mcs_runner, "--input", str(MODULE_ROOT / "tests" / "data" / "small_sar.csv"), "--max-pairs", "1001"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("--max-pairs must be <= 1000", rejected.stderr)

        for structure_name in ["murcko", "mcs", "brics", "recap"]:
            with self.subTest(inline_rejected=structure_name):
                structure_runner = str(SKILLS / f"cs-compute-clustering-structure-{structure_name}" / "scripts" / "run.py")
                inline_rejected = subprocess.run(
                    [sys.executable, structure_runner, "--smiles", "CCO"],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(2, inline_rejected.returncode)
                self.assertIn("--input", inline_rejected.stderr)

    def test_sali_selects_representation_metric_and_preserves_landscape_evidence(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "small_sar.csv"
        sali_runner = SKILLS / "cs-analysis-sali" / "scripts" / "run.py"
        interpretation_runner = SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "run.py"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            description = temporary / "D002_morgan.csv"
            description.write_text(
                "compound_id,morgan_bit_0,morgan_bit_1,morgan_bit_2\n"
                "CMPD_001,1,0,0\nCMPD_002,1,0,0\nCMPD_003,1,1,0\n"
                "CMPD_004,0,0,1\nCMPD_005,0,1,1\nCMPD_006,0,1,1\n",
                encoding="utf-8",
            )
            outdir = temporary / "sali"
            self.run_cli(
                str(sali_runner), "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                "--description", str(description), "--evaluation-representation", "D002", "--metric", "auto", "--k", "2",
                "--output-dir", str(outdir), "--conductor", "--project", "unit", "--run-id", "sali-metric",
                "--node-id", "A006:001", "--overwrite",
            )
            evidence = json.loads((outdir / "evidence.json").read_text(encoding="utf-8"))
            summary = evidence["machine_readable_summary"]
            self.assertEqual("tanimoto", summary["metric"])
            self.assertEqual("auto", summary["requested_metric"])
            self.assertIn("median_sali", summary)
            self.assertIn("p95_sali", summary)
            self.assertTrue(summary["top_sali_pairs"])
            self.assertTrue(evidence["supporting_pairs"])
            self.assertTrue(all(pair["compound_id_a"] != pair["compound_id_b"] for pair in evidence["supporting_pairs"]))
            self.assertTrue(any({pair["compound_id_a"], pair["compound_id_b"]} == {"CMPD_001", "CMPD_002"} for pair in evidence["supporting_pairs"]))
            self.assertIsInstance(evidence["uncertainty"], dict)
            self.assertEqual("global", evidence["scope"]["mode"])

            membership = MODULE_ROOT / "tests" / "data" / "scope_membership.csv"
            scoped_evidence = []
            for label, node_id, extra in [
                ("within", "A006:002", ["--target-group", "G_ALIPHATIC", "--scope-mode", "within-group"]),
                ("between", "A006:003", ["--target-group", "G_ALIPHATIC", "--comparison-group", "G_AROMATIC", "--scope-mode", "between-groups"]),
            ]:
                scoped_outdir = temporary / label
                self.run_cli(
                    str(sali_runner), "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                    "--description", str(description), "--membership", str(membership),
                    "--evaluation-representation", "D002", "--metric", "auto", "--k", "2",
                    "--reference-scope", "global", "--output-dir", str(scoped_outdir), "--conductor",
                    "--project", "unit", "--run-id", "sali-metric", "--node-id", node_id, "--overwrite", *extra,
                )
                scoped_evidence.append(json.loads((scoped_outdir / "evidence.json").read_text(encoding="utf-8")))
            self.assertEqual("within-group", scoped_evidence[0]["scope"]["mode"])
            self.assertEqual(3, scoped_evidence[0]["scope"]["sample_count"])
            self.assertEqual("global", scoped_evidence[0]["scope"]["reference_scope"])
            self.assertEqual("between-groups", scoped_evidence[1]["scope"]["mode"])
            self.assertEqual(6, scoped_evidence[1]["scope"]["sample_count"])
            self.assertEqual(3, len({evidence["evidence_id"], *(item["evidence_id"] for item in scoped_evidence)}))

            rejected = subprocess.run(
                [sys.executable, str(sali_runner), "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                 "--description", str(description), "--evaluation-representation", "D002", "--metric", "cosine",
                 "--output-dir", str(temporary / "rejected")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Binary Description vectors require --metric tanimoto", rejected.stderr)

            interpreted = temporary / "interpretation"
            self.run_cli(
                str(interpretation_runner), "--evidence", str(outdir / "evidence.json"),
                "--evidence", str(temporary / "within" / "evidence.json"),
                "--evidence", str(temporary / "between" / "evidence.json"),
                "--output-dir", str(interpreted), "--run-id", "sali-metric", "--overwrite",
            )
            interpretation = json.loads((interpreted / "interpretation.json").read_text(encoding="utf-8"))
            self.assertTrue(interpretation["hypotheses"][0]["focus_pairs"])
            self.assertIn("SALI landscape", interpretation["notable_findings"][0]["observation"])
            self.assertTrue(any(item["relation_type"] == "localizes" for item in interpretation["evidence_relations"]))

    @unittest.skipUnless(__import__("importlib").util.find_spec("sklearn") and __import__("importlib").util.find_spec("scipy"), "scikit-learn and SciPy are not installed")
    def test_vector_clustering_requires_a_description_vector_and_binary_tanimoto(self) -> None:
        runner = SKILLS / "cs-compute-clustering-vector-butina" / "scripts" / "run.py"
        raw_smiles = subprocess.run(
            [sys.executable, str(runner), "--smiles", "CCO"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertNotEqual(0, raw_smiles.returncode)
        self.assertIn("--input", raw_smiles.stderr)

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            description = temporary / "description.csv"
            description.write_text(
                "compound_id,mol_parse_ok,bit_0,bit_1,bit_2\n"
                "A,True,1,0,1\nB,True,1,0,1\nC,True,0,1,0\nD,False,,,\n",
                encoding="utf-8",
            )
            outdir = temporary / "grouping"
            self.run_cli(
                str(runner), "--input", str(description), "--metric", "tanimoto",
                "--similarity-threshold", "0.5", "--min-cluster-size", "1",
                "--output-dir", str(outdir), "--run-id", "tanimoto", "--overwrite",
            )
            with (outdir / "cluster_membership.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(DictReader(handle))
            invalid = next(row for row in rows if row["compound_id"] == "D")
            self.assertEqual("0.0", invalid["membership_value"])
            self.assertEqual("invalid_smiles", invalid["membership_reason"])
            duplicate_vector_rows = [row for row in rows if row["compound_id"] in {"A", "B"} and row["membership_value"] == "1.0"]
            self.assertEqual(2, len(duplicate_vector_rows))
            self.assertEqual(duplicate_vector_rows[0]["cluster_id"], duplicate_vector_rows[1]["cluster_id"])
            self.assertFalse((outdir / "grouping_manifest.json").exists())

            rejected = subprocess.run(
                [sys.executable, str(runner), "--input", str(description), "--metric", "cosine", "--output-dir", str(temporary / "rejected")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Binary Description vectors require --metric tanimoto", rejected.stderr)

    @unittest.skipUnless(__import__("importlib").util.find_spec("sklearn") and __import__("importlib").util.find_spec("scipy"), "scikit-learn and SciPy are not installed")
    def test_gobbi_pharm2d_svd_is_a_general_mode_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "pharm2d-svd"
            self.run_cli(
                str(SKILLS / "cs-compute-description-gobbi-pharm2d" / "scripts" / "run.py"),
                "--smiles", "CCO", "--smiles", "CCN", "--smiles", "c1ccccc1",
                "--reduction", "svd", "--svd-dim", "2",
                "--output-dir", str(outdir), "--run-id", "svd", "--overwrite",
            )
            with (outdir / "D017_gobbi_pharm2d.csv").open(encoding="utf-8", newline="") as handle:
                columns = next(DictReader(handle)).keys()
            self.assertTrue(any(name.startswith("pharm2d_svd__") for name in columns))
            self.assertEqual(["D017_gobbi_pharm2d.csv"], sorted(path.name for path in outdir.iterdir()))

    def test_state_rejects_an_unplanned_description_variant(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "small_sar.csv"
        state_manager = SKILLS / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
        runner = SKILLS / "cs-compute-description-morgan" / "scripts" / "run.py"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state_root = temporary / "state"
            state_path = state_root / "state.json"
            run_id = "variant_contract"
            self.run_cli(str(state_manager), "init", "--input", str(data), "--endpoint", "pIC50", "--higher-is-better", "--project", "unit", "--parallel-limit", "1", "--run-id", run_id, "--output-dir", str(state_root))
            self.run_cli(str(state_manager), "add", "--state", str(state_path), "--capability-id", "D002", "--parameters-json", '{"include_chirality":true}', "--reason", "unit variant contract")
            planned_state = json.loads(state_path.read_text(encoding="utf-8"))
            outdir = Path(planned_state["execution_graph"]["nodes"][0]["output_dir"])
            self.run_cli(str(state_manager), "start", "--state", str(state_path), "--node-id", "D002:001")
            self.run_cli(str(runner), "--input", str(data), "--n-bits", "2048", "--output-dir", str(outdir), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "D002:001", "--overwrite")
            rejected = subprocess.run(
                [sys.executable, str(state_manager), "record", "--state", str(state_path), "--event", str(outdir / "execution_event.json")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Event configuration does not match planned node parameters", rejected.stderr)

            self.run_cli(str(runner), "--input", str(data), "--include-chirality", "--n-bits", "2048", "--output-dir", str(outdir), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "D002:001", "--overwrite")
            self.run_cli(str(state_manager), "record", "--state", str(state_path), "--event", str(outdir / "execution_event.json"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            node = state["execution_graph"]["nodes"][0]
            self.assertEqual("succeeded", node["status"])
            self.assertTrue(node["configuration"]["include_chirality"])

    def test_mode_argument_contract_is_enforced(self) -> None:
        runner = str(SKILLS / "cs-compute-description-morgan" / "scripts" / "run.py")
        cases = [
            (["--smiles", "CCO", "--conductor", "--run-id", "unit"], "--conductor requires --project, --run-id, and --node-id"),
            (["--smiles", "CCO", "--project", "unit"], "--project and --node-id are valid only with --conductor"),
            (["--smiles", "CCO", "--metadata"], "unrecognized arguments: --metadata"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                process = subprocess.run([sys.executable, runner, *arguments], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(2, process.returncode)
                self.assertIn(message, process.stderr)

    def test_jak2_description_regression(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "chemble_jak2.csv"
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "jak2"
            self.run_cli(
                str(SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"),
                "--input", str(data), "--output-dir", str(outdir), "--run-id", "jak2_regression", "--overwrite",
            )
            output = outdir / "D001_rdkit_2d.csv"
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(DictReader(handle))
            self.assertEqual(231, len(rows))
            self.assertEqual("CHEMBL3639983", rows[0]["compound_id"])
            self.assertTrue(all(row["mol_parse_ok"] == "True" for row in rows))

    def test_invalid_smiles_is_retained_and_duplicate_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            invalid_input = temporary / "invalid.csv"
            invalid_input.write_text("compound_id,smiles\nA,CCO\nB,not-a-smiles\n", encoding="utf-8")
            outdir = temporary / "description"
            self.run_cli(
                str(SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"),
                "--input", str(invalid_input), "--output-dir", str(outdir), "--conductor", "--project", "unit", "--run-id", "invalid", "--node-id", "D001:invalid", "--overwrite",
            )
            with (outdir / "D001_rdkit_2d.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(DictReader(handle))
            self.assertEqual(2, len(rows))
            self.assertEqual("False", rows[1]["mol_parse_ok"])
            warnings = json.loads((outdir / "warnings.json").read_text(encoding="utf-8"))
            self.assertTrue(warnings["warnings"])

            grouping = temporary / "grouping"
            self.run_cli(
                str(SKILLS / "cs-compute-clustering-structure-murcko" / "scripts" / "run.py"),
                "--input", str(invalid_input), "--output-dir", str(grouping), "--conductor", "--project", "unit", "--run-id", "invalid", "--node-id", "C001:invalid", "--min-cluster-size", "1", "--overwrite",
            )
            with (grouping / "cluster_membership.csv").open(encoding="utf-8", newline="") as handle:
                membership_rows = list(DictReader(handle))
            invalid_membership = next(row for row in membership_rows if row["compound_id"] == "B")
            self.assertEqual("0.0", invalid_membership["membership_value"])
            self.assertEqual("invalid_smiles", invalid_membership["membership_reason"])

            duplicate_input = temporary / "duplicate.csv"
            duplicate_input.write_text("compound_id,smiles\nA,CCO\nA,CCC\n", encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"), "--input", str(duplicate_input), "--output-dir", str(temporary / "duplicate-output")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, process.returncode)
            self.assertIn("Duplicate compound IDs", process.stderr)

    def test_meta_overlap_accepts_long_membership_and_boolean_matrix_shards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            membership = MODULE_ROOT / "tests" / "data" / "meta_overlap.csv"
            outdir = temporary / "meta"
            self.run_cli(
                str(SKILLS / "cs-compute-clustering-meta-overlap" / "scripts" / "run.py"),
                "--input", str(membership), "--output-dir", str(outdir), "--min-cluster-size", "1", "--run-id", "meta", "--overwrite",
            )
            self.assertTrue((outdir / "cluster_membership.csv").is_file())
            self.assertTrue((outdir / "cluster_summary.csv").is_file())
            for auxiliary in ["group_registry.json", "grouping_manifest.json", "warnings.json", "execution_event.json"]:
                self.assertFalse((outdir / auxiliary).exists(), auxiliary)

            shard_a = temporary / "Cpd_Group_matrix_G000000_099999.csv"
            shard_b = temporary / "Cpd_Group_matrix_G100000_199999.csv"
            shard_a.write_text(
                "compound_id,G_A,G_B\nA,True,False\nB,True,True\nC,False,True\n",
                encoding="utf-8",
            )
            shard_b.write_text(
                "compound_id,G_C\nA,False\nB,True\nC,True\n",
                encoding="utf-8",
            )
            wide_outdir = temporary / "meta-wide"
            self.run_cli(
                str(SKILLS / "cs-compute-clustering-meta-overlap" / "scripts" / "run.py"),
                "--input", str(shard_a), "--input", str(shard_b), "--output-dir", str(wide_outdir),
                "--min-cluster-size", "1", "--run-id", "meta-wide", "--overwrite",
            )
            with (wide_outdir / "cluster_membership.csv").open(encoding="utf-8", newline="") as handle:
                wide_rows = list(DictReader(handle))
            self.assertEqual({"A", "B", "C"}, {row["compound_id"] for row in wide_rows if float(row["membership_value"]) > 0})

    def test_mcs_pair_cap_is_random_seeded_and_bounded(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "small_sar.csv"
        runner = SKILLS / "cs-compute-clustering-structure-mcs" / "scripts" / "run.py"
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "mcs"
            self.run_cli(
                str(runner), "--input", str(data), "--min-cluster-size", "3",
                "--max-pairs", "5", "--max-core-groups", "300", "--random-seed", "123",
                "--output-dir", str(outdir), "--conductor", "--project", "unit",
                "--run-id", "mcs-random", "--node-id", "C002:001", "--overwrite",
            )
            manifest = json.loads((outdir / "grouping_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(15, manifest["details"]["pair_population"])
            self.assertEqual(5, manifest["details"]["evaluated_pair_count"])
            self.assertEqual("uniform_random_without_replacement", manifest["details"]["pair_sampling"])
            self.assertEqual(123, manifest["details"]["random_seed"])
            rejected = subprocess.run(
                [sys.executable, str(runner), "--input", str(data), "--max-pairs", "1001", "--output-dir", str(Path(directory) / "rejected")],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("--max-pairs must be <= 1000", rejected.stderr)

            operator_outdir = Path(directory) / "pairwise"
            self.run_cli(
                str(SKILLS / "cs-analysis-pairwise-structure-similarity" / "scripts" / "run.py"),
                "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                "--max-pairs", "5", "--random-seed", "321", "--output-dir", str(operator_outdir),
                "--conductor", "--project", "unit", "--run-id", "pair-random", "--node-id", "A003:001", "--overwrite",
            )
            operator_evidence = json.loads((operator_outdir / "evidence.json").read_text(encoding="utf-8"))
            operator_summary = operator_evidence["machine_readable_summary"]
            self.assertEqual(15, operator_summary["eligible_pair_count"])
            self.assertEqual(5, operator_summary["evaluated_pair_count"])
            self.assertEqual("uniform_random_without_replacement", operator_summary["pair_sampling"])
            self.assertEqual(321, operator_summary["random_seed"])

    def test_analysis_general_mode_emits_only_primary_result(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "small_sar.csv"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            outdir = temporary / "analysis"
            self.run_cli(
                str(SKILLS / "cs-analysis-activity-distribution" / "scripts" / "run.py"),
                "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                "--output-dir", str(outdir), "--run-id", "general", "--overwrite",
            )
            self.assertTrue((outdir / "A002_activity_distribution.csv").is_file())
            for auxiliary in ["evidence.json", "analysis_manifest.json", "warnings.json", "execution_event.json"]:
                self.assertFalse((outdir / auxiliary).exists(), auxiliary)

            wide_membership = temporary / "wide-membership.csv"
            wide_membership.write_text(
                "compound_id,G_A,G_B\n"
                "CMPD_001,True,False\nCMPD_002,True,False\nCMPD_003,True,False\n"
                "CMPD_004,False,True\nCMPD_005,False,True\nCMPD_006,False,True\n",
                encoding="utf-8",
            )
            group_outdir = temporary / "group-profile"
            self.run_cli(
                str(SKILLS / "cs-analysis-group-profile" / "scripts" / "run.py"),
                "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                "--membership", str(wide_membership), "--output-dir", str(group_outdir), "--overwrite",
            )
            with (group_outdir / "A001_group_profile.csv").open(encoding="utf-8", newline="") as handle:
                group_rows = list(DictReader(handle))
            self.assertEqual({"G_A", "G_B"}, {row["group_id"] for row in group_rows})

    def test_end_to_end_artifact_chain(self) -> None:
        data = MODULE_ROOT / "tests" / "data" / "small_sar.csv"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            description = temporary / "description"
            analysis = temporary / "analysis"
            interpretation = temporary / "interpretation"
            state_root = temporary / "state-run"
            state_path = state_root / "state.json"
            run_id = "unit_e2e"
            state_manager = SKILLS / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
            self.run_cli(str(state_manager), "init", "--input", str(data), "--endpoint", "pIC50", "--higher-is-better", "--assay-column", "assay", "--project", "unit", "--parallel-limit", "2", "--run-id", run_id, "--output-dir", str(state_root))
            self.run_cli(str(state_manager), "plan-wide", "--state", str(state_path))
            planned_state = json.loads(state_path.read_text(encoding="utf-8"))
            assay_node = next(node for node in planned_state["execution_graph"]["nodes"] if node["capability_id"] == "C011")
            self.assertEqual("assay", assay_node["parameters"]["columns"])
            self.assertEqual(str(data), assay_node["parameters"]["input"])
            description_node = next(node for node in planned_state["execution_graph"]["nodes"] if node["capability_id"] == "D001")
            description = Path(description_node["output_dir"])
            grouping_node = next(node for node in planned_state["execution_graph"]["nodes"] if node["capability_id"] == "C001")
            grouping = Path(grouping_node["output_dir"])
            self.run_cli(str(state_manager), "start", "--state", str(state_path), "--node-id", "D001:001")
            self.run_cli(str(SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"), "--input", str(data), "--output-dir", str(description), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "D001:001", "--overwrite")
            description_event = json.loads((description / "execution_event.json").read_text(encoding="utf-8"))
            self.assertEqual("unit", description_event["project"])
            self.assertIsInstance(description_event["configuration"], dict)
            wrong_project_event = dict(description_event, project="wrong-project")
            wrong_project_path = description / "wrong-project-event.json"
            wrong_project_path.write_text(json.dumps(wrong_project_event), encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(state_manager), "record", "--state", str(state_path), "--event", str(wrong_project_path)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Event project does not match State", rejected.stderr)
            self.run_cli(str(state_manager), "record", "--state", str(state_path), "--event", str(description / "execution_event.json"))
            self.run_cli(str(state_manager), "start", "--state", str(state_path), "--node-id", grouping_node["node_id"])
            self.run_cli(str(SKILLS / "cs-compute-clustering-structure-murcko" / "scripts" / "run.py"), "--input", str(data), "--output-dir", str(grouping), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", grouping_node["node_id"], "--min-cluster-size", "3", "--overwrite")
            self.run_cli(str(state_manager), "record", "--state", str(state_path), "--event", str(grouping / "execution_event.json"))
            self.run_cli(str(SKILLS / "cs-analysis-activity-distribution" / "scripts" / "run.py"), "--input", str(data), "--property-column", "pIC50", "--higher-is-better", "--output-dir", str(analysis), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "A002:001", "--overwrite")
            self.run_cli(str(SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "run.py"), "--evidence", str(analysis / "evidence.json"), "--state", str(state_path), "--output-dir", str(interpretation), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "I001:001", "--overwrite")
            standalone_interpretation = temporary / "standalone-interpretation"
            self.run_cli(str(SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "run.py"), "--evidence", str(analysis / "evidence.json"), "--output-dir", str(standalone_interpretation), "--run-id", run_id, "--overwrite")
            self.assertFalse((standalone_interpretation / "execution_event.json").exists())
            for path in [description / "execution_event.json", grouping / "group_registry.json", analysis / "evidence.json", interpretation / "interpretation.json", interpretation / "interpretation.md", interpretation / "interpretation.html"]:
                self.assertTrue(path.is_file(), path)
            html_report = (interpretation / "interpretation.html").read_text(encoding="utf-8")
            for heading in ["探索概要", "Evidence index", "注目すべき発見", "Evidence間関係", "未解決の矛盾", "仮説・検証候補", "推奨される次解析", "人間による確認事項"]:
                self.assertIn(heading, html_report)
            edited_interpretation = json.loads((interpretation / "interpretation.json").read_text(encoding="utf-8"))
            edited_interpretation["human_review_points"].append("RENDER_SENTINEL")
            (interpretation / "interpretation.json").write_text(json.dumps(edited_interpretation), encoding="utf-8")
            self.run_cli(
                str(SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "render.py"),
                "--input", str(interpretation / "interpretation.json"),
            )
            self.assertIn("RENDER_SENTINEL", (interpretation / "interpretation.html").read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("succeeded", state["execution_graph"]["nodes"][0]["status"])
            self.assertEqual(1, state["group_index"]["group_count"])
            registry_path = Path(state["group_index"]["registry_path"])
            matrix_path = Path(state["group_index"]["matrix_shards"][0]["path"])
            with registry_path.open(encoding="utf-8", newline="") as handle:
                registry_rows = list(DictReader(handle))
            with matrix_path.open(encoding="utf-8", newline="") as handle:
                matrix_rows = list(DictReader(handle))
            self.assertEqual(grouping_node["node_id"], registry_rows[0]["source_node_id"])
            self.assertRegex(registry_rows[0]["group_id"], r"^G_C001_001_[A-F0-9]{16}$")
            self.assertIn(registry_rows[0]["group_id"], matrix_rows[0])


if __name__ == "__main__":
    unittest.main()
