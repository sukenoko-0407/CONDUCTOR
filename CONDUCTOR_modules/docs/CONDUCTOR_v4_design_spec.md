# CONDUCTOR 4.3.0 設計仕様

## 1. 目的

CONDUCTORは、複数のDescription、Grouping、Operatorを疎結合に組み合わせ、化合物全体と局所Groupの違いを反復的に探索するSAR解析システムである。単一の一貫した説明を強制せず、局所化による変化、異なる表現での一致、矛盾、例外、Activity Cliffを仮説候補として提示する。

本仕様は新規Run専用である。旧Stateとの後方互換は持たない。

## 2. 用語

- **Run**: 同一input、endpoint、`higher_is_better`を扱う解析全体。複数Roundを含む。
- **Round**: 人間の解析開始・継続指示からOrchestratorが成果またはcheckpointを返すまでの管理単位。
- **Phase**: Nodeの目的。`basic_compute`、`initial_global`、`initial_local`、`additional_exploration`、`deep_dive`、`human_directed`を使う。
- **Capability**: Catalogへ登録された手法。
- **Node**: Run内でCapabilityを一つの設定・scopeにより実行する単位。
- **Evidence**: Operatorが生成する数値的観察。
- **Finding**: 一つ以上のEvidenceに基づく注目すべき観察。
- **Hypothesis**: 検証可能な説明候補。Findingごとに必須ではない。
- **Question**: 追加解析で識別したい未解決の科学的問い。

RoundとPhaseは直交する。基本計算が複数Roundへまたがることも、一つのRoundで追加探索と深掘りを行うことも許容する。

## 3. 基本原則

1. Runは複数Roundを前提とする。
2. Description、Grouping、Operatorの科学計算Kernelは原則維持する。
3. 一般利用では`--conductor`を付けない。
4. CONDUCTOR利用ではOrchestratorだけがNodeを予約し、明示的に`--conductor`を付ける。
5. 基本計算、初期探索、追加探索はcoverage中心、深掘りはQuestion中心に計画する。
6. 全成果物を保存する。重要度は可変な索引で管理し、成果物へ書き戻さない。
7. DAGは有向非巡回とし、計算依存、再開、stale伝播、provenanceを管理する。
8. Round、Question、salience、coverageをDAGだけで表現しない。
9. 相関を因果と断定しない。
10. 分子標準化、compound ID、SMILESの品質は人間の責務とする。

## 4. Skill境界

### 4.1 Description

CSVまたは単一・複数SMILESから数値表現を生成する。計算式、既定parameter、一般利用CSVを保護対象とする。CONDUCTOR adapterはrepresentation family、value semantics、natural metric、seed、model／conformer情報、manifest、eventを付加できる。

### 4.2 Grouping

Direct structure Groupingはcompound-ID/SMILES CSV、Description-vector ClusteringはDescription artifactを入力とする。クラスタリング結果の計算は保護対象とし、run-global Group ID、由来、`membership_semantics`、Group indexはState Managerが管理する。

### 4.3 Operator

数値KernelとCONDUCTOR adapterを分離する。Kernelの数式と数値CSVは原則維持する。adapterはscope、provenance、Evidence ID、digest、比較可能性情報、HTML reportを担当する。新しい集約が必要な場合は既存Operatorの意味を黙って変えず、新Operatorまたは明示的aggregatorとして追加する。

### 4.4 Interpretation

Interpretationは大幅な再設計対象である。全Evidenceの短いdigestを索引検索し、新規、未評価、priority、Question関連、反証候補だけを詳細読込する。全ペア総当たり比較を行わない。

## 5. 解析Phase

### 5.1 `basic_compute`

人間の明示的省略がない限り、Catalogで有効かつ実行可能な全Descriptionを生成する。高コストDescriptionを含み、input hash、endpoint、profile hash、設定、resource envelopeに対して一回だけbundle承認を得る。

