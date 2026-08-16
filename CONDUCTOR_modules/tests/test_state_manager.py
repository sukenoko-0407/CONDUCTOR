from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
CLI=ROOT/".claude"/"skills"/"cs-conductor-runtime"/"scripts"/"state_manager.py"
SPEC=importlib.util.spec_from_file_location("state_runtime",CLI);STATE=importlib.util.module_from_spec(SPEC);assert SPEC and SPEC.loader;SPEC.loader.exec_module(STATE)


class RuntimeTests(unittest.TestCase):
    def cli(self,*args:str,check:bool=True)->subprocess.CompletedProcess[str]:
        result=subprocess.run([sys.executable,str(CLI),*args],cwd=ROOT,text=True,capture_output=True)
        if check and result.returncode: self.fail(result.stdout+result.stderr)
        return result

    def setup_run(self,temporary:Path)->tuple[Path,str]:
        source=temporary/"compounds.csv"
        with source.open("w",encoding="utf-8",newline="") as handle:
            writer=csv.writer(handle);writer.writerow(["compound_id","smiles","pIC50"])
            for i in range(1,13):writer.writerow([f"C{i:03d}","CCO" if i%2 else "CCN",5+i/10])
        run_root=temporary/"run"
        state_path=Path(self.cli("init","--input",str(source),"--endpoint","pIC50","--higher-is-better","--project","unit","--parallel-limit","4","--run-id","unit-run","--output-dir",str(run_root)).stdout.strip())
        bootstrap=json.loads(self.cli("bootstrap","--state",str(state_path),"--owner-id","unit-test").stdout)
        return state_path,bootstrap["lease_token"]

    def event(self,node:dict,attempt_id:str,status:str="failed",artifacts:list[dict]|None=None)->dict:
        now=datetime.now(timezone.utc).isoformat()
        return {"schema_version":"2.0.0","project":"unit","run_id":"unit-run","round_id":"RND0001","node_id":node["node_id"],"attempt_id":attempt_id,"capability_id":node["capability_id"],"skill_name":node["skill_name"],"status":status,"input_hash":"a"*64,"config_hash":"b"*64,"configuration":{},"artifacts":artifacts or [],"warnings":[],"started_at":now,"finished_at":now}

    def test_basic_plan_ids_brief_and_lease(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder))
            self.cli("plan-basic","--state",str(state_path),"--lease-token",token)
            state=json.loads(state_path.read_text(encoding="utf-8"));nodes=state["execution_graph"]["nodes"]
            self.assertEqual(18,len([n for n in nodes if n["stage"]=="description"]))
            self.assertEqual(52,len([n for n in nodes if n["stage"]=="clustering"]))
            self.assertTrue(all(len(n["node_id"])==8 for n in nodes));self.assertTrue(any(n["node_id"].startswith("NC") for n in nodes))
            brief=Path(folder)/"run"/"summaries"/"orchestrator_brief.json";self.assertLess(brief.stat().st_size,50*1024)
            value=json.loads(brief.read_text(encoding="utf-8"));self.assertIsInstance(value["required_control_action"],dict);self.assertIn("code",value["required_control_action"])
            denied=self.cli("plan-initial-global","--state",str(state_path),"--lease-token","wrong",check=False);self.assertNotEqual(0,denied.returncode)

    def test_retry_rejects_late_attempt_event(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder))
            added=json.loads(self.cli("add","--state",str(state_path),"--capability-id","A001","--reason","unit","--lease-token",token).stdout)["node"]
            first=json.loads(self.cli("start","--state",str(state_path),"--node-id",added["node_id"],"--lease-token",token).stdout)
            event_dir=Path(added["output_dir"])/"attempts"/first["attempt_id"];event_dir.mkdir(parents=True)
            event_path=event_dir/"execution_event.json";event_path.write_text(json.dumps(self.event(added,first["attempt_id"])),encoding="utf-8")
            self.cli("record","--state",str(state_path),"--event",str(event_path),"--lease-token",token)
            second=json.loads(self.cli("start","--state",str(state_path),"--node-id",added["node_id"],"--retry","--lease-token",token).stdout)
            self.assertEqual("ATT0002",second["attempt_id"])
            late=self.cli("record","--state",str(state_path),"--event",str(event_path),"--lease-token",token,check=False);self.assertNotEqual(0,late.returncode)
            node=next(n for n in json.loads(state_path.read_text(encoding="utf-8"))["execution_graph"]["nodes"] if n["node_id"]==added["node_id"])
            self.assertEqual("running",node["status"]);self.assertEqual("ATT0002",node["current_attempt_id"])

    def test_cluster_ids_are_allocated_at_commit(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder))
            node=json.loads(self.cli("add","--state",str(state_path),"--capability-id","C001","--reason","unit","--lease-token",token).stdout)["node"]
            started=json.loads(self.cli("start","--state",str(state_path),"--node-id",node["node_id"],"--lease-token",token).stdout);out=Path(node["output_dir"])/"attempts"/started["attempt_id"];out.mkdir(parents=True)
            membership=out/"cluster_membership.csv";membership.write_text("cluster_id,compound_id,membership_value,membership_reason\n"+"".join(f"LCL000001,C{i:03d},1,unit\n" for i in range(1,6)),encoding="utf-8")
            registry=out/"cluster_registry.json";registry.write_text(json.dumps([{"local_cluster_id":"LCL000001","cluster_label":"unit","compound_count":5}]),encoding="utf-8")
            artifacts=[{"type":"cluster_membership","path":membership.name,"sha256":hashlib.sha256(membership.read_bytes()).hexdigest()},{"type":"cluster_registry","path":registry.name,"sha256":hashlib.sha256(registry.read_bytes()).hexdigest()}]
            event_path=out/"execution_event.json";event_path.write_text(json.dumps(self.event(node,started["attempt_id"],"succeeded",artifacts)),encoding="utf-8")
            self.cli("record","--state",str(state_path),"--event",str(event_path),"--lease-token",token)
            state=json.loads(state_path.read_text(encoding="utf-8"));committed=next(n for n in state["execution_graph"]["nodes"] if n["node_id"]==node["node_id"])
            self.assertEqual(["CL000001"],committed["cluster_ids"]);self.assertEqual(1,state["indices"]["clusters"]["cluster_count"])
            matrix=Path(state["indices"]["clusters"]["matrix_paths"][0]).read_text(encoding="utf-8");self.assertIn("CL000001",matrix)

    def test_no_usable_clustering_is_committed_as_negative_result(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder))
            node=json.loads(self.cli("add","--state",str(state_path),"--capability-id","C001","--reason","unit","--lease-token",token).stdout)["node"]
            started=json.loads(self.cli("start","--state",str(state_path),"--node-id",node["node_id"],"--lease-token",token).stdout);out=Path(node["output_dir"])/"attempts"/started["attempt_id"];out.mkdir(parents=True)
            membership=out/"cluster_membership.csv";membership.write_text("cluster_id,compound_id,membership_value,membership_reason\n"+"".join(f",C{i:03d},0,no_usable_partition\n" for i in range(1,13)),encoding="utf-8")
            registry=out/"cluster_registry.json";registry.write_text("[]",encoding="utf-8")
            manifest=out/"clustering_manifest.json";manifest.write_text(json.dumps({"selection_status":"no_usable_partition","quality_flags":["fragmented"],"cluster_count":0,"membership_count":0,"unassigned_count":12,"natural_metric":"euclidean","details":{"selected_parameters":None}}),encoding="utf-8")
            artifacts=[
                {"type":"cluster_membership","path":membership.name,"sha256":hashlib.sha256(membership.read_bytes()).hexdigest()},
                {"type":"cluster_registry","path":registry.name,"sha256":hashlib.sha256(registry.read_bytes()).hexdigest()},
                {"type":"manifest","path":manifest.name,"sha256":hashlib.sha256(manifest.read_bytes()).hexdigest()},
            ]
            event_path=out/"execution_event.json";event_path.write_text(json.dumps(self.event(node,started["attempt_id"],"succeeded",artifacts)),encoding="utf-8")
            self.cli("record","--state",str(state_path),"--event",str(event_path),"--lease-token",token)
            state=json.loads(state_path.read_text(encoding="utf-8"));committed=next(n for n in state["execution_graph"]["nodes"] if n["node_id"]==node["node_id"])
            self.assertEqual("succeeded",committed["status"])
            self.assertEqual("no_usable_partition",committed["clustering_summary"]["selection_status"])
            self.assertEqual([],committed["cluster_ids"])
            self.assertEqual([],STATE.usable_clustering_nodes(state))

    def test_interpretation_ids_continue_across_rounds(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,_token=self.setup_run(Path(folder));state=STATE.read_json(state_path);result_ref="NA000001@ATT0001"
            STATE.write_jsonl(Path(state["indices"]["operator_results"]["path"]),[{"result_ref":result_ref,"round_id":"RND0001"}])
            state["indices"]["operator_results"]["count"]=1
            for number in (1,2):
                if number==2:
                    state["round_control"]["active_round_id"]=None;STATE.create_round(state,"next",120,10,1)
                node,_=STATE.add_node(state,STATE.catalog(),"I001",[],"human_directed",f"round {number}",{"focus":f"focus-{number}"})
                node["current_attempt_id"]="ATT0001";node["execution_attempts"]=[{"attempt_id":"ATT0001","status":"running"}];node["status"]="running"
                out=Path(node["output_dir"])/"attempts"/"ATT0001";out.mkdir(parents=True)
                context=out/"context.json";context.write_text(json.dumps({"allowed_result_refs":[result_ref]}),encoding="utf-8")
                draft=out/"draft.json";draft.write_text(json.dumps({"title":"解釈","executive_summary":"要約","coverage_note":"範囲","insights":[{"title":f"Insight {number}","observation":"数値観察。","interpretation":"探索的解釈。","attention":"watch","scope":{},"supporting_results":[result_ref],"counter_results":[],"limitations":["反証探索では不一致を確認できなかった。"]}],"next_actions":[{"title":"反証","rationale":"別の表現で確認する。","status":"open","source_insights":["TMP-INS0001"],"requested_analysis":[]}]}),encoding="utf-8")
                artifacts=[{"type":"interpretation_draft","resolved_path":str(draft),"path":draft.name,"sha256":hashlib.sha256(draft.read_bytes()).hexdigest()},{"type":"interpretation_context","resolved_path":str(context),"path":context.name,"sha256":hashlib.sha256(context.read_bytes()).hexdigest()}]
                STATE.commit_interpretation(state,node,out,artifacts)
            self.assertEqual(2,state["counters"]["insight"]);self.assertEqual(2,state["counters"]["action"])
            insights=STATE.read_jsonl(Path(state["indices"]["insights"]["path"]));actions=STATE.read_jsonl(Path(state["indices"]["next_actions"]["path"]))
            self.assertEqual(["INS0001","INS0002"],[x["insight_id"] for x in insights]);self.assertEqual(["ACT0001","ACT0002"],[x["action_id"] for x in actions])

    def test_composite_operator_results_are_indexed_without_new_nodes(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder));node=json.loads(self.cli("add","--state",str(state_path),"--capability-id","A005","--reason","survey","--lease-token",token).stdout)["node"]
            started=json.loads(self.cli("start","--state",str(state_path),"--node-id",node["node_id"],"--lease-token",token).stdout);out=Path(node["output_dir"])/"attempts"/started["attempt_id"];out.mkdir(parents=True)
            result=out/"A005_multidescription_feature_model.csv";result.write_text("cluster_id,rmse\nCL000001,0.4\n",encoding="utf-8");digest=hashlib.sha256(result.read_bytes()).hexdigest();base=f"{node['node_id']}@{started['attempt_id']}"
            def summary(ref:str,mode:str,clusters:list[str])->dict:
                return {"schema_version":"1.0.0","result_ref":ref,"node_id":node["node_id"],"attempt_id":started["attempt_id"],"operator_id":"A005","run_id":"unit-run","round_id":"RND0001","scope":{"mode":mode,"target_cluster_id":clusters[0] if clusters else None},"scope_context":{"description_node_ids":[],"clustering_node_ids":[],"cluster_ids":clusters},"sample_count":30,"endpoint":{"column":"pIC50","higher_is_better":True},"metric":"rmse","headline":"unit survey","key_metrics":{"rmse":0.4,"large_payload":list(range(100))},"limitations":["探索用途。"],"warnings":[],"source_nodes":[],"primary_artifact":{"path":result.name,"sha256":digest},"created_at":datetime.now(timezone.utc).isoformat()}
            aggregate=out/"operator_summary.json";aggregate.write_text(json.dumps(summary(base,"cluster-survey",[])),encoding="utf-8")
            collection=out/"cluster_operator_summaries.json";collection.write_text(json.dumps([summary(base+"/CL000001","within-cluster",["CL000001"])]),encoding="utf-8")
            artifacts=[{"type":"operator_result","path":result.name,"sha256":digest},{"type":"operator_summary","path":aggregate.name,"sha256":hashlib.sha256(aggregate.read_bytes()).hexdigest()},{"type":"operator_summary_collection","path":collection.name,"sha256":hashlib.sha256(collection.read_bytes()).hexdigest()}]
            event_path=out/"execution_event.json";event_path.write_text(json.dumps(self.event(node,started["attempt_id"],"succeeded",artifacts)),encoding="utf-8");self.cli("record","--state",str(state_path),"--event",str(event_path),"--lease-token",token)
            state=json.loads(state_path.read_text(encoding="utf-8"));indexed=STATE.read_jsonl(Path(state["indices"]["operator_results"]["path"]));committed=next(item for item in state["execution_graph"]["nodes"] if item["node_id"]==node["node_id"])
            self.assertEqual([base,base+"/CL000001"],committed["result_refs"]);self.assertEqual(2,len(indexed));self.assertNotIn("top_records",indexed[0]);self.assertLessEqual(len(indexed[0]["key_metrics"]),16)
            STATE.write_jsonl(Path(state["indices"]["operator_results"]["path"]),[]);state["indices"]["operator_results"]["count"]=0;counts=STATE.rebuild_indices(state);rebuilt=STATE.read_jsonl(Path(state["indices"]["operator_results"]["path"]));self.assertEqual(2,counts["operator_results"]);self.assertEqual([base,base+"/CL000001"],[item["result_ref"] for item in rebuilt])

    def test_later_operator_reuses_same_interpretation_node(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,token=self.setup_run(Path(folder));state=STATE.read_json(state_path);first,_=STATE.add_node(state,STATE.catalog(),"A001",[],"human_directed","first",{});first.update({"status":"succeeded","finished_at":"2026-01-01T00:00:00+00:00"});STATE.save(state_path,state)
            created=json.loads(self.cli("add-interpretation","--state",str(state_path),"--reason","terminal","--lease-token",token).stdout);node_id=created["node"]["node_id"]
            state=STATE.read_json(state_path);interp=next(item for item in state["execution_graph"]["nodes"] if item["node_id"]==node_id);final=Path(interp["output_dir"])/"attempts"/"ATT0001";final.mkdir(parents=True)
            for name,value in (("interpretation.json","{}"),("interpretation.md","# report"),("interpretation.html","<html></html>"),("quality_report.json",json.dumps({"status":"pass"}))):(final/name).write_text(value,encoding="utf-8")
            interp.update({"status":"succeeded","finished_at":"2026-01-02T00:00:00+00:00","final_output_dir":str(final)});second,_=STATE.add_node(state,STATE.catalog(),"A002",[],"human_directed","later",{});second.update({"status":"succeeded","finished_at":"2026-01-03T00:00:00+00:00"});STATE.save(state_path,state)
            reused=json.loads(self.cli("add-interpretation","--state",str(state_path),"--reason","refresh","--lease-token",token).stdout);self.assertEqual(node_id,reused["node"]["node_id"]);self.assertTrue(reused["reused"]);self.assertEqual("stale",reused["node"]["status"]);self.assertIn(second["node_id"],reused["node"]["dependencies"])

    def test_initial_local_projection_overlay_reuses_global_projection(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,_token=self.setup_run(Path(folder));state=STATE.read_json(state_path);caps=STATE.catalog()
            desc,_=STATE.add_node(state,caps,"D001",[],"basic_compute","unit");desc["status"]="succeeded"
            clustering,_=STATE.add_node(state,caps,"C001",[],"basic_compute","unit");clustering["status"]="succeeded"
            projection,_=STATE.add_node(state,caps,"A003",[desc["node_id"]],"initial_global","unit",{"role":"projection-fit"});projection["status"]="succeeded"
            registry=Path(state["indices"]["clusters"]["registry_path"]);STATE.write_csv(registry,["cluster_id","local_cluster_id","source_node_id","clustering_capability_id","cluster_label","compound_count","membership_path","status","created_at"],[{"cluster_id":"CL000001","local_cluster_id":"LCL000001","source_node_id":clustering["node_id"],"clustering_capability_id":"C001","cluster_label":"unit","compound_count":"5","membership_path":"unit.csv","status":"active","created_at":datetime.now(timezone.utc).isoformat()}]);state["indices"]["clusters"]["cluster_count"]=1
            planned=STATE.plan_initial_local(state);overlays=[n for n in state["execution_graph"]["nodes"] if n["node_id"] in planned and n["capability_id"]=="A003" and n["parameters"].get("role")=="cluster-overlay"]
            self.assertEqual(1,len(overlays));self.assertEqual([projection["node_id"],clustering["node_id"]],overlays[0]["dependencies"]);self.assertEqual("CL000001",overlays[0]["parameters"]["target_cluster"])

    def test_deferred_node_is_reactivated_without_allocating_a_new_id(self)->None:
        with tempfile.TemporaryDirectory() as folder:
            state_path,_token=self.setup_run(Path(folder));state=STATE.read_json(state_path);caps=STATE.catalog();node,_=STATE.add_node(state,caps,"D001",[],"basic_compute","round one")
            node["status"]="deferred";node["execution_round_id"]=None;state["round_control"]["active_round_id"]=None;STATE.create_round(state,"round two",120,10,1,2)
            resumed,reactivated=STATE.add_node(state,caps,"D001",[],"basic_compute","resume required work")
            self.assertTrue(reactivated);self.assertEqual(node["node_id"],resumed["node_id"]);self.assertEqual("RND0001",resumed["requested_round_id"]);self.assertEqual("RND0002",resumed["execution_round_id"]);self.assertEqual("pending",resumed["status"]);self.assertEqual(1,state["counters"]["description_node"])
            self.assertEqual(2,state["run"]["parallel_limit"]);self.assertEqual(2,STATE.active_round(state)["execution_control"]["parallel_limit"])
            command=STATE.command_for(state,resumed,"ATT0001");self.assertEqual("RND0002",command[command.index("--round-id")+1])


if __name__=="__main__":unittest.main()
