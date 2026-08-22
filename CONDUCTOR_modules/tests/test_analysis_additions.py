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
HAS_JSONSCHEMA=importlib.util.find_spec("jsonschema") is not None
HAS_SKLEARN=importlib.util.find_spec("sklearn") is not None


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

    @unittest.skipUnless(HAS_SKLEARN,"scikit-learn is installed by the Analysis Skill Pixi environment")
    def test_pca_general_mode_outputs_only_primary_csv(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder=Path(folder_name);endpoint,paths=self.tables(folder,24);out=folder/"pca"
            self.run_cli(SKILLS/"cs-analysis-projection-pca"/"scripts"/"run.py","--input",str(endpoint),"--description",str(paths["D001"]),"--value-semantics","dense_continuous","--metric","euclidean","--property-column","pIC50","--higher-is-better","--output-dir",str(out))
            self.assertTrue((out/"A003_projection_pca.csv").is_file());self.assertFalse((out/"operator_summary.json").exists());self.assertTrue((out/"projection.png").is_file())

    @unittest.skipUnless(HAS_JSONSCHEMA,"jsonschema is installed by the Analysis Skill Pixi environment")
    def test_projection_skills_accept_runtime_description_result(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder=Path(folder_name);metadata=folder/"result.json"
            payload=folder/"features.csv";payload.write_text("compound_id,f1,f2\nC001,1,2\nC002,2,3\n",encoding="utf-8")
            metadata.write_text(json.dumps({"document_type":"description_result","schema_version":"1.0.0","node_id":"N000001","capability_id":"D001","payload":"features.csv","row_count":2,"feature_count":2,"value_semantics":"dense_continuous","natural_metric":"euclidean","feature_columns":["f1","f2"],"quality_flags":[],"created_at":"2026-01-01T00:00:00+00:00"}),encoding="utf-8")
            for name in ("cs-analysis-projection-pca","cs-analysis-projection-umap"):
                script=SKILLS/name/"scripts"/"run.py";spec=importlib.util.spec_from_file_location(name,script);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module)
                parsed=module.description_contract(type("Args",(),{"description_result":str(metadata),"value_semantics":None,"metric":None,"conductor":True,"role":"projection-fit","description":str(payload),"evaluation_representation":"D001"})())
                self.assertEqual("1.0.0",parsed["schema_version"])

    @unittest.skipUnless(HAS_SKLEARN,"scikit-learn is installed by the Analysis Skill Pixi environment")
    def test_multidescription_model_fixed_panel_and_oof(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder=Path(folder_name);endpoint,paths=self.tables(folder,50);out=folder/"model";args=["--input",str(endpoint),"--property-column","pIC50","--higher-is-better","--output-dir",str(out),"--outer-folds","5"]
            for block,path in paths.items():args.extend(["--description",f"{block}={path}"])
            self.run_cli(SKILLS/"cs-analysis-multidescription-feature-model"/"scripts"/"run.py",*args)
            self.assertTrue((out/"A005_multidescription_feature_model.csv").is_file());self.assertTrue((out/"global_oof_predictions.csv").is_file());self.assertTrue((out/"operator_report.html").is_file())

    def test_fixed_interpretation_renderer(self)->None:
        path=ROOT/"CONDUCTOR_modules"/"tools"/"templates"/"interpretation_render.py";spec=importlib.util.spec_from_file_location("renderer",path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module)
        subject={"scope_mode":"single_cluster","cluster_ids":["C000001"],"clustering_input_kind":"vector","cluster_source_description_nodes":["N000001"],"analysis_description_nodes":["N000002"],"clustering_nodes":["N000010"],"population_count":100,"endpoint_valid_count":95,"analyzed_count":30,"excluded_count":70,"compound_set_hash":"a"*64,"cluster_overlap":None}
        card={"schema_version":"1.0.0","result_ref":"N000020@ATT0001","node_id":"N000020","round_id":"RND0001","capability_id":"A008","analysis_subject":subject,"metric":"tanimoto","headline":"局所SALI","key_metrics":{},"limitations":[],"quality_flags":[],"artifact_links":{"report":"analysis/N000020/report.html"},"created_at":"2026-01-01T00:00:00+00:00"}
        report={"schema_version":"3.0.0","run_id":"run","round_id":"RND0001","node_id":"N000021","title":"解析結果","report_header":{"project":"p","endpoint":"pIC50","higher_is_better":True,"endpoint_unit":None,"endpoint_transform":None,"completion":"complete"},"executive_summary":"C000001を対象とした局所SALI解析では、Globalとは区別された局所的な変化候補を確認した。ただし反証探索は限定的であり、現段階では機序を断定できない。","coverage_summary":"当該Roundから選択された単一ClusterのOperator Result一件を詳細確認した。未確認結果はなく、別Descriptionによる独立な確認は今後の課題である。","created_at":"2026-01-01T00:00:00+00:00","insights":[{"insight_id":"INS000001","revision":1,"title":"C000001の局所変化","observation":"C000001を対象としたSALI結果において、同一Metricで評価した局所集合内の数値変化が観察された。対象は30化合物であり、Cluster-local結果として記録された。","interpretation":"この観察はC000001に限定された局所的なLandscape変化の候補を示す。ただし独立な比較Resultがないため、別Clusterへの一般化はまだ判断できない。","attention":"active","claim_kind":"single_scope_observation","analysis_subject":subject,"supporting_results":["N000020@ATT0001"],"comparison_results":[],"counter_results":[],"limitations":["反証探索は限定的である。"],"recommended_followups":[{"title":"別表現で確認","rationale":"独立性を高める。"}],"fact_panel":{"clustering_method":"C005","cluster_source_descriptions":["N000001"],"analysis_descriptions":["N000002"],"operators":["A008"],"metrics":["tanimoto"],"result_samples":{"N000020@ATT0001":30},"key_metrics":{"N000020@ATT0001":{"private_metric_0x":987654.321}}}}],"result_catalog":[card],"review_manifest":{"schema_version":"1.0.0","round_id":"RND0001","detailed_result_refs":["N000020@ATT0001"],"aggregate_result_refs":[],"unreviewed_results":[],"scope_counts":{"single_cluster":1},"operator_counts":{"A008":1},"description_counts":{"N000002":1},"created_at":"2026-01-01T00:00:00+00:00"}}
        markdown=module.render_markdown(report);html=module.render_html(report)
        for token in ("エグゼクティブサマリー","Insight","次Roundで検討可能な方向","INS000001","C000001","Cluster-local"):self.assertIn(token,markdown+html)
        self.assertIn("個別report",html)
        self.assertNotIn("主要数値",markdown+html)
        self.assertNotIn("private_metric_0x",markdown+html)
        self.assertEqual(987654.321,report["insights"][0]["fact_panel"]["key_metrics"]["N000020@ATT0001"]["private_metric_0x"])
        self.assertEqual([],module.quality_issues(report))


if __name__=="__main__":unittest.main()