Direct structure Groupingを実行し、Description-vector Groupingは人間管理profileが指定する互いに異なるrepresentation familyの代表へ全適用可能algorithmを実行する。C011はassay条件が複数の場合、meta Groupingは必要な上流完成後に計画する。

### 5.2 `initial_global`

全体scopeについて全applicable Operator roleを実行する。Description依存Operatorは共通master panelから互換性のある表現を使用し、Operatorごとに恣意的なsource集合をハードコードしない。Grouping全体を評価するOperatorもこのphaseに含む。

### 5.3 `initial_local`

Grouping-wide screenにより各Grouping Nodeから通常2～4の代表Groupを選ぶ。同じGroupが複数roleを満たす場合は統合する。各代表Groupへ全applicable local Operator roleを実行する。不適用cellは理由付き`not_applicable`とする。

### 5.4 `additional_exploration`

未実行の有効analysis cellをDescription family、Grouping family、Operator、scopeで層化し、coverage不足の大きい層を優先したseed付きランダム非復元抽出を行う。候補全件をDAG Node化せず、採択分だけを登録する。

### 5.5 `deep_dive`

Questionへ紐付く比較bundleを計画する。標準bundleは、同一Groupの別Operator、sibling Groupとglobal comparator、同一Groupの異Description、outside／matched control、反証・再現、人間指定である。

## 6. Round

Round IDは`RND0001`からRun内通番とする。active Roundは一つだけとし、承認待ちやsession終了では同Roundをpause/resumeする。番号不整合時はStateを変更しない。

通常はInterpretation Nodeを生成してRoundを完了する。基本計算のみ、HPC job待ち、人間による中断では`checkpoint`として終了できる。各Roundはrequest、manifest、summary、Evidence set、triage update、next-round briefを保存する。

## 7. Stateと索引

`state.json`はcontrol planeであり、巨大なmembershipや長文解釈を格納しない。少なくとも次を保持する。

- Run identityとpackage/profile snapshot
- Round controlとID counters
- execution DAG
- coverage indexへの参照
- Group indexへの参照
- Evidence digest／salience／Question／Relation ledgerへの参照
- artifact path、hash、status、analysis signature

Derived indexはStateとimmutable artifactから再構築可能でなければならない。Orchestratorは最初に`state_summary.json`を読み、必要なNode、Group、Evidenceだけを詳細取得する。

## 8. ID

ID契約は[識別子リファレンス](CONDUCTOR_identifier_reference.md)を正本とする。Run内entityはRoundをまたいで通番を維持し、削除、再利用、再番号付けを行わない。Capability IDとNode IDは別namespaceとする。

## 9. SalienceとQuestion

Evidenceの`attention_class`、科学的role、Question linkageは可変であり、append-only eventで履歴を残す。`routine` Evidenceもdigest検索対象に残し、新しい比較が成立した場合は再昇格できる。

Questionはすべて深掘りする必要がない。Agentの`deep_dive_potential`と人間の`human_decision`を分ける。人間の`skip`はhard gateであり、Agentは`reopen_recommended`を提示できるが勝手に解除しない。

## 10. Packageと再現性

Run開始時にCatalog、profiles、Policies、Skill version、package manifest hashをsnapshotする。Round開始時に差分を検出し、人間承認なしにcoverage定義やSkill意味を変更しない。

3D、model、quantum系はseed、conformer設定、model名、weight hash、device、precision、software versionを記録する。Skill環境は各Skillの`env/`内Pixi環境とし、共有Pixi binaryとSkill内cacheを使用する。

## 11. 受入基準

- 計算Kernelのgolden regressionが維持される。
- 基本計算、初期global、初期localのcoverageが機械検証できる。
- Round番号、run-global ID、Question、salienceが再開後も一貫する。
- balanced random探索がseed再現可能で偏りを抑える。
- routine Evidenceが新しい関係から再昇格できる。
- InterpretationがEvidence数に対して全ペア総当たりを行わない。
- State／indexが中断後に再構築・再開できる。
- Windowsでplanningと小規模実行、Linux HPCでCPU64／A100と共有Pixiを検証する。
