# CONDUCTOR 0.1.10 追補修正計画書

Status: **実装完了。2026-09-06協議内容を反映し、contract testで検証済み。**

## 1. 目的

0.1.10の基本仕様と既存Runの互換性を維持しながら、判定契約、Runtime入出力、Series採否、定型Report、補助文書を修正する。本書は既存の`CONDUCTOR_0.1.10_implementation_plan.md`に対する追補であり、過去の実装記録を置き換えない。

今回の変更では、科学計算の追加を目的にしない。明示された不整合を解消し、承認済みのSeries評価方法を実装し、Templateから生成されるReportの再現性を高める。

## 2. 対象範囲と非対象

### 対象

1. A003の正式判定と出力契約
2. Description `calculation_version`の必須化
3. Runtime関連JSON Schemaと実装の整合
4. Series member support分類と新しいSeries採否条件
5. Report Templateへの忠実性、link監査、件数監査
6. ID、検証手順、README等の文書不整合
7. 日常／特別対応promptの補強

### 非対象

- A006のN×N計算方式は変更しない。通常2,000化合物未満、Linux HPC利用を前提とし、実害が確認された場合に再検討する。
- Description計算scriptのhashをcache signatureへ追加しない。
- A008 MMPの追加改修は行わない。2 Mode化、Global Top 1、Transformation evidence、1/2-cut、情報抽出、Interactive visualizationは0.1.11へ移管する。
- Runtime Supervisor、Endpoint選抜安定性、A005予測安定性、共通runner再編は0.1.12へ引き継ぐ。
- LLM Vision、Screenshot比較、AIによるReport外観評価は導入しない。

### 現行契約と実装対象の優先順位

2026-09-06以降の0.1.10残作業では、本書と更新後の`CONDUCTOR_0.1.10_specification_overview.md`を現行契約とする。`CONDUCTOR_0.1.10_implementation_plan.md`の実装結果節は初回baselineの履歴であり、本書と異なる旧Series採否条件を新規実装の根拠にしない。

主な変更先を次に固定する。実装中に同等copyが見つかった場合はcanonical側を先に変更し、package同期手順でcopyへ反映する。

- A003: `.claude/skills/cs-analysis-series-descriptor-contrast/`
- C012: `CONDUCTOR_modules/tools/templates/series_batch_runner.py`と`.claude/skills/cs-compute-clustering-meta-overlap/`
- A009: `CONDUCTOR_modules/tools/templates/series_batch_runner.py`、`standard_summary_template.html`、`series_detail_template.html`と`.claude/skills/cs-analysis-series-report/`
- Runtime／Schema: `CONDUCTOR_modules/tools/runtime_controller.py`、`CONDUCTOR_modules/schemas/`、`.claude/skills/cs-conductor-runtime/`
- Description version検証: 全Description `capability.json`、catalog、`CONDUCTOR_modules/tools/verify_package_layout.py`
- Test: `CONDUCTOR_modules/tests/`のunit、contract、integration、renderer fixture
- 文書／Prompt: `CONDUCTOR_modules/docs/`と`.claude/skills/cs-compute-clustering-meta-overlap/README.md`

0.1.10残作業では`.claude/skills/cs-analysis-matched-molecular-pairs/`を変更対象にしない。既存の未commit変更がある場合も、本計画の実装変更と混ぜず別途扱う。

## 3. Phase 0: baseline固定

### 作業

1. 現在のGit revision、Version、working tree状態を記録する。
2. package layout verification、catalog check、全unit／contract testを実行する。
3. 現在の代表Report fixtureを、変更前比較用として特定する。
4. 既存0.1.10 Run Artifactを変更対象外とし、新規生成物だけへ新契約を適用する。

### 完了条件

- 修正前のtest件数と結果を記録している。
- 変更後に比較するA003、C012、A009 fixtureが決まっている。

## 4. Phase 1: A003判定契約の修正

### 4.1 正式判定

