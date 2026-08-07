# CONDUCTOR 4.3.0 リファクタリング作業計画

## 1. 文書の位置づけ

本書は[設計仕様](CONDUCTOR_v4_design_spec.md)を実装へ反映するための作業計画兼完了記録である。現在のbranch上で新規Run向けに実装し、旧Stateのmigration、後方互換wrapper、Archive作成は行わない。

2026-08-07時点でPhase 1～9とWindows上の自動総合試験を完了した。全34試験、Catalog検証、Package配置検証は合格している。Linux HPC、A100、共有Pixi、最大規模benchmarkは配置先での受入試験として残る。詳細は[検証記録](CONDUCTOR_v4_verification.md)を参照する。

| 区分 | 状態 |
|---|---|
| ID／Round／DAG／index／Group管理 | 実装・自動試験済み |
| 基本計算／初期探索／追加探索／深掘りplanner | 実装・自動試験済み |
| Operator adapter／Interpretation／HTML／handoff | 実装・自動試験済み |
| Package差分gate／Catalog／profile | 実装・自動試験済み |
| Linux HPC／A100／共有Pixi／最大規模性能 | 受入環境で未実施 |

## 2. 目的

1. 複数Roundを例外ではなく標準動作にする。
2. 基本計算、初期探索、追加探索、深掘り解析を明確に分離する。
3. Description／Grouping／Operatorの計算Kernelを極力維持する。
4. State、ID、Group、Evidence、Question、salienceを単純かつ監査可能に管理する。
5. Orchestratorが全成果物を毎回全文読込せず、必要箇所へ到達できるようにする。
6. Interpretationを作業logではなく、人間が次の判断に使える解釈reportにする。

## 3. 変更境界

### 3.1 原則維持するもの

- Descriptionの数値計算、既定parameter、standalone CSV
- Groupingのcluster／membership計算
- Operatorの数式と主要数値CSV
- 一般利用時の`--conductor`なしの挙動
- Skill単独コピー可能性とSkill内Pixi環境
- compound ID／SMILES／分子標準化を人間が担う境界

保護対象の変更が必要になった場合は、理由、旧出力との差、golden regression更新の妥当性を個別に提示し、暗黙には変更しない。

### 3.2 主な再設計対象

- `.claude/skills/cs-conductor-orchestrator/`
- `.claude/agents/cs-conductor-orchestrator.md`
- `.claude/agents/cs-conductor-interpreter.md`
- `.claude/skills/cs-analysis-interpret-evidence/`
- Operator SkillのCONDUCTOR adapterとHTML report層
- `CONDUCTOR_modules/schemas/`
- `CONDUCTOR_modules/catalog/`と新設するprofile
- State／index／Round artifact
- 検証scriptとtests

### 3.3 非対象

- 旧Runのimportまたは変換
- SBDD本実装
- MMPの新規実装
- 分子標準化
- Description、Grouping、Operatorの全面的なアルゴリズム刷新

## 4. 実装原則

- 正本schema、Policy、profileは`CONDUCTOR_modules/`で管理し、Skillへ必要なcopyを生成・照合する。
- Skill実行に必要なcode、schema、環境定義は各Skill directory内にも保持する。
- `CONDUCTOR_modules/`はruntime read-onlyとし、解析結果を書き込まない。
- State更新はOrchestrator／State Managerだけが行い、各Skillはeventとartifactを返す。
- artifactはimmutable、importanceとQuestion statusはappend-only event由来の可変viewとする。
- candidateを大量にDAGへ先行登録せず、実行採択時にNodeを予約する。
- すべての乱択にseed、候補集合hash、採択順を記録する。

## 5. 実装工程

### Phase 0: 現行baseline固定

作業:

- standalone／`--conductor`双方について代表fixtureを保存する。
- 全Description、全Grouping、全Operatorの入力、主要出力、hash、数値許容誤差を定義する。
- MCSのseed付きsampling、metric dispatch、Operator HTMLを含む現状testを確定する。
- 変更禁止のKernel部分と変更可能なadapter部分をfile／function単位で記録する。

完了条件:

- refactor前の成功例を自動再現できる。
- 数値差が発生した際にKernel差かmetadata差かを判別できる。

### Phase 1: ID、schema、Round lifecycle

