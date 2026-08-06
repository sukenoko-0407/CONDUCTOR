# CONDUCTOR v4 設計仕様

## 1. 目的と範囲

CONDUCTOR v4は、多様な化学表現、Grouping、解析Operator、Interpretationを有向非巡回グラフとして計画・実行するClaude Code専用SAR解析基盤である。初期実装は次を対象とする。

- v1/v2で実装済みのDescription、Grouping、SAL、Group Insight機能の分割移植
- アルゴリズム単位の自己完結Claude Code Project Skill
- Catalog、run単位State、Policy、共通artifact schema
- 広く浅い探索から根拠に基づく局所深掘りへのOrchestration
- machine-readable InterpretationとMarkdown/HTMLレポート

SBDD実処理、MMP、新規化合物SMILES生成、人間フィードバック追跡は初期実装の対象外とする。SBDDについては、将来のPDB/mmCIF、SDF pose、ProLIF/IFP入力を表現する`CONDUCTOR_modules/schemas/sbdd_input.schema.json`だけを予約し、実行Skillは人間が実装・承認・Catalog収載するまで提供しない。

## 2. 基本原則

1. Claude Code Project Skillsを唯一のエージェント実行面とする。
2. 各Skillはフォルダ単位でコピーして単独利用できるよう、コード、schema、設定、`env/pixi.toml`を内包する。
3. Skill間でPythonモジュールを実行時共有しない。
4. 一般利用ではDescription、Clustering、Analysisという処理名を使う。
5. CONDUCTOR内ではDescription、Grouping、Operator、Interpretationという段階名を使う。
6. Operatorは客観的evidenceを返し、最終解釈を行わない。
7. 分子標準化、活性単位変換、pActivity変換は暗黙に行わない。
8. 1 runは1 endpointを扱い、`higher_is_better`を必須とする。
9. 高コスト計算は原則として実行前に人間の承認を必要とする。人間管理Catalogで`preauthorized_initial`とされたC002 MCSは必須初手として例外とする。
10. Catalog収載Skillは人間がallowlistで指定する。
11. Skillは原則algorithm単位とする。同一algorithmで入力契約、依存環境、cost class、DAG stageが同じ差分は、追跡可能なCLI parameter variantとして一つのSkillへ統合できる。
12. 初手は狭い最小計算ではなく、Description、Grouping、Operatorの代表情報軸を網羅する`representative-family-wide-v1` profileとする。3D Descriptionを必ず一種類含める。

## 3. リポジトリ構成

```text
<project-dir>/
├── .claude/
│   ├── agents/
│   │   ├── cs-conductor-orchestrator.md
│   │   └── cs-conductor-interpreter.md
│   └── skills/<skill-name>/
│       ├── SKILL.md
│       ├── capability.json
│       ├── scripts/
│       ├── schemas/
│       └── env/pixi.toml
├── CONDUCTOR_modules/
│   ├── catalog/
│   │   ├── included_skills.json
│   │   └── catalog.json
│   ├── docs/
│   ├── schemas/                     # Skill生成・保守用の正本
│   ├── tools/
│   ├── tests/
│   ├── pyproject.toml               # 開発・受入試験のみ
│   └── uv.lock                      # 開発・受入試験のみ
└── results/                         # Git管理外
```

Claude Codeの発見対象である`.claude/agents/`と`.claude/skills/`だけをProject直下へ置く。CONDUCTOR固有の管理・文書・保守資産は`CONDUCTOR_modules/`へ集約する。旧資産はGit管理外の`CONDUCTOR_modules/Archive/`に保存する。

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

### 5.1 Description

- `--input <csv>`または反復可能な`--smiles <smiles>`のどちらかを受ける。
- CSVはID列とSMILES列を自動推定できる。曖昧な場合は明示指定する。
- IDのないSMILESには`CMPD_000001`形式のrun内IDを付与する。
- 重複IDはhard errorとする。
- invalid SMILESは主結果に保持し、計算値を欠損、警告を記録する。
- 塩除去、中和、tautomer正規化、stereo正規化は行わない。

### 5.2 Direct structure Grouping

