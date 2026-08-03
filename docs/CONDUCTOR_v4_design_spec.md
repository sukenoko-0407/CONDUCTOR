# CONDUCTOR v4 設計仕様

## 1. 目的と範囲

CONDUCTOR v4は、多様な化学表現、Grouping、解析Operator、Interpretationを有向非巡回グラフとして計画・実行するClaude Code専用SAR解析基盤である。初期実装は次を対象とする。

- v1/v2で実装済みのDescription、Grouping、SAL、Group Insight機能の分割移植
- アルゴリズム単位の自己完結Claude Code Project Skill
- Catalog、run単位State、Policy、共通artifact schema
- 広く浅い探索から根拠に基づく局所深掘りへのOrchestration
- machine-readable InterpretationとMarkdown/HTMLレポート

SBDD実処理、MMP、新規化合物SMILES生成、人間フィードバック追跡は初期実装の対象外とする。SBDDについては、将来のPDB/mmCIF、SDF pose、ProLIF/IFP入力を表現する`schemas/sbdd_input.schema.json`だけを予約し、実行Skillは人間が実装・承認・Catalog収載するまで提供しない。

## 2. 基本原則

1. Claude Code Project Skillsを唯一のエージェント実行面とする。
2. 各Skillはフォルダ単位でコピーして単独利用できるよう、コード、schema、設定、`env/pixi.toml`を内包する。
3. Skill間でPythonモジュールを実行時共有しない。
4. 一般利用ではDescription、Clustering、Analysisという処理名を使う。
5. CONDUCTOR内ではDescription、Grouping、Operator、Interpretationという段階名を使う。
6. Operatorは客観的evidenceを返し、最終解釈を行わない。
7. 分子標準化、活性単位変換、pActivity変換は暗黙に行わない。
8. 1 runは1 endpointを扱い、`higher_is_better`を必須とする。
9. 高コスト計算は実行前に人間の承認を必要とする。
10. Catalog収載Skillは人間がallowlistで指定する。
11. Skillは原則algorithm単位とする。同一algorithmで入力契約、依存環境、cost class、DAG stageが同じ差分は、追跡可能なCLI parameter variantとして一つのSkillへ統合できる。

## 3. リポジトリ構成

```text
CONDUCTOR/
├── .claude/
│   ├── agents/cs-conductor-orchestrator.md
│   └── skills/<skill-name>/
│       ├── SKILL.md
│       ├── capability.json
│       ├── scripts/
│       ├── schemas/
│       └── env/pixi.toml
├── catalog/
│   ├── included_skills.json
│   └── catalog.json
├── docs/
├── schemas/
├── tests/
├── pyproject.toml                   # 開発・受入試験のみ
├── uv.lock                          # 開発・受入試験のみ
└── results/                         # Git管理外
```

旧資産はGit管理外の`Archive/v2/`に保存する。

## 4. Skill命名規約

| Stage | Pattern | 例 |
|---|---|---|
| Description | `cs-compute-description-<algorithm>` | `cs-compute-description-morgan` |
| Clustering | `cs-compute-clustering-<family>-<algorithm>` | `cs-compute-clustering-structure-murcko` |
| Operator | `cs-analysis-<algorithm>` | `cs-analysis-sali` |
| Interpretation | `cs-analysis-interpret-<purpose>` | `cs-analysis-interpret-evidence` |
| Orchestration | `cs-conductor-orchestrator` | 同左 |

Skill名は小文字英数字とハイフンのみ、64文字未満とする。

## 5. 入力契約

### 5.1 Descriptionおよびstructure Clustering

- `--input <csv>`または反復可能な`--smiles <smiles>`のどちらかを受ける。
- CSVはID列とSMILES列を自動推定できる。曖昧な場合は明示指定する。
- IDのないSMILESには`CMPD_000001`形式のrun内IDを付与する。
- 重複IDはhard errorとする。
- invalid SMILESは主結果に保持し、計算値を欠損、警告を記録する。
- 塩除去、中和、tautomer正規化、stereo正規化は行わない。

### 5.2 Operator

- 元CSV、ID列、endpoint列、`higher_is_better`を受ける。
- 必要に応じDescription artifact、Grouping membership、registryを明示入力する。
- 同じ入力CSVでもendpointが異なれば別runとする。

## 6. 出力契約

一般利用時:

```text
results/<stage>/<input_stem>/<skill_name>/<run_id>/
```

CONDUCTOR利用時:

```text
results/CONDUCTOR/<project>/<run_id>/
├── description/<skill_name>/
├── grouping/<skill_name>/
├── analysis/<skill_name>/
├── interpretation/<skill_name>/
├── events/
└── state.json
```

`--output-dir`は常に既定値より優先するが、モードを変更しない。通常モードはdefaultかつ主成果物だけを返す。CONDUCTORモードは明示的opt-inであり、`--conductor --project <project> --run-id <run_id> --node-id <node_id>`をすべて指定した場合だけ、manifest、warnings、evidenceまたはgroup registry、execution event、schema検証を追加する。通常モードでは`--project`と`--node-id`を受け付けない。

Agentはrepository名、Catalog収載、CONDUCTOR互換artifact、`results/CONDUCTOR/`形式の出力先だけを根拠にCONDUCTORモードを推測しない。ユーザーの明示依頼、OrchestratorからのDAG node実行、または既存runへの明示接続がなければ`--conductor`を省略する。意図が曖昧なら実行前に確認し、確認できなければ通常モードを選ぶ。