作業:

- [識別子リファレンス](CONDUCTOR_identifier_reference.md)に従いCapability IDとNode IDを分離する。
- `RND`、`ND/NG/NO/NI`、`G/E/F/H/Q/REL/REQ/SCP/SEV`のrun-global counterを実装する。
- State schemaをRun identity、Round control、DAG、counter、index reference中心へ再設計する。
- active Roundを一つに制限し、start、pause、resume、checkpoint、completeを実装する。
- Node予約、retry時の予約再利用、atomic update、lock、stale伝播を実装する。
- 完了済み／欠番／別active Round指定時にStateを変更しない。

完了条件:

- 複数sessionと複数RoundをまたいでもIDが再利用・再番号付けされない。
- retryでNodeとInterpretation entityが二重登録されない。
- DAG cycleがschema／State Managerの双方で拒否される。

### Phase 2: 軽量indexとsummary

作業:

- `coverage_index.json`をphase、Capability、family、scope、applicabilityで検索可能にする。
- `group_registry.csv`と分割可能なcompound × Group Boolean matrixを実装する。
- `evidence_digest.jsonl`、`salience_view.jsonl`、`salience_history.jsonl`を実装する。
- `question_ledger.jsonl`と`relation_index.jsonl`を実装する。
- `state_summary.json`と`next_round_brief.json`をmaterialized viewとして生成する。
- Stateとimmutable artifactからindexを再構築するcommandを実装する。

完了条件:

- Orchestratorがraw Stateと全Evidence本文を読まずに進捗、未完了coverage、active Questionを把握できる。
- `routine` Evidenceを削除せず再昇格できる。
- 数千Node／Evidenceのrelation候補生成で全ペア走査を行わない。

### Phase 3: Operator CONDUCTOR adapter

作業:

- 各Operatorの数値Kernelとmetadata／report生成を明示的に分離する。
- `evidence.json`とcompactな`evidence_digest.json`の共通契約を実装する。
- scope、sample数、Group、評価Description、Grouping由来、metric、主要統計、warningを記録する。
- 全Operatorで個別`operator_report.html`を生成し、数値CSVとsupporting row／pairへ導線を持たせる。
- metricはDescription metadataからdispatchし、binary fingerprintではTanimoto以外を拒否する。
- 同一数値結果を重複計算せず、既存Grouping-wide出力がcoverageを満たす場合は参照する。

完了条件:

- refactor前後で保護対象の数値出力がgolden regressionに合格する。
- 全OperatorのCONDUCTOR出力がEvidence、digest、manifest、HTML、eventを持つ。
- 一般利用時にCONDUCTOR専用artifactを要求しない。

### Phase 4: 基本計算planner

作業:

- Catalog schemaへrepresentation family、value semantics、natural metric、applicability、cost、runtime requirementを追加する。
- 人間管理の解析profileを新設し、全Description、Grouping family代表、variant、waiver規則を宣言する。
- 全有効DescriptionとDirect structure Groupingを計画する。
- Vector Clusteringをprofileで指定した異family代表へ全applicable algorithm適用する。
- Categorical、Meta-overlap等の条件付きCapabilityを`not_applicable`理由付きで扱う。
- 高コストDescriptionを一つのapproval bundleへまとめ、preflightと承認scope hashを保存する。

完了条件:

- 明示的waiverなしに高コストDescriptionが黙って除外されない。
- 基本計算coverageが`success/failed/unavailable/waived/not_applicable`で監査できる。
- 基本計算未完了時に、Orchestratorが理由なく初期探索へ進まない。

### Phase 5: 初期探索の二段wave

作業:

- 共通Description master panelをprofileで宣言し、Operatorごとの恣意的source固定を除去する。
- global waveで全applicable Operator roleを計画する。
- 全Grouping artifactについてGroup数、size、Endpoint分散、enrichment、構造凝集性、overlap semanticsをscreenする。
- 各Groupingから通常2～4の代表Groupを、十分なN、中程度size、構造凝集性、Endpoint dispersion極値、低重複の役割で選ぶ。
- 同一Groupが複数roleを満たす場合は統合する。
- local waveで各代表Groupへ全applicable local Operator roleを計画する。
- 排他的partitionだけに適用できるGroup間比較を、重複Groupへ誤適用しない。

