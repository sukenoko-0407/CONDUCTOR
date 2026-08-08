# Migration直後の安全確認プロンプト

Migrationの`apply`と`verify`が完了した後、Orchestratorによる科学解析を開始する前に使用する。Migration AgentやOrchestratorを起動せず、明示したStateを読み取り監査するためのプロンプトである。

## Full Audit

```text
cs-conductor-run-auditを使用して、次のStateをFullモードで監査してください。

state.json:
<移行先run_root>/state.json

OrchestratorやInterpreterは起動しないでください。
新規Nodeの作成、既存Nodeの実行、Stateの変更も行わないでください。

以下を明示してください。
- Migration verificationの成否
- active Round
- RND0002に所属するNodeの一覧と状態
- Interpretation Nodeの有無
- running中のNode／attemptの有無
- Orchestrator leaseの所有者と有効期限
- Interpretation gateの状態
- 監査結果のstatus、warning、error
```

監査結果は`<run_root>/audit/<timestamp>/audit.json`と`audit.md`に保存される。Stateと科学成果物は変更されない。

## DAG可視化（必要な場合）

```text
cs-conductor-state-reportを使用して、次のStateを可視化してください。

state.json:
<移行先run_root>/state.json

これは人間による明示的な可視化依頼です。
Orchestratorは起動せず、Stateを変更しないでください。
```

出力は`<run_root>/state/<timestamp>/`に保存される。

## 継続可否の目安

- Migration verificationが`pass`
- RND0002の科学Nodeが0件
- RND0002のInterpretation Nodeが0件
- `running` Nodeと未終了attemptが0件

上記を満たし、leaseだけが残っている場合は、leaseを正規に解放するか失効・監査済みtakeoverを行った後に解析を再開できる。RND0002に意図しないNodeがある場合は手作業で削除せず、Audit結果を基に補正または再Migrationを判断する。
