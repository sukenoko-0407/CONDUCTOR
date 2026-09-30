from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
SPEC = importlib.util.spec_from_file_location("standalone_mmp_run", SCRIPT)
RUN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN)


class StandaloneMmpCliContractTest(unittest.TestCase):
    def test_conductor_entrypoints_are_absent(self) -> None:
        skill = Path(__file__).resolve().parents[1]
        for relative in (
            "capability.json",
            "scripts/launch.py",
            "scripts/conductor_request_adapter.py",
            "scripts/batch_skill_common.py",
        ):
            self.assertFalse((skill / relative).exists(), relative)

    def test_build_requires_endpoint_direction(self) -> None:
        parser = RUN._parser()
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args([
                    "build", "--input", "x.csv", "--output-dir", "out",
                    "--id-column", "id", "--smiles-column", "smiles",
                    "--endpoint-column", "pIC50",
                ])

    def test_report_accepts_multiple_explicit_targets(self) -> None:
        args = RUN._parser().parse_args([
            "report", "--database", "mmp.sqlite", "--output-dir", "out",
            "--target-id", "CMP001", "--target-id", "CMP002",
        ])
        self.assertEqual(args.target_id, ["CMP001", "CMP002"])

    def test_report_reuses_database_structural_contract(self) -> None:
        args = RUN._parser().parse_args([
            "report", "--database", "mmp.sqlite", "--output-dir", "out",
            "--target-id", "CMP001",
        ])
        metadata = {
            "endpoint_column": "pIC50",
            "higher_is_better": True,
            "neutral_tolerance": 0.10,
            "cut_smarts": "cut_AlkylChains",
            "num_cuts": 2,
            "structural_parameters": {
                "min_core_heavy_atoms": 9,
                "min_core_fraction": 0.55,
                "max_variable_heavy_atoms": 18,
                "radius": [1, 2],
                "two_cut_thresholds": {"min_anchor_heavy_atoms": 5},
            },
        }
        config = RUN._report_config(
            args, Path("mmp.sqlite").resolve(), Path("compounds.csv").resolve(), metadata
        )
        parameters = config["parameters"]
        self.assertEqual(parameters["cut_smarts"], "cut_AlkylChains")
        self.assertEqual(parameters["radius_min"], 1)
        self.assertEqual(parameters["radius_max"], 2)
        self.assertEqual(parameters["min_core_heavy_atoms"], 9)
        self.assertEqual(parameters["targets"][0]["compound_id"], "CMP001")
        self.assertEqual(
            parameters["targets"][0]["selection_sources"][0]["source_type"],
            "human_explicit",
        )

    def test_output_must_be_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "existing.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                RUN._prepare_output(root)


if __name__ == "__main__":
    unittest.main()