A003の正式通過判定を`correlation_hit`だけに統一する。

```text
criteria_pass = correlation_hit
```

判定条件は次とする。

- `|Pearson r| >= 0.60`または`|Spearman r| >= 0.60`
- 対応するGlobal絶対相関との差が`>= 0.20`
- 対応する相関のBH qが`<= 0.05`

### 4.2 Median shift削除

A003からMedian shift関連の計算、判定、出力、説明を削除する。少なくとも次を対象とする。

- `median_shift`
- `median_shift_global_iqr`
- `shift_pvalue`
- `shift_q_bh`
- `shift_hit`
- Median shiftを使用するnear-miss score／sort条件
- A003 summary内のMedian shift parameterとcriteria

### 4.3 名称変更

- `strict_hit`を`criteria_pass`へ変更する。
- A003 CSV、summary JSON、A009 reader、Report renderer、test fixtureを同時に更新する。
- 旧`strict_hit`互換列は残さない。

### 4.4 Sample N

`sample_count`はanalysis unitの総所属数ではなく、各featureについてEndpointとfeature値の両方が有限なpair数とする。Pearson、Spearman、p値を実際に計算したNと一致させる。

### Test

- 相関条件通過／不通過の境界値
- Median shiftだけが大きいcaseが通過しないこと
- feature欠損によりfeature別Nが異なるcase
- `strict_hit`とMedian shift列がcanonical CSV／HTMLに残っていないこと
- A009の通過件数が`criteria_pass`と一致すること

## 5. Phase 2: Description calculation_version契約

### 作業

1. 全Description Capabilityで`calculation_version`を必須とする。
2. Runtime／Database helperの未指定時`"1"` fallbackを廃止し、欠落時は計算開始前にfail-fastする。
3. Package verifierで、全Description Capabilityに許容形式の`calculation_version`があることを検証する。
4. calculation signatureは、明示Version、parameter、環境lockfile、model識別情報等の現行構成を維持する。script hashは追加しない。
5. Version不一致recordは削除せず、cache missとして新Versionを計算・登録する。
6. 更新規則は`CONDUCTOR_calculation_version_policy.md`を正式文書とする。

### Test

- `calculation_version`欠落Capabilityをpackage verificationとRuntimeの両方が拒否する。
- Version一致ではcache hit、Version不一致ではcache missになる。
- Reportだけの変更ではcalculation versionを変更せずcacheを再利用できる。

## 6. Phase 3: JSON Schema hardening

### 6.1 方針

Runtimeが実際に依存するcore fieldを厳格化し、Capability固有parameterや拡張metadataは必要な範囲で開いたままにする。Schemaが受理する形式とRuntime／Full Auditが受理する形式を一致させる。

### 6.2 Schema修正

1. `node_id`、`round_id`、dependency IDへ`type: string`とpatternを指定する。
2. Artifact manifestとexecution eventの`artifacts`を、1件以上のarrayへ統一する。
3. Artifact itemへ`path`、`sha256`等の必須field、型、hash patternを定義する。
4. Execution Request／eventのidentity主要項目に型とpatternを定義する。
5. Nodeの`dependencies`、`attempts`、`status`をRuntimeが生成・参照する実形式へ合わせる。
6. control、DAG、eventのtimestamp、revision、Version fieldを実装と一致させる。
7. `additionalProperties: false`を全階層へ一律適用しない。Runtime制御fieldは厳格化し、Capability固有`parameters`等は拡張可能にする。

### 6.3 Runtime validation境界

次の境界で共通Schema validatorを使用する。

1. control／DAG読込直後
2. SkillへExecution Requestを渡す直前
3. Skill execution event／Artifact manifest受理時
4. Nodeを`succeeded`へ確定する直前

失敗時は`SCHEMA_VALIDATION_FAILED`として、file、JSON path、reasonを返し、不正Nodeを実行または成功登録しない。

### 6.4 互換性

