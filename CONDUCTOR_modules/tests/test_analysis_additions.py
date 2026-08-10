from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
SKILLS=ROOT/".claude"/"skills"


class AnalysisAdditionTests(unittest.TestCase):
    def run_cli(self,script:Path,*args:str)->subprocess.CompletedProcess[str]:
        result=subprocess.run([sys.executable,str(script),*args],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr);return result

    def tables(self,folder:Path,n:int=50)->tuple[Path,dict[str,Path]]:
        endpoint=folder/"endpoint.csv"
        with endpoint.open("w",encoding="utf-8",newline="") as handle:
            writer=csv.writer(handle);writer.writerow(["compound_id","smiles","pIC50"])
            for i in range(n):writer.writerow([f"C{i:03d}","CCO",4.5+0.08*i+0.15*((i%5)-2)])
        paths={}
        for block in ("D001","D002","D006","D013","D016","D019"):
            path=folder/f"{block}.csv";paths[block]=path
            with path.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.writer(handle);writer.writerow(["compound_id",*[f"f{j}" for j in range(8)]])
                for i in range(n):
                    values=[(i+j)%2 for j in range(8)] if block=="D002" else [max(0,(i*(j+1))%17) for j in range(8)] if block=="D006" else [i/(j+2)+(i%3)*0.1 for j in range(8)]
                    writer.writerow([f"C{i:03d}",*values])
        return endpoint,paths

    def test_pca_general_mode_outputs_only_primary_csv(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder=Path(folder_name);endpoint,paths=self.tables(folder,24);manifest=folder/"manifest.json";manifest.write_text(json.dumps({"value_semantics":"dense_continuous","natural_metric":"euclidean"}),encoding="utf-8");out=folder/"pca"
            self.run_cli(SKILLS/"cs-analysis-projection-pca"/"scripts"/"run.py","--input",str(endpoint),"--description",str(paths["D001"]),"--description-manifest",str(manifest),"--property-column","pIC50","--higher-is-better","--output-dir",str(out))
            self.assertTrue((out/"A003_projection_pca.csv").is_file());self.assertFalse((out/"operator_summary.json").exists());self.assertTrue((out/"projection.png").is_file())

    def test_multidescription_model_fixed_panel_and_oof(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder=Path(folder_name);endpoint,paths=self.tables(folder,50);out=folder/"model";args=["--input",str(endpoint),"--property-column","pIC50","--higher-is-better","--output-dir",str(out),"--outer-folds","5"]
            for block,path in paths.items():args.extend(["--description",f"{block}={path}"])
            self.run_cli(SKILLS/"cs-analysis-multidescription-feature-model"/"scripts"/"run.py",*args)
            self.assertTrue((out/"A005_multidescription_feature_model.csv").is_file());self.assertTrue((out/"global_oof_predictions.csv").is_file());self.assertTrue((out/"operator_report.html").is_file())

    def test_fixed_interpretation_renderer(self)->None:
        path=ROOT/"CONDUCTOR_modules"/"tools"/"templates"/"interpretation_render.py";spec=importlib.util.spec_from_file_location("renderer",path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module)
        report={"schema_version":"2.0.0","run_id":"run","round_id":"RND0001","node_id":"NI000001","attempt_id":"ATT0001","title":"解析結果","executive_summary":"要約","coverage_note":"範囲","created_at":"2026-01-01T00:00:00+00:00","insights":[{"insight_id":"INS0001","revision":1,"title":"局所変化","observation":"GlobalとClusterで数値が変化した。","interpretation":"局所性の候補。","attention":"priority","scope":{"target_cluster_id":"CL000001"},"supporting_results":["NA000001@ATT0001/CL000001"],"counter_results":[],"limitations":["反証探索の範囲内では明確な不一致を確認できなかった。"]}],"next_actions":[{"action_id":"ACT0001","revision":1,"title":"反証","rationale":"別の表現で確認する。","status":"open","source_insights":["INS0001"],"requested_analysis":[]}],"result_catalog":[{"result_ref":"NA000001@ATT0001/CL000001","operator_id":"A008","scope":{"mode":"within-cluster"},"scope_context":{"description_node_ids":["ND000001"],"cluster_ids":["CL000001"]},"sample_count":30,"metric":"tanimoto","headline":"局所SALI","artifact_path":"result.csv","operator_report_path":"operator_report.html","summary_artifact_path":"operator_summary.json"}]}
        markdown=module.render_markdown(report);html=module.render_html(report);quality=module.render_quality(report)
        for token in ("エグゼクティブサマリー","Insight","次の解析候補","INS0001","ACT0001"):self.assertIn(token,markdown+html)
        self.assertIn("個別HTML report",html);self.assertIn("局所SALI",html)
        self.assertEqual("pass",quality["status"])


if __name__=="__main__":unittest.main()