- 一般利用・CONDUCTOR利用とも、compound ID列とSMILES列を含むCSVを`--input <csv>`へ必ず指定する。
- inlineの`--smiles`と`--compound-id`は受け付けない。複数化合物の集合を分類し、入力集合とID対応を監査できることを優先する。
- ID列とSMILES列は自動推定できる。曖昧な場合は`--id-column`と`--smiles-column`で明示する。
- duplicate IDはhard errorとする。invalid SMILESは未割当として保持して警告を記録する。
- 塩除去、中和、tautomer正規化、stereo正規化は行わない。
- Murcko、MCS、BRICS、RECAPに限定し、CSV内のSMILESを宣言された構造規則で直接処理する。Morgan等のfingerprintを内部生成してButina、DBSCAN、graph clusteringへ渡す処理は含めない。

### 5.3 Description-vector Clustering

- compound IDと数値featureを持つDescription SkillのCSV artifactを`--input`で受ける。
- raw SMILESおよび反復可能な`--smiles`は受け付けず、descriptorやfingerprintを内部生成しない。
- CONDUCTORではStateの`input_bindings.description`で生成元Description nodeを一つ明示する。
- `--metric auto`を既定とし、Descriptionの表現種別と実VectorからMetricを決定する。binaryおよびMorganはTanimoto、USR/USRCATはManhattan、疎な非負countはCosine、embedding/SVDはCosine、その他の連続値は標準化Euclideanを使う。binaryまたは既知のbit fingerprintへTanimoto以外を明示した場合はerrorとする。
- 異なるcompound IDが同一Vectorを持つことは許容する。近傍解析では自己行だけを除外し、距離0の別化合物は正当な近傍として保持する。
- invalid SMILESまたはDescription値がない行はclusterへ代入せず、主結果に未割当として保持する。

### 5.4 Operator

- 元CSV、ID列、endpoint列、`higher_is_better`を受ける。
- 必要に応じDescription artifact、Grouping membership、registryを明示入力する。
- 同じ入力CSVでもendpointが異なれば別runとする。
- 全Operatorはscope metadataをevidenceへ残す。A003、A005、A006、A007は`global`、`within-group`、`between-groups`、A004はglobalとwithin-groupに対応する。
- 局所解析はGrouping membershipとtarget Groupを明示し、連続Descriptionの比較ではglobal referenceでfitした前処理を既定とする。

## 6. 出力契約

一般利用時:

```text
results/<stage>/<input_stem>/<skill_name>/<run_id>/
```

CONDUCTOR利用時:

```text
results/CONDUCTOR/<project>/<run_id>/
├── description/<skill_name>/<node_id_safe>/
├── grouping/<skill_name>/<node_id_safe>/
├── analysis/<skill_name>/<node_id_safe>/
├── interpretation/<skill_name>/<node_id_safe>/
├── events/
└── state.json
```

`node_id_safe`は通常の段階別Node IDと同一である。既存Stateの旧形式IDに`:`が含まれる場合だけWindows互換のため`-`へ置換する。`--output-dir`は常に既定値より優先するが、モードを変更しない。通常モードはdefaultかつ主成果物だけを返す。CONDUCTORモードは明示的opt-inであり、`--conductor --project <project> --run-id <run_id> --node-id <node_id>`をすべて指定した場合だけ、manifest、warnings、evidenceまたはgroup registry、execution event、schema検証を追加する。通常モードでは`--project`と`--node-id`を受け付けない。

Agentはrepository名、Catalog収載、CONDUCTOR互換artifact、`results/CONDUCTOR/`形式の出力先だけを根拠にCONDUCTORモードを推測しない。ユーザーの明示依頼、OrchestratorからのDAG node実行、または既存runへの明示接続がなければ`--conductor`を省略する。意図が曖昧なら実行前に確認し、確認できなければ通常モードを選ぶ。

高次元表現はCSVを標準とし、`--format parquet`を任意で許可する。NPZはpretrained embeddingなど明確な必要性があるSkillだけで許可する。

## 7. ID体系

CatalogのCapability IDは「何を実行するか」を表す。

- Description representation capability: `D001`から新規附番
- Grouping capability: `C001`から新規附番
- Operator capability: `A001`から新規附番
- Interpretation capability: `I001`

StateのExecution Node IDは「このrunで何回目の実行か」を表し、Capability IDとは独立に段階別連番とする。

- Description node: `D001`, `D002`, ...
- Grouping node: `G001`, `G002`, ...
- Operator node: `O001`, `O002`, ...
- Interpretation node: `I001`, `I002`, ...