- 現行Runtimeが生成した正常な0.1.10 State／eventが新Schemaを通過することをfixtureで確認する。
- これまでRuntimeが受理していない不正形式をSchemaから除外する修正は、Artifact schema versionを不用意に変更しない。
- 正常な既存Runのread-only auditに影響する場合は、実装前に互換readerの要否を判断する。

### Negative test

- 数値Node ID
- pattern不一致Round ID
- object形式または空arrayの`artifacts`
- path／SHA256欠落Artifact
- 不正status／attempt
- identity不一致
- control／DAG revision不一致
- Schema不正eventを`succeeded`として登録しないこと

## 7. Phase 4: Series support分類と採否条件

### 7.1 Leiden graph

現行のgraph構築とweighted Leidenは変更しない。

- 1化合物以上のoverlapでedgeを形成する。
- edge weightはJaccardとする。
- resolution探索と人間gateは現行契約を維持する。
- edge形成閾値は導入しない。

### 7.2 Member分類

Candidate Series内のSelected Clusterを対象として、各化合物を排他的に分類する。

```text
Series
├─ Supported Core
│  ├─ Cross-representation Core
│  └─ Core
└─ Fringe
```

- `Cross-representation Core`: 2種類以上のrepresentationから支持される化合物
- `Core`: 同一representation内の2種類以上のClustering手法から支持される化合物
- `Fringe`: Selected Cluster 1件だけから支持される化合物

Representation keyは次の規則で決める。

- Vector clusteringはDescription IDをrepresentation keyとする。
- C001 Murcko、C002 MCS、C003 BRICS、C004 RECAP等の構造由来Clusterは、それぞれの構造分類Capabilityをrepresentation keyとする。
- 複数representationに該当した化合物はCross-representation Coreだけへ分類し、Coreへ重複計上しない。

判定時は`compound_id × source Cluster ID`を一意化し、同じmembershipを重複してsupportへ数えない。各化合物について次を保存する。

- `support_cluster_count`: 支持する一意なSelected Cluster数
- `support_representation_count`: 支持する一意なrepresentation数
- `support_representation_keys`: 支持representation keyの決定的sort済み一覧
- `member_class`: `cross_representation_core`、`core`、`fringe`のいずれか

`Supported Core`はCross-representation CoreとCoreの重複なし和集合とする。3分類は排他的かつ網羅的で、3分類のcompound count合計はCandidate SeriesのUnion compound countと一致しなければならない。

### 7.3 FFと件数

各集合`G`について、次の共通規則で件数とFFを計算する。

```text
Endpoint-valid N(G) = finiteなEndpointを持つ化合物数
Favorable N(G) = Endpoint-validかつFavorable cutoffを満たす化合物数
FF(G) = Favorable N(G) / Endpoint-valid N(G)
```

Endpoint-valid Nが0の場合、FFは`null`とし、採否条件を満たさない。`higher_is_better`に応じた既存のFavorable方向を維持する。

各Candidate Seriesについて、少なくとも次を保存する。

- Cross-representation Core compound count／Endpoint-valid N／FF
- Core compound count／Endpoint-valid N／FF
- Supported Core compound count／Endpoint-valid N／FF
- Fringe compound count／Endpoint-valid N／FF／Union内compound fraction
- Union compound count／Endpoint-valid N／FF
- Supported Core coverage = Supported Core compound count / Union compound count
- representation数とsource Cluster数

Cross-representation Core、Core、Fringeの3種類のFFはReport用の層別統計とする。Supported Core FFとUnion FFはSeries採否にも使用する。

#### Canonical Artifact追加契約

`compound_series_support.csv`には少なくとも次を追加する。

- `candidate_series_id`、`compound_id`
- `support_cluster_count`、`support_representation_count`、`support_representation_keys_json`
- `member_class`、`endpoint_valid`、`favorable`

