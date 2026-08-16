from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/".claude"/"skills"/"cs-conductor-result-concierge"/"scripts"/"run.py"


class ConciergeTests(unittest.TestCase):
    def cli(self,*args:str,check:bool=True)->subprocess.CompletedProcess[str]:
        result=subprocess.run([sys.executable,str(SCRIPT),*args],cwd=ROOT,text=True,capture_output=True)
        if check and result.returncode:self.fail(result.stdout+result.stderr)
        return result

    def test_prepare_is_scoped_and_requires_frozen_run(self)->None:
        with tempfile.TemporaryDirectory() as folder_name:
            root=Path(folder_name)/"run";root.mkdir();state={"schema_version":"2.0.0","conductor_version":"0.1.1","run":{"run_id":"run","project":"unit"},"round_control":{"active_round_id":None,"rounds":[]},"orchestration_control":{"lease":{"owner_id":None,"expires_at":None}},"execution_graph":{"nodes":[],"edges":[]},"indices":{}}
            state_path=root/"state.json";state_path.write_text(json.dumps(state),encoding="utf-8")
            refused=self.cli("prepare","--state",str(state_path),"--request","説明","--focus-id","INS0001",check=False);self.assertNotEqual(0,refused.returncode)
            prepared=json.loads(self.cli("prepare","--state",str(state_path),"--request","INS0001を説明","--focus-id","INS0001","--explicit-request").stdout)
            request_dir=Path(prepared["request_dir"]);self.assertEqual(root/"concierge"/"CRQ000001",request_dir);self.assertTrue((request_dir/"context.json").is_file())
            self.assertEqual(state,json.loads(state_path.read_text(encoding="utf-8")))


if __name__=="__main__":unittest.main()