例えばCapability `I001`を3回実行した場合、Node IDは`I001`、`I002`、`I003`となる。旧形式`<capability-id>:<sequence>`を持つ既存Stateは読み取りと継続を許可するが、新規Nodeには使用しない。

- Evidence: `<run_id>:<operator_id>:<node-or-scope-context>:<sequence>`
- Group: `G_<source-node-id-safe>_<group-content-hash16>`。hashはGroupラベルとmember集合から決め、再計算で内容が同じGroupは同じID、内容が変わったGroupは新しいIDとする。methodはCatalogのcapability IDとregistryで参照する。

旧L01-L60、旧group ID、旧CLI、旧出力パスとの互換性は持たない。

D011（chiral Morgan）はD002の`--include-chirality`へ、D018（Gobbi Pharm2D SVD）はD017の`--reduction svd`へ統合した。既存IDを再利用して意味を変えないため、D011とD018は欠番として保持する。direct structure GroupingとDescription-vector Clusteringは入力契約と責務が異なるため統合しない。一方、SMILESからMorgan fingerprintを内部生成してvector algorithmへ渡していた旧`structure-butina`等の6ラッパーは責務が重複するためCatalogから除外し、現行C005～C010はDescription artifact入力のvector algorithmへ連番で割り当てる。

## 8. Catalog

各Skillの`capability.json`をmetadata源とし、`CONDUCTOR_modules/catalog/included_skills.json`に人間が列挙したSkillだけを`CONDUCTOR_modules/catalog/catalog.json`へ収載する。Markdown版Catalogは機械Catalogから生成する。自動スキャンはallowlistを変更しない。

初手profileへの参加は`default_wide_shallow`、担当軸は`wide_shallow_axis`、上流の限定組合せは`wide_shallow_sources`で宣言する。source固有parameterは`wide_shallow_parameter_overrides`で宣言し、例えば同じOperatorでもbinary fingerprintへTanimoto、USR/USRCATへManhattanを割り当てる。依存を持つ初手capabilityはsourceを明示し、Catalog builderはsourceの存在、stage、初手profile参加、parameter overrideの参照整合性を検証する。`*`は初手で計画された当該stageの全nodeを意味する。

## 9. StateとDAG

Stateはrunごとに一つのJSONとし、次を保持する。

- run metadata、endpoint、`higher_is_better`
- nodeとdependency edge
- `pending/running/succeeded/failed/skipped/stale`状態
- 入力hash、計画parameter、実行configuration、設定hash、上流artifact hash
- 出力artifact、警告、開始・終了時刻
- Orchestratorの選択理由と人間承認状態
- `wide_shallow/deep_dive/human_directed` phase、request origin、選択理由、coverage axis、上流artifact binding、node固有output directory
- `interpretation_exploration` phase、Policy version、人間設定budget、seed、iteration、request ledger、analysis signature

SkillはStateを直接更新せず、実行時の`configuration`を含むexecution eventを生成する。Orchestratorのローカルscriptが実行前にnodeを`running`へ遷移させ、project/run/node/capabilityと計画parameterをeventに照合して原子的にStateへ反映する。eventなしで異常終了した場合は専用のfailure遷移へ理由を記録する。上流nodeが失敗または承認拒否で実行不能になった場合、そのnodeだけに依存する未開始下流nodeを理由付き`skipped`へ伝播する。上流hashが変化した場合、下流nodeと対応するdomain/evidence graph nodeを`stale`にする。

実行DAG、group関係graph、evidence依存graphは別オブジェクトとして管理し、ID参照で接続する。同じcapability、上流node、科学的parameterからanalysis signatureを作り、Description、Grouping、Operatorの同一解析を再登録しない。Interpretationは同じ固定Evidenceを異なる人間指示や新しい比較視点で再解釈できるため、各`I###` roundと前回Interpretation lineageをsignatureへ含める。

## 10. Orchestration

Orchestratorは最初に`representative-family-wide-v1`をDAGへ展開する。現profileはDescription 7 node、Grouping 9 node、Operator 36 nodeの計52 nodeを基本とし、assay条件が複数ならcategorical Groupingと対応Operatorを追加する。Descriptionには2D物性、circular graph、substructure、atom pair、path、2D pharmacophore、3D shape/pharmacophoreを含む。GroupingはSMILES直接型としてMurcko、事前許可済み必須初手MCS、BRICSを、Description-vector型としてButina、hierarchical、DBSCAN、Leidenを含む。vector ClusteringはD001、D002、D013、D017のうちCatalogで宣言されたartifactへ個別bindingする。Operatorは全10種を、意味のある上流sourceだけに接続する。A009は重複所属が重要なC002 MCSとC003 BRICSの双方へ接続する。

