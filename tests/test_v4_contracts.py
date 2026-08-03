from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from csv import DictReader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude" / "skills"


class RepositoryContractTests(unittest.TestCase):
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
        self.assertEqual(48, len(skill_directories))
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

        selection = json.loads((ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
        capability_schema = json.loads((ROOT / "schemas" / "capability.schema.json").read_text(encoding="utf-8"))
        names = selection["included_skills"]
        self.assertEqual(48, len(names))
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
                self.assertIn("--conductor requires --project, --run-id, and --node-id", runner, name)
                self.assertIn("--project and --node-id are valid only with --conductor", runner, name)
                self.assertIn("Algorithm-specific options", instructions, name)
            if capability["stage"] in {"description", "grouping", "analysis"}:
                self.assertTrue((skill / "schemas" / "artifact_manifest.schema.json").is_file(), name)

    def test_catalog_matches_human_allowlist(self) -> None:
        selection = json.loads((ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
        catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text(encoding="utf-8"))
        selected = selection["included_skills"]
        catalog_names = [entry["skill_name"] for entry in catalog["capabilities"]]
        self.assertEqual(set(selected), set(catalog_names))
        ids = [entry["capability_id"] for entry in catalog["capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in catalog["capabilities"]:
            if entry["cost"]["class"] in {"high", "very_high"}:
                self.assertTrue(entry["cost"]["human_approval_required"])
        by_id = {entry["capability_id"]: entry for entry in catalog["capabilities"]}
        self.assertEqual({"standard", "chiral"}, {item["id"] for item in by_id["D002"]["variants"]})
        self.assertEqual({"folded", "svd"}, {item["id"] for item in by_id["D017"]["variants"]})
        self.assertNotIn("D011", by_id)
        self.assertNotIn("D018", by_id)

    def test_json_schemas_parse(self) -> None:
        for path in (ROOT / "schemas").glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("$schema", value, path.name)

    def test_claude_orchestrator_can_invoke_skills_and_request_approval(self) -> None:
        definition = (ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").read_text(encoding="utf-8")
        self.assertIn("Skill", definition)
        self.assertIn("AskUserQuestion", definition)
        self.assertIn("  - cs-conductor-orchestrator", definition)
        self.assertTrue((ROOT / "pyproject.toml").is_file())
        self.assertTrue((ROOT / "uv.lock").is_file())


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
                    self.assertIn(option, process.stdout)
                for option in absent:
                    self.assertNotIn(option, process.stdout)

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
            ("cs-compute-clustering-structure-murcko", ["--min-cluster-size"], ["--metric", "--similarity-threshold", "--max-core-groups"]),
            ("cs-compute-clustering-structure-mcs", ["--max-pairs", "--max-core-groups"], ["--max-cores", "--metric"]),
            ("cs-compute-clustering-vector-butina", ["--metric", "--similarity-threshold"], ["--radius", "--eps"]),
            ("cs-analysis-descriptor-activity-correlation", ["--description"], ["--k", "--max-pairs", "--membership"]),
            ("cs-analysis-activity-cliff", ["--similarity-threshold", "--activity-delta-threshold", "--max-pairs"], ["--description", "--membership", "--k"]),
        ]
        for skill_name, present, absent in cases:
            with self.subTest(skill=skill_name):
                process = self.run_cli(str(SKILLS / skill_name / "scripts" / "run.py"), "--help")
                for option in present:
                    self.assertIn(option, process.stdout)
                for option in absent:
                    self.assertNotIn(option, process.stdout)

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
        data = ROOT / "tests" / "data" / "small_sar.csv"
        state_manager = SKILLS / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
        runner = SKILLS / "cs-compute-description-morgan" / "scripts" / "run.py"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state_root = temporary / "state"
            state_path = state_root / "state.json"
            outdir = temporary / "description"
            run_id = "variant_contract"
            self.run_cli(str(state_manager), "init", "--input", str(data), "--endpoint", "pIC50", "--higher-is-better", "--project", "unit", "--parallel-limit", "1", "--run-id", run_id, "--output-dir", str(state_root))
            self.run_cli(str(state_manager), "add", "--state", str(state_path), "--capability-id", "D002", "--parameters-json", '{"include_chirality":true}', "--reason", "unit variant contract")
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
        data = ROOT / "chemble_jak2.csv"
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

    def test_meta_overlap_accepts_long_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            membership = ROOT / "tests" / "data" / "meta_overlap.csv"
            outdir = temporary / "meta"
            self.run_cli(
                str(SKILLS / "cs-compute-clustering-meta-overlap" / "scripts" / "run.py"),
                "--input", str(membership), "--output-dir", str(outdir), "--min-cluster-size", "1", "--run-id", "meta", "--overwrite",
            )
            self.assertTrue((outdir / "cluster_membership.csv").is_file())
            self.assertTrue((outdir / "cluster_summary.csv").is_file())
            for auxiliary in ["group_registry.json", "grouping_manifest.json", "warnings.json", "execution_event.json"]:
                self.assertFalse((outdir / auxiliary).exists(), auxiliary)

    def test_analysis_general_mode_emits_only_primary_result(self) -> None:
        data = ROOT / "tests" / "data" / "small_sar.csv"
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory) / "analysis"
            self.run_cli(
                str(SKILLS / "cs-analysis-activity-distribution" / "scripts" / "run.py"),
                "--input", str(data), "--property-column", "pIC50", "--higher-is-better",
                "--output-dir", str(outdir), "--run-id", "general", "--overwrite",
            )
            self.assertTrue((outdir / "A002_activity_distribution.csv").is_file())
            for auxiliary in ["evidence.json", "analysis_manifest.json", "warnings.json", "execution_event.json"]:
                self.assertFalse((outdir / auxiliary).exists(), auxiliary)

    def test_end_to_end_artifact_chain(self) -> None:
        data = ROOT / "tests" / "data" / "small_sar.csv"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            description = temporary / "description"
            grouping = temporary / "grouping"
            analysis = temporary / "analysis"
            interpretation = temporary / "interpretation"
            state_root = temporary / "state-run"
            state_path = state_root / "state.json"
            run_id = "unit_e2e"
            state_manager = SKILLS / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
            self.run_cli(str(state_manager), "init", "--input", str(data), "--endpoint", "pIC50", "--higher-is-better", "--assay-column", "assay", "--project", "unit", "--parallel-limit", "2", "--run-id", run_id, "--output-dir", str(state_root))
            self.run_cli(str(state_manager), "plan-wide", "--state", str(state_path))
            planned_state = json.loads(state_path.read_text(encoding="utf-8"))
            assay_node = next(node for node in planned_state["execution_graph"]["nodes"] if node["capability_id"] == "C017")
            self.assertEqual({"columns": "assay"}, assay_node["parameters"])
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
            self.run_cli(str(SKILLS / "cs-compute-clustering-structure-murcko" / "scripts" / "run.py"), "--input", str(data), "--output-dir", str(grouping), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "C001:001", "--min-cluster-size", "1", "--overwrite")
            self.run_cli(str(SKILLS / "cs-analysis-activity-distribution" / "scripts" / "run.py"), "--input", str(data), "--property-column", "pIC50", "--higher-is-better", "--output-dir", str(analysis), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "A002:001", "--overwrite")
            self.run_cli(str(SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "run.py"), "--evidence", str(analysis / "evidence.json"), "--output-dir", str(interpretation), "--conductor", "--project", "unit", "--run-id", run_id, "--node-id", "I001:001", "--overwrite")
            standalone_interpretation = temporary / "standalone-interpretation"
            self.run_cli(str(SKILLS / "cs-analysis-interpret-evidence" / "scripts" / "run.py"), "--evidence", str(analysis / "evidence.json"), "--output-dir", str(standalone_interpretation), "--run-id", run_id, "--overwrite")
            self.assertFalse((standalone_interpretation / "execution_event.json").exists())
            for path in [description / "execution_event.json", grouping / "group_registry.json", analysis / "evidence.json", interpretation / "interpretation.json", interpretation / "interpretation.md", interpretation / "interpretation.html"]:
                self.assertTrue(path.is_file(), path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("succeeded", state["execution_graph"]["nodes"][0]["status"])


if __name__ == "__main__":
    unittest.main()