`series_registry.csv`と`series_summary.json`には、接頭辞`cross_representation_core`、`core`、`fringe`、`supported_core`、`union`ごとに`*_compound_count`、`*_endpoint_valid_n`、`*_favorable_n`、`*_ff`を保存する。加えて`fringe_union_fraction`、`supported_core_coverage`、`source_cluster_count`、`representation_count`、`acceptance_mode`を保存する。

`support_representation_keys_json`はsort済み文字列arrayのJSONとする。`acceptance_mode`は`standard`、`supported_core_rescue`、`rejected`のいずれかとする。両方の通過条件を満たす場合は`standard`を優先する。採用Seriesの`analysis_unit_membership.csv`にはUnion全化合物と`series_member_class`を引き継ぐ。fallback Clusterでは`series_member_class=not_applicable`とする。`analysis_unit_registry.csv`には`series_acceptance_mode`を追加し、fallback Clusterでは`not_applicable`とする。

### 7.4 Series採否

従来のmulti-Cluster一律`Union FF >= 0.40`を撤廃する。

#### Standard acceptance

```text
Union FF >= 0.50
```

#### Supported Core rescue

```text
Union FF >= 0.30
AND Supported Core Endpoint-valid N >= min_ff_evaluate
AND Supported Core FF >= 0.50
```

救済通過時もFringeを除外せず、Union全体をanalysis unitとする。

#### Rejection

いずれも満たさないCandidate Seriesは棄却し、source Clusterを現行どおりfallback analysis unitへ戻す。

### 7.5 下流利用

- A009個別ReportとPCA／UMAPでCross-representation Core、Core、Fringeを色分けする。
- A009全体でStandard accepted、Supported Core rescue、Rejected、fallbackを区別する。
- A007 structural signatureでもSupported Coreを優先しない。
- A003–A007は、採用されたUnion全体をanalysis unitとして扱う。
- A008は0.1.10で追加改修せず、現行の入力・Target選択・Report契約を維持する。

A009全体のCandidate Series Tableは、Candidate ID、source Cluster数、Union N／FF、Supported Core Endpoint-valid N／FF、acceptance mode、最終analysis unitをcompact列として示す。Cross-representation Core、Core、Fringeの各N／FFは同Table直下の折り畳み詳細または個別Reportで示す。

A009個別Series Reportでは3分類のN／FFを示し、PCA／UMAPおよびmembership表示をCross-representation Core=`#c2185b`、Core=`#ff7f0e`、Fringe=`#7f7f7f`の固定3色と凡例で区別する。Global背景点は`#d9d9d9`とする。該当classが0件でもclassの意味は凡例または説明に残す。fallback Cluster Reportは従来の単一analysis unit表示を維持し、Series member classによる色分けを行わない。

### 7.6 Parameter探索との接続

Session内Matrixのcell形式`final unit数 / Cluster coverage / Compound coverage / fallback数`は変更しない。各configurationのRuntime内部decision stateには、Standard accepted数、Supported Core rescue数、Rejected Series数、fallback Cluster数を追加する。

既存の探索順とhuman gateを維持する。tie-breakerの`Series FF中央値`は、採用Seriesの`Union FF中央値`を意味する。FFが有限な採用Seriesがない場合は比較上の最低値として扱う。

### Test

- 同一Description＋複数ClusteringがCoreになる。
- 異なるDescription、構造表現＋Description、異なる構造表現がCross-representation Coreになる。
- 単独Selected Cluster支持がFringeになる。
- 分類が排他的で、合計がUnion Nと一致する。
- Cross-representation Core、Core、Fringe、Supported Core、UnionのFFが共通のEndpoint-valid N規則で計算される。
- Endpoint-valid Nが0の集合ではFFが`null`となり、救済判定に使われない。
- Union FF 0.50、Supported Core FF 0.50、Union FF 0.30の各境界。
- StandardとSupported Core rescueを同時に満たす場合はStandardになる。
- 救済通過時にFringeを含むUnion全体がanalysis unitになる。
- 不通過時にsource Clusterへfallbackする。
- parameter MatrixとA009の最終unit数が新採否結果と一致する。