完了条件:

- globalとlocalの必須coverage matrixを機械検証できる。
- 特定Description／Groupingに特定Operatorだけを割り当てる旧固定表が残らない。
- Endpoint依存の代表選択がdiscovery biasとして記録される。

### Phase 6: 追加探索planner

作業:

- 未実施analysis cellをDescription family、Grouping family、Operator、scopeで層化する。
- coverageの薄い層を優先し、seed付きランダム非復元抽出する。
- candidate pool hash、seed、採択順、除外理由をRound manifestへ保存する。
- resource envelope内の採択分だけDAG Node化する。

完了条件:

- 同一seedと候補集合で採択が再現する。
- 特定family、Grouping、Operatorへ一方的に偏らない。
- 未採択候補がStateを膨張させない。

### Phase 7: Question起点の深掘り

作業:

- Questionに`deep_dive_potential`、`human_decision`、status、priority、根拠を実装する。
- 人間の`skip`をhard gate、`defer`を保留、`allow`を許可として扱う。
- 同一Groupの別Operator、sibling Group/global、異Description、outside/matched control、反証を比較bundleとして計画する。
- 人間指定の部分解析もNode、Round、provenance、coverageへ通常どおり登録する。
- 同じanalysis signatureを再実行しない。

完了条件:

- すべての深掘りNodeがQuestionまたは明示的human requestへ紐付く。
- 注目結果に対し、少なくとも一つの反証またはcontrol候補が検討される。
- `skip`されたQuestionをAgentが勝手に再開しない。

### Phase 8: Interpretation再設計

作業:

- Interpreterの入力をsummary → digest → indexed comparison → full artifactの段階読込へ変更する。
- global/local、cross-Description、sibling Group、cross-Operator、counterexampleをindexed keyで比較する。
- Findingを「観察」「解釈」「注目理由」「制約」に分ける。
- Hypothesisへ支持、反対、代替説明、適用scope、反証状態を持たせる。
- Finding、Hypothesis、Question、Relationのrevisionとrun-global IDを実装する。
- Markdown／HTMLに解析対象、具体的数値、比較対象、意味、限界、個別Operator HTMLへのlinkを表示する。
- Interpreterの提案をState Managerが検証してからledgerへ反映する。

完了条件:

- reportが作業件数やID列挙ではなく、具体的な解釈を人間へ伝える。
- 一つの整った物語へ無理に統合せず、矛盾、例外、negative resultを保持する。
- 全EvidenceのCartesian comparisonを行わない。

### Phase 9: Agent、Skill、promptの統合

作業:

- Orchestrator／Interpreter Subagent文書を新しい役割境界へ更新する。
- Orchestrator／Interpretation SkillのSKILL.mdとREADMEを更新する。
- Operator SkillのCONDUCTOR契約を統一する。
- 新規Run、Round 2以降、部分解析、Interpretationのみ再実行、session handoffのpromptを実装に照合する。
- Catalog、profile、Policy、schemaのsnapshot hashとpackage差分検出を実装する。
- package installerとlayout verifierを新構成へ対応させる。

完了条件:

- Claude Codeの新sessionがState pathとRound番号から再開できる。
- `CONDUCTOR_modules/`を丸ごと差し替えても既存Run artifactが変更されない。
- 必要なSkillとSubagentの差し替え範囲がpackage verifierで判定できる。

### Phase 10: 総合検証

作業:

- [検証仕様](CONDUCTOR_v4_verification.md)の全項目を自動試験または記録付き手動試験として実施する。
- Windowsでplanning、State、small smokeを確認する。
- Linux HPCで共有Pixi binary、Skill内environment/cache、CPU64、A100＋CPU8、shared filesystem lockを確認する。
- 中断、再開、失敗、stale、index再構築、別session継続をfault injectionで試験する。
- 2,000化合物と多数Node／Evidenceのbenchmarkを行い、Round追加時の増加傾向を測定する。
- 説明用HTML、PNG、PPTXを実装済み仕様へ再生成する。

完了条件:

- 必須試験が成功し、未検証環境と既知問題が明記される。
- 旧固定`wide_shallow`、Round単位の再採番、全Evidence全文再読込、runtime package書込みが残らない。