高次元表現はCSVを標準とし、`--format parquet`を任意で許可する。NPZはpretrained embeddingなど明確な必要性があるSkillだけで許可する。

## 7. ID体系

- Description representation: `D001`から新規附番
- Grouping capability: `C001`から新規附番
- Operator: `A001`から新規附番
- Interpretation: `I001`から新規附番
- Evidence: `<run_id>:<operator_id>:<group_id-or-global>:<sequence>`
- Group: `<clustering_id>_<sequence>`（methodはCatalogのcapability IDとregistryで参照する）

旧L01-L60、旧group ID、旧CLI、旧出力パスとの互換性は持たない。

D011（chiral Morgan）はD002の`--include-chirality`へ、D018（Gobbi Pharm2D SVD）はD017の`--reduction svd`へ統合した。既存IDを再利用して意味を変えないため、D011とD018は欠番として保持する。構造／vector clusteringのように入力契約または上流依存が異なるもの、Mordred 2D／3Dのようにcost classが異なるもの、異なる解析意味を持つOperatorは統合しない。

## 8. Catalog

各Skillの`capability.json`をmetadata源とし、`catalog/included_skills.json`に人間が列挙したSkillだけを`catalog/catalog.json`へ収載する。Markdown版Catalogは機械Catalogから生成する。自動スキャンはallowlistを変更しない。

## 9. StateとDAG

Stateはrunごとに一つのJSONとし、次を保持する。

- run metadata、endpoint、`higher_is_better`
- nodeとdependency edge
- `pending/running/succeeded/failed/skipped/stale`状態
- 入力hash、計画parameter、実行configuration、設定hash、上流artifact hash
- 出力artifact、警告、開始・終了時刻
- Orchestratorの選択理由と人間承認状態

SkillはStateを直接更新せず、実行時の`configuration`を含むexecution eventを生成する。Orchestratorのローカルscriptが実行前にnodeを`running`へ遷移させ、project/run/node/capabilityと計画parameterをeventに照合して原子的にStateへ反映する。eventなしで異常終了した場合は専用のfailure遷移へ理由を記録する。上流hashが変化した場合、下流nodeと対応するdomain/evidence graph nodeを`stale`にする。

実行DAG、group関係graph、evidence依存graphは別オブジェクトとして管理し、ID参照で接続する。

## 10. Orchestration

Orchestratorは最初に低～中コストの表現と解析を広く実行し、以下を根拠に深掘り候補を選ぶ。

- effect sizeと統計的信頼性
- 局所的不連続、activity cliff、例外
- 独立した表現またはOperatorによる支持
- sample数、局所密度、欠損率
- group重複とevidence依存性
- 未解析の組合せと期待情報利得
- 計算コストと利用可能資源

高コストSkillは必ず人間の承認を得る。並列数も人間指定値を上限とする。想定HPC資源はCPU 64 core、またはNVIDIA A100 1枚とCPU 8 coreである。

## 11. Interpretation

正本はagent-friendlyなJSONとし、観察、支持、矛盾、独立性、代替説明、scope、例外、確信度、次解析、構造設計方向、人間確認点を含む。同じ内容からMarkdownと自己完結HTMLを生成する。具体的な新規SMILES生成は行わない。

## 12. 環境

各Skillは`env/pixi.toml`を持ち、Linux x86_64とWindows x86_64を対象とする。実行時は次の順序を使う。

1. `scripts/launch.py`が共有バイナリ`/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先して選ぶ。
2. 共有バイナリが存在しないWindows等ではPATH上の`pixi`へfallbackする。どちらも無ければ停止する。
3. launcher自身の場所から`<skill>/env/pixi.toml`とrunnerの絶対パスを解決し、`pixi run --manifest-path ...`を実行する。呼出し元のworking directoryは環境選択に使わない。
4. Pixi起動前に、環境構築・実行中の全書込み先を`<skill>/env/`配下へ作成する。Pixi cacheは`env/cache/pixi/`、uv cacheは`env/cache/uv/`、一時領域は`env/tmp/`とする。
5. `PIXI_HOME`、`PIXI_CACHE_DIR`と全`PIXI_CACHE_<KIND>_DIR`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、`XDG_*`、`TMPDIR`/`TMP`/`TEMP`、使用ライブラリの主要cache変数を子processへ明示的に渡す。既存の同名環境変数よりSkill-local値を優先する。
6. `PIXI_CACHE_NETFS_REDIRECT=never`によりNFS上でもnode-local scratchへcacheを退避させない。`PIXI_NO_CONFIG=1`によりsystem/user Pixi configから外部保存先を注入させない。必要なmirror、proxy、認証はmanifestまたは実行環境変数として与える。
7. `detached-environments`が無効となる隔離構成で、環境が未作成なら`<skill>/env/.pixi/envs/default/`へ自動構築し、作成済みなら同じ環境を再利用する。
8. manifest更新に伴うlock fileは`<skill>/env/pixi.lock`に置かれる。

rootの`pyproject.toml`と`uv.lock`はrepository開発・受入試験用であり、Skillから参照しない。

## 13. 受入基準

- 全Skillのmetadata、命名、Pixi manifestを静的検証できる。
- CSVと複数SMILES入力が動作する。
- 通常モードとCONDUCTORモードが動作する。
- schema validation、State resume/stale、Catalog allowlistが動作する。
- 小規模end-to-endとJAK2回帰smoke testが成功する。
- Linux/Windows双方でパスを固定せず実行できる。
- working directory外へcache、一時file、Pixi global dataを書き込まない。
