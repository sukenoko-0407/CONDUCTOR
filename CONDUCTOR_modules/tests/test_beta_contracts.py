from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
MODULES=ROOT/"CONDUCTOR_modules"
SKILLS=ROOT/".claude"/"skills"


class BetaContracts(unittest.TestCase):
    def test_catalog_and_ids(self)->None:
        self.assertEqual("0.1.8",(MODULES/"VERSION").read_text(encoding="utf-8").strip())
        catalog=json.loads((MODULES/"catalog"/"catalog.json").read_text(encoding="utf-8"));self.assertEqual("0.1.8",catalog["conductor_version"])
        by_id={item["capability_id"]:item for item in catalog["capabilities"]}
        self.assertEqual([f"D{i:03d}" for i in range(1,17)]+["D019","D020"],sorted(k for k in by_id if k.startswith("D")))
        self.assertEqual([f"C{i:03d}" for i in range(1,13)],sorted(k for k in by_id if k.startswith("C")))
        self.assertEqual([f"A{i:03d}" for i in range(1,15)],sorted(k for k in by_id if k.startswith("A")))
        self.assertEqual("cs-analysis-matched-molecular-pairs", by_id["A014"]["skill_name"])
        self.assertEqual("cs-compute-description-tblite-xtb",by_id["D019"]["skill_name"])
        self.assertEqual("cs-compute-description-chemberta-embedding",by_id["D020"]["skill_name"])
        self.assertEqual("euclidean",by_id["D019"]["natural_metric"]);self.assertEqual("cosine",by_id["D020"]["natural_metric"])
        self.assertEqual(["D001","D002","D006","D013","D016","D019"],by_id["A005"]["fixed_description_panel"])
        self.assertFalse(by_id["A005"]["cost"]["human_approval_required"])

    def test_all_selected_skills_are_self_contained(self)->None:
        selection=json.loads((MODULES/"catalog"/"included_skills.json").read_text(encoding="utf-8"))
        for name in [*selection["included_skills"],*selection.get("support_skills",[])]:
            root=SKILLS/name
            for relative in ("SKILL.md","README.md","capability.json","scripts/launch.py","env/pixi.toml"):
                self.assertTrue((root/relative).is_file(),f"{name}: {relative}")
            launcher=(root/"scripts"/"launch.py").read_text(encoding="utf-8")
            for token in ("assets_pixi-binary/latest/pixi","PIXI_CACHE_DIR","UV_CACHE_DIR","--manifest-path","--locked"):
                self.assertIn(token,launcher,f"{name}: {token}")

    def test_all_skill_environments_support_linux_and_keep_temporary_data_local(self)->None:
        selection=json.loads((MODULES/"catalog"/"included_skills.json").read_text(encoding="utf-8"))
        for name in [*selection["included_skills"],*selection.get("support_skills",[])]:
            root=SKILLS/name
            manifest=tomllib.loads((root/"env"/"pixi.toml").read_text(encoding="utf-8"))
            self.assertEqual({"linux-64","win-64"},set(manifest["workspace"]["platforms"]),name)
            launcher=(root/"scripts"/"launch.py").read_text(encoding="utf-8")
            for token in ("PIXI_CACHE_DIR","UV_CACHE_DIR","TMPDIR","TEMP"):
                self.assertIn(token,launcher,f"{name}: {token}")

    def test_public_contract_uses_cluster_terms(self)->None:
        selection=json.loads((MODULES/"catalog"/"included_skills.json").read_text(encoding="utf-8"))
        roots=[ROOT/".claude"/"agents"/"cs-conductor-executor.md",ROOT/".claude"/"agents"/"cs-conductor-interpreter.md",SKILLS/"cs-conductor-orchestrator"/"SKILL.md"]
        for name in selection["included_skills"]: roots.extend([SKILLS/name/"SKILL.md",SKILLS/name/"README.md",SKILLS/name/"capability.json"])
        for path in roots:
            text=path.read_text(encoding="utf-8")
            self.assertNotIn("CONDUCTOR_v4",text,str(path));self.assertNotIn("interpret-evidence",text,str(path));self.assertNotIn("pretrained-embedding",text,str(path))
            self.assertNotIn('"stage": "grouping"',text,str(path));self.assertNotIn("/grouping/",text,str(path))

    def test_clustering_and_metric_contracts(self)->None:
        catalog=json.loads((MODULES/"catalog"/"catalog.json").read_text(encoding="utf-8"));clusters=[x for x in catalog["capabilities"] if x["stage"]=="clustering"]
        self.assertTrue(all(x["default_parameters"].get("min_cluster_size")==5 for x in clusters))
        mcs=next(x for x in clusters if x["capability_id"]=="C002")
        self.assertEqual(1000,mcs["default_parameters"]["max_pairs"]);self.assertGreaterEqual(mcs["default_parameters"]["max_core_clusters"],300)
        runner=(SKILLS/mcs["skill_name"]/"scripts"/"run.py").read_text(encoding="utf-8")
        self.assertIn("rng.sample",runner);self.assertIn('parser.error("--min-cluster-size must be >= 5")',runner)
        self.assertIn("ProcessPoolExecutor(max_workers=worker_count)",runner)
        self.assertIn("MCS_MAX_WORKERS = 8",runner)
        self.assertIn("rdSubstructLibrary.PatternHolder()",runner)
        self.assertIn("maxResults=len(valid)",runner)
        vector=next(x for x in clusters if x["capability_id"]=="C005")
        self.assertEqual(["description_vector_payload","canonical_description_result_in_conductor","explicit_semantics_metric_in_general"],vector["input_contract"])
        vector_runner=(SKILLS/vector["skill_name"]/"scripts"/"run.py").read_text(encoding="utf-8")
        self.assertIn("Binary Description vectors require --metric tanimoto",vector_runner)
        self.assertIn("--description-result",vector_runner);self.assertNotIn("--description-manifest",vector_runner)
        operator=(SKILLS/"cs-analysis-sali"/"scripts"/"run.py").read_text(encoding="utf-8");self.assertIn('representation == "D020"',operator);self.assertNotIn('representation == "D019" or any("embedding"',operator)

    def test_docs_and_layout_verifier(self)->None:
        docs=MODULES/"docs";self.assertFalse(any(p.suffix.lower() in {".png",".pptx"} for p in docs.rglob("*")))
        required={"CONDUCTOR_overview.md","CONDUCTOR_policy.md","CONDUCTOR_design_spec.md","CONDUCTOR_output_contract.md","CONDUCTOR_user_guide.md","CONDUCTOR_skill_catalog.md"}
        self.assertTrue(required.issubset({p.name for p in docs.iterdir() if p.is_file()}))
        result=subprocess.run([sys.executable,str(MODULES/"tools"/"verify_package_layout.py")],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)


if __name__=="__main__":unittest.main()