## 6. 主要file別の予定

| 対象 | 主な変更 |
|---|---|
| `CONDUCTOR_modules/schemas/` | State、Round、Evidence digest、salience、Question、Relation、requestのschema |
| `CONDUCTOR_modules/catalog/` | Capability metadata拡張、人間管理profile、生成Catalog |
| `cs-conductor-orchestrator/scripts/state_manager.py` | ID、Round、DAG、lock、index、再構築、partial execution登録 |
| `cs-conductor-orchestrator` Skill／Agent | phase gate、planner、approval、再開、summary-first読込 |
| `cs-analysis-interpret-evidence` | selective loading、entity revision、提案artifact、Markdown／HTML |
| 全Operator Skill | Kernelを保護したEvidence digest／HTML adapter統一 |
| Description／Grouping Skill | 原則metadata adapterとschema同期のみ。計算部は保持 |
| `CONDUCTOR_modules/tools/` | package install、layout/schema同期、Catalog生成、整合検証 |
| `CONDUCTOR_modules/tests/` | golden、contract、Round、ID、coverage、performance、fault recovery |

## 7. 試験戦略

### 単体試験

- ID allocator、analysis signature、DAG cycle、stale propagation
- Round state machine、approval scope、Question gate
- metric dispatch、Group semantics、balanced sampling
- salience revision、index rebuild、report rendering

### contract試験

- 各Skillの一般利用／CONDUCTOR利用の分離
- schema validationとartifact path
- State Manager以外からのState書込み禁止
- package directoryへのruntime書込み禁止

### 回帰試験

- Description、Grouping、Operatorのgolden output
- MCS samplingとVector Clustering metric
- standalone CLI

### end-to-end試験

1. 新規Runと高コストbundle承認
2. 基本計算から初期global／local
3. InterpretationとQuestion生成
4. 新Claude Code sessionで次Round再開
5. 追加探索と人間指定深掘り
6. Question skip／defer／allow
7. index破損からの再構築

## 8. リスクと抑制策

| リスク | 抑制策 |
|---|---|
| control plane変更が数値計算へ波及 | Kernel golden testを最初に固定し、adapter境界で実装 |
| 全Description／全global Operatorによる時間増加 | 高コストbundle承認、preflight、HPC並列上限、再計算防止 |
| Group × Operatorの組合せ爆発 | 代表Group wave、applicability、coverage index、採択時Node化 |
| Round増加によるState肥大化 | immutable artifact分離、compact index、summary-first読込 |
| salienceによる見落とし | artifactを保存し、可変分類とroutine再昇格を許可 |
| Interpretationの偽陽性 | 許容した上で探索回数、選択経路、反証、独立性を明示 |
| profile変更によるRun内意味の混在 | Run snapshotとRound開始時差分検出、人間承認 |
| 複数sessionの競合更新 | 単一active Round、lock、atomic replace、retry reservation |

## 9. 実装順序とcommit単位

Phase 0から順に実装した。特に初期探索を広げる前に、Phase 1～3のState、index、Operator digestを完成させ、解析数だけを増やしてOrchestratorの読込負荷を悪化させない構成とした。

各Phaseは原則一つ以上の独立commitとし、次の状態で区切る。

1. schema／test
2. implementation
3. Skill／Agent文書
4. generated copy／Catalog
5. verification result

Archive directoryは作らず、過去状態への復帰はgit historyと現在のbranch管理で行う。

## 10. Definition of Done

- 正本文書、schema、Catalog/profile、Skill、Subagent、実装が一致している。
- 基本計算、初期探索、追加探索、深掘りのcoverageと選択理由をStateから監査できる。
- 一つのRunでRoundを継続し、全run-global IDを引き継げる。
- 部分実行とInterpretationのみの再実行も通常のNode／Round管理へ入る。
- 全結果を保存したまま、Orchestratorが重要なdigestだけを通常読込できる。
- Interpretation Markdown／HTMLが具体的な解析、比較、意味、限界、次のQuestionを説明する。
- Description／Grouping／Operatorの保護対象計算がgolden regressionを維持する。
- Windowsの所定試験が完了し、Linux HPC項目が受入試験として明記されている。
- `CONDUCTOR_modules/`へのruntime書込みがない。