## 8. Phase 5: Template忠実性とReport監査

### 8.1 品質保証原則

定型Reportは承認済みTemplateを唯一のレイアウト定義とする。実行時にLLMがSection構成、表示順、Table構成を生成または変更しない。

対象は次とする。

- A009全体Report
- A009個別Report

### 8.2 Template契約

1. 各Reportを必ず対応Templateから`Template.substitute()`で生成する。
2. full HTMLを組み立てる代替経路を作らない。
3. 必須placeholder一覧を検証し、欠落、重複、未解決placeholderを拒否する。
4. 共通Table、metric card、gallery、折り畳みは共通rendererに限定する。
5. Report indexへ`template_id`、`template_version`、`template_sha256`を記録する。
6. 通常、0件、一部未実施、一部掲載、fallbackのみのfixtureで同じTemplate構造をrenderできることをtestする。
7. Template変更時は人間が一度表示を確認し、その後はhashと契約testで固定する。

Template契約違反はReportを生成済みとして扱わない。必須placeholderの欠落、重複、未解決placeholder、Template metadata不整合を検出した場合はA009 Nodeを失敗させ、診断にTemplate IDと該当placeholderを残す。

### 8.3 自動監査

追加する生成後監査はlink確認と件数確認に限定する。

#### Link確認

- Report indexに登録されたHTML／CSV／画像が存在する。
- local `href`／`src`がReport directory内の実在fileまたは有効な埋込みdataを参照する。
- directory外への意図しないrelative traversalを拒否する。

#### 件数確認

Canonical CSV／JSONとHTML表示値について、少なくとも次を照合する。

- 全Cluster、Selected Cluster、Candidate／Accepted／Rejected Series、fallback、最終analysis unit
- Standard accepted／Supported Core rescueの内訳
- Cross-representation Core／Core／Fringe／Supported Core／Unionの各N
- 個別Report index件数と実HTML件数
- 「全件表示」と「上位N件表示」の説明値

生成後監査結果はA009配下の`report_audit.json`へ保存し、少なくとも`status`、`template_checks`、`link_checks`、`count_checks`、`errors`を持たせる。`status`は`pass`または`fail`とする。local link切れ、directory traversal、canonical Artifactとの件数不一致が1件でもあればA009 Nodeを成功確定せず、Runtime Full AuditもFAILとする。監査失敗はReport内容を自動修正せず、原因と対象Report／fieldを診断として返す。

### 8.4 禁止事項

- LLM Visionを使用しない。
- Screenshot比較を自動監査へ含めない。
- AIによる可読性、色、余白、化学構造の外観評価を行わない。
- Runtime AuditがTemplateのデザインを独自判断して修正しない。

## 9. Phase 6: 文書整合

### 作業

1. Series ID表記を実装の`S######`／`S000001`へ統一する。
2. verification commandの実行directoryを明示し、repository rootからそのまま実行できる形へ統一する。
3. repository rootへQuick Start READMEを追加し、新規Run、再開、終了処理への導線を置く。
4. docs READMEから本追補計画、calculation version規則、0.1.11 MMP文書、0.1.12引継ぎ文書へlinkする。
5. 0.1.10仕様概要、実装計画、policy、output contract、user guide、quick referenceを新しいA003／Series／Report契約へ同期する。
6. 旧multi-Cluster FF 0.40を現行採否条件として扱う説明が残っていないことを検索検証する。廃止理由またはbaseline履歴として明示した記述は許容する。

## 10. Phase 7: Prompt集の補強

### 方針

- Promptは実在するSkill／Runtime操作だけを案内する。
- 日常操作と障害／保守操作を分離する。
- Main Agentが独自CLI、State直接編集、短間隔pollを行う指示を追加しない。
- Versionと用語を0.1.10実装へ一致させる。

### 必須追加・改訂項目