初手はヒント発見のための網羅passであり、一部nodeで信号が弱いことを理由に残りを打ち切らない。Stateは`wide_shallow` nodeを`deep_dive`より優先し、初手がterminalになるまでInterpretationの開始を拒否する。coverage auditで必須軸の成功、失敗、代替、skip理由を確認してから、以下を根拠に深掘り候補を選ぶ。

- effect sizeと統計的信頼性
- 局所的不連続、activity cliff、例外
- 独立した表現またはOperatorによる支持
- sample数、局所密度、欠損率
- group重複とevidence依存性
- 未解析の組合せと期待情報利得
- 計算コストと利用可能資源

高コストSkillは原則として人間の承認を得る。Catalogで`approval_policy=preauthorized_initial`とされたC002 MCSだけはrunごとの承認を求めず、初手から実行する。並列数は人間指定値を上限とする。想定HPC資源はCPU 64 core、またはNVIDIA A100 1枚とCPU 8 coreである。

## 11. Interpretation

Interpretationは`CONDUCTOR_modules/docs/CONDUCTOR_v4_interpretation_policy.md`に従う専用Claude Code Agentが担当する。Capability I001のrunnerはevidence index、Group候補、provenance、関係候補、失敗、skip、探索ledgerを`interpretation_context.json`へ機械的に整理し、`draft`として明示する。Agentはartifactを多面的に比較してObservationとInterpretationを分離し、人間向け要約、注目理由、制約、矛盾評価、必要な場合だけ検証可能なHypothesisを記載する。品質gateを通過した`agent_interpreted` reportだけを正式成果物とする。

Interpretation nodeはStateを変更しない読み取り専用の終端nodeとする。追加計算は`exploration_plan.json`としてOrchestratorへ返し、Orchestratorだけが人間設定budget、並列上限、Orchestrator指定bounds、重複analysis signature、反証要求、costとapprovalを検証して、新しいDescription–Grouping–Operator branchを作る。そのbranchは別のInterpretation nodeで終える。既存Groupingにない切り出しはPlanにcompound ID集合を持たせ、登録時にrun inputと照合したcontent-addressed membershipへ固定する。

人間が部分的なDescription、Grouping、Operator、Interpretationを指定した場合も、Skillを直接実行せず、Orchestratorが`human_directed` nodeとしてStateへ登録する。上流node、artifact binding、parameter、理由、承認、実行eventは通常nodeと同じ規則で管理する。Interpretation再実行は新しい`I###` nodeを作り、前回`I###`のreportを実行依存edgeではなくread-only lineageとして渡す。

多重探索による発見候補を抑制せず、DiscoveryとValidation、negative result、矛盾、未実行候補、全試行履歴を保持する。一つの整合的仮説へ収束させない。各discoveryには反証、control、または独立replicationを必ず要求する。

正本JSONは観察、evidence relation、依存性、代替説明、scope、例外、反証状態、確信度、探索履歴、次解析意図、人間確認点を含む。同じ内容からMarkdownと自己完結HTMLを生成する。具体的な新規SMILES生成は行わない。

## 11.1 Orchestratorの二段階状態認識

Stateは軽量な制御面とし、node status、依存関係、初手coverage、approval、探索budget、Group件数だけを常時読む。化合物ごとのGroup所属と詳細provenanceはrun共通のGroup indexへ分離し、局所解析の選択時だけ参照する。

Group indexは横持ちBoolean CSVとprovenance CSVから構成する。Group IDは生成nodeを含む一意IDとし、複数Descriptionから同じClustering Capabilityを実行しても衝突させない。Interpretationが作るrandom、intersection、difference、boundary scopeも同じGroup indexへ登録する。

Orchestratorは全解析空間を完全に記憶する必要はない。粗い状態から次の領域を選び、必要なGroup行・列とevidenceだけを読む。十分に深掘りして情報価値が低い領域は理由付き`discarded`として自動選択対象から外すが、監査可能性のためmembershipと履歴は保持する。

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