1. 入力preflight: 列、重複ID、Endpoint有効数、invalid SMILES、Project／Run rootをread-only確認する。
2. Report link／件数監査: 新しいFull Audit項目だけを実行・報告する。
3. Series support結果確認: Standard／rescue／fallbackと3 member層を短く確認する。
4. calculation version確認: Description CapabilityのVersion必須性とcache再利用可否を確認する。
5. Release smoke test: package verification、test、代表fixture、Full Auditを順に実行する。
6. Round完走後の終了処理: Runtime `query`、`AWAIT_HUMAN_REVIEW`、Full Audit PASSを確認してから`accept-round`を実行し、新Roundを開始しない。
7. 同じRoundの再開、Series Matrix選択、25～100件の明示承認、On-demand解析の既存Promptを新しいSeries用語へ同期する。

Promptに記載したSkill名、Runtime subcommand、required action、parameterが実装に存在することをcontract testで検証する。Report再生成、Run間比較、Database backup等は、対応する正式操作が存在する場合だけPromptを追加し、Promptだけを先行させない。A008用Promptは0.1.10 baselineのままとし、0.1.11の2 Mode等を先行記載しない。

## 11. Version境界: A008 MMPは0.1.11へ移管

0.1.10追補ではA008 MMPへ追加変更を行わない。現行0.1.10で実装済みのMMP Report、A009導線、Type-I／II／III、1-cut、radius 0–2はbaselineとして維持する。

次の追加改修は[`CONDUCTOR_0.1.11_handoff.md`](CONDUCTOR_0.1.11_handoff.md)へ移管した。

- 2 Mode化と旧3 Type互換adapter
- Global Top 1と人間指定Targetの共通Target解析
- Target／Neighbor方向のcorrectness修正
- MMP relationship mapの製品実装
- Exact Core以外のTransformation evidence
- Attachment-constrained mappingとEnvironment解析
- Analysis unit情報との接続
- Target improvement opportunityとVirtual Candidate
- 1-cut／2-cutの範囲と品質条件
- Interactive Report／GUI

0.1.10のtest、Report監査、Definition of Doneへ、これらの新しいMMP条件を含めない。

## 12. 実装順序

1. Baseline固定
2. A003判定契約
3. calculation version必須化
4. Schema hardening
5. Series support分類と採否
6. Template忠実性、link／件数監査
7. 文書とPrompt同期
8. 全test、package verification、代表E2E、Full Audit

## 13. Definition of Done

- A003の正式通過件数が相関条件だけから決まる。
- A003のNがfeatureごとの有限pair数と一致する。
- 全Descriptionに明示的な`calculation_version`があり、欠落時にfail-fastする。
- 正常Runtime JSONは全Schemaを通り、不正fixtureは期待する境界で拒否される。
- Series member分類、3 member classのFF、Supported Core／Union FF、標準／救済採否、fallbackが決定的に再現する。
- 採用Seriesのanalysis unitがFringeを含むUnionである。
- canonical Reportが承認済みTemplateだけから生成され、template ID／Version／hashを追跡できる。
- Report linkと主要件数の自動監査がPASSし、失敗時にA009とFull Auditが成功扱いにならない。
- LLM Visionを使用する処理、手順、Promptが存在しない。
- docsとPromptが実装済みCLI／Skill／用語と一致する。
- 全test、package verification、catalog check、Runtime Full AuditがPASSする。
- A008に0.1.11向けの追加改修が混入せず、現行0.1.10 baselineが維持される。

## 14. 実装結果

2026-09-06に本計画の対象項目を実装した。A003判定、`calculation_version`必須化、Schema強化、Series member分類とSupported Core rescue、A009 Template契約とlink／件数監査、文書・prompt・Catalog同期を完了した。MMP追加改修は計画どおり0.1.11へ分離した。

検証は専用Pixi test環境で60 tests PASS、package layout verification PASS、generated Catalog check PASSとした。Test環境の実体`.pixi/`およびRun／Report検証出力はGit管理対象外であり、`pixi.toml`とlockfileは再現性入力として管理する。
