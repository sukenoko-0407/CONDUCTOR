# CONDUCTOR 0.2.1 実装計画書

Status: **本番規模L5の不適合を確認。全Lensの実worker消費・計算量・長時間Node管理を横断再評価中。**

対象読者: **本設計の議論に参加していない実装担当者。**

したがって本書は「適切に判断する」「必要に応じて」といった委任表現を使わない。
判断が必要な箇所は本書で決めるか、決められないものは「実装前に確認を要する」と明示する。

## 0. 読む順序

| 順 | 文書 | 読む理由 |
|---|---|---|
| 1 | [`CONDUCTOR_0.2.1_specification_overview.md`](CONDUCTOR_0.2.1_specification_overview.md) | 全体像と決定事項。**13章の決定事項一覧は実装の契約** |
| 2 | [`design/calibration_results.md`](design/calibration_results.md) | **全パラメータの根拠。実測値であり推測ではない** |
| 3 | [`design/finding_model.md`](design/finding_model.md) | 出力の中心データ構造 |
| 4 | [`design/discovery_lenses.md`](design/discovery_lenses.md) | 各レンズの統計形式 |
| 5 | [`prompt/CONDUCTOR_0.2.1_prompts.md`](prompt/CONDUCTOR_0.2.1_prompts.md) | 本番運用とLocal LLM taskの正式プロンプト契約 |
| 6 | [`CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md`](CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md) | 実装判断履歴、本番障害、0.1.x Boolean matrixを踏まえたL5/Runtime再設計案 |
| 7 | 残りの design/ 各論 | 実装中に必要になった箇所だけ |

0.1.x のドキュメントは `archive_0.1.x/`（Git 管理外）にある。科学的仕様の前提にはしない。ただし、科学的意味から独立した計算表現・atomic promotion・sharding等は、[`CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md`](CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md)の区分に従って再評価する。
当初から流用対象としたコード資産は本書3章に列挙する。

---

## 1. 実装しないもの 【最初に読むこと】

設計途中で検討され、**実データ計測により却下された**ものがある。これらを実装してはならない。

| 項目 | 却下理由 |
|---|---|
| **L1a（空間水準の説明力）** | 全空間で不在（best_min_lam の最大値が負）。検定約100回で何も生まない |
| **L3（局所期待からの逸脱）** | ドライランで enrichment 1.02〜1.08。並べ替えデータと区別がつかない |
| **L6（活性濃縮クラスタ）** | ドライランで enrichment 0.98〜1.01。検出しているのは骨格そのもの |
| **FF ≥ 0.50 による事前選抜** | 0.1.x の失敗要因。循環と範囲制限を生む |
| **フラグメント類似度による未試験フラグメントへの外挿** | λ_frag = 0.27 で信頼できない |
| **空間ごとの重み付け** | 全空間で λ が横並び（0.61〜0.68）。優劣が存在しない |
| **Cliff 閾値の IQR 基準** | IQR はデータセット間で2倍以上変動する。ノイズ基準を使う |
| **MPO 横断レンズ（M1〜M3）の解析実装** | 0.2.1 の範囲外。データモデルとスキーマのみ対応させる |

L1a / L3 / L6 は**診断指標として計算し報告してよい**。ただし Finding を生成してはならない。

---

## 2. 確定パラメータ一覧

すべて [`design/calibration_results.md`](design/calibration_results.md) に根拠がある実測値である。
**コード内にハードコードせず、設定ファイルの既定値として置く。**

### 2.1 ノイズと閾値

| パラメータ | 値 | 根拠 |
|---|---|---|
| 測定 σ | 0.10 | 較正 1章。3手法が収束 |
| σ_diff | 0.14 | √2 × σ |
| 単一ペアの neutral 判定 | \|Δ\| < 0.28 | 2 σ_diff |
| Cliff の Endpoint 差下限 | \|Δ\| ≥ 0.42 | 3 σ_diff |
| Cliff の類似度下限 | Tanimoto ≥ 0.75 | 0.85 へ上げても抽出率は改善しない |
| 許容性の分散上限 | σ² ≤ 0.02 | σ_diff² 相当 |

**測定 σ は較正データ固有の値である。** 別プロジェクトへ適用する際は診断モジュールで
再推定すること（0.2.2 で自動化する）。0.2.1 では設定ファイルに書く。

### 2.2 構造・文脈

| パラメータ | 値 |
|---|---|
| 局所平坦性 λ の閾値 | 0.5 |
| 近傍サイズ k | 10 |
| 文脈の最小サイズ | Endpoint 有効 5 化合物 |
| 文脈の Jaccard 重複排除閾値 | 0.9 |
| 条件付け深度 | **1**（単一条件のみ。組合せ条件は作らない。段階9-3 参照） |
| Favorable の定義 | Global Endpoint の上位20%（`higher_is_better=false` なら下位20%） |

### 2.3 レンズ別

| レンズ | パラメータ |
|---|---|
| L2a | 3ペア以上を持つ変換のみ対象。文脈内 n ≥ 3 かつ文脈外 n ≥ 3 |
| L2b | 2文脈以上に現れるフラグメント。検定には3文脈以上 |
| L5 | 両文脈で \|r\| ≥ 0.3、符号が逆、同一分割軸から生じたペアに限定 |
| L7 | 共通 R 基 m ≥ 5。\|Spearman ρ\| ≥ 0.5 |
| L4 | 到達経路が1本以上存在すること（L2 の変換 DB を参照） |

### 2.4 出力

| パラメータ | 値 |
|---|---|
| 既定表示件数 K | 10 |
| 深堀の最大深度 | 3 |
| 深堀のノードあたり最大分岐 | 3 |
| 深堀の Finding あたり検定実行回数 | 15 |
| 連続 INCONCLUSIVE で枝を打ち切る | 2 |

---

## 3. 0.1.x から流用するコード資産

| 資産 | 流用先 | 注意 |
|---|---|---|
| **Description Database**（Program 別 SQLite、`calculation_version` による再利用判定） | Phase 1 | **ほぼそのまま転用する。再構築しない。** 同一 ID・異構造の fail-fast、監査付き invalidate も含む |
| Description Skill 群（D001〜D020） | Phase 1 | Pixi 環境ごとそのまま使う |
| MMP canonical database（0.1.11 Mode II） | Fragment engine | Target 非依存・immutable な設計は正しい |
| **Attachment 制約付き MCS ＋ Tanimoto による Similar core 判定** | L2 の core 類似度クラス | **再構築コストが高い。0.1.11 の実装を活かす** |
| Pixi による Skill 自己完結 | 全 Skill | |

**診断モジュール**（`CONDUCTOR_modules/diagnosis/`）は 0.2.1 に含まれる計測ツールである。
本解析パイプラインへの組み込みは 0.2.2 で行う。0.2.1 では独立したツールとして維持する。

### 3.1 既存 0.1.x 資産の処遇 【段階0 として最初に実施すること】

リポジトリには 0.1.x の実装が残っている。**着手前に仕分けること。**
削除ではなく `Archive/` へ退避し `.gitignore` へ追加する（ドキュメントと同じ方式）。

| 対象 | 処遇 |
|---|---|
| `.claude/skills/cs-compute-description-*`（19個） | **保持。そのまま流用する** |
| `.claude/skills/cs-analysis-*`（10個） | **退避。** A001〜A009 は 0.2.1 に存在しない |
| `.claude/skills/cs-compute-clustering-*`（11個） | **退避。** 0.2.1 は凝集型1手法のみで、`cs-context-builder` に内包する |
| `.claude/skills/cs-conductor-orchestrator` / `cs-conductor-runtime` | **退避。** Phase 構成が変わるため再実装する |
| `.claude/skills/cs-conductor-on-demand-analysis` | **退避。** 0.2.1 では On-demand を定義していない |
| `CONDUCTOR_modules/catalog/*.json` | **退避して作り直す。** 0.1.x の Capability（A/C/I/O）を参照している |
| `CONDUCTOR_modules/schemas/*.json` | **退避して作り直す。** 0.2.1 は Finding 中心の契約になる |
| `CONDUCTOR_modules/tools/description_database.py` | **保持。そのまま流用する** |
| `CONDUCTOR_modules/tools/runtime_controller.py` | **退避。** 再実装する |
| `CONDUCTOR_modules/tools/verify_package_layout.py` | **退避して作り直す。** 検証対象が変わる |
| `CONDUCTOR_modules/tools/install_into_project.py` | 保持し、新しいレイアウトに合わせて更新する |
| `CONDUCTOR_modules/tests/` | **退避。** 0.1.x の契約テストである |
| `CONDUCTOR_modules/diagnosis/` | **保持。触らない** |

退避したものを参照して実装しないこと。**0.1.x の思想は引き継がない。**
流用すると明記した資産（Description Skill、Description Database、
MMP canonical database、Attachment 制約付き MCS）だけを使う。

0.1.10/0.1.11のDescription Databaseは現行と同じschema version `1.0.0`、Program別・Description別SQLite配置を前提にin-place再利用する。schema変換や一括importは実装しない。cache hitは同一Program、同一compound ID、同一canonical SMILES、同一`calculation_version`、同一calculation signatureで判定する。Gobbi Pharm2D＋SVDはdataset signatureも含める。旧Run stateと旧解析Artifactは再利用しない。

---

## 4. モジュール構成

```text
.claude/skills/
├── cs-description-*/          # D001〜D020。0.1.x から流用
├── cs-fragment-engine/        # MMP 3クラス + フラグメント表
├── cs-context-builder/        # クラスタリング + 文脈カタログ + 翻訳
├── cs-stat-core/              # 並べ替え基盤・多重比較・効果量
├── cs-lens-l2/                # L2a + L2b
├── cs-lens-l5/                # 符号矛盾
├── cs-lens-l1b/               # 条件付き平坦性
├── cs-lens-l4/                # 未踏領域
├── cs-lens-l7/                # 骨格 × 置換基
├── cs-scoring/                # 段階B スコアリング
├── cs-deepdive/               # 深堀エンジン
├── cs-report/                 # 統合・報告・引用検証
└── cs-runtime/                # DAG・State・監査

CONDUCTOR_modules/
├── diagnosis/                 # 計測ツール（既存）
├── schemas/                   # JSON Schema
├── catalog/
└── docs/
    └── prompt/                # 版管理する正式運用・内部LLMプロンプト
```

各 Skill は `env/pixi.toml` を持ち自己完結する。

---

## 5. 実装順序

**この順序を守ること。** 特に段階3（統計基盤）を後回しにしてはならない。
全レンズがこれに依存し、ここを誤ると全結果が無効になる。

```text
段階1  データモデルと契約          ← 他の全てが依存する
段階2  Phase 1 表現生成            ← 0.1.x 流用。早期に動かして実データを流す
段階3  統計基盤（並べ替え）        ← 最重要。レンズより先に作る
段階4  Fragment engine             ← L2 / L4 / L7 が依存
段階5  Phase 2 文脈構築            ← L1b / L2 / L5 が依存
段階6  L2b（主力）                 ← 最初に作るレンズ
段階7  L5 → L1b → L2a → L7 → L4
段階8  Phase 4 スコアリング
段階9  Phase 5 深堀
段階10 Phase 6 統合・報告
段階11 Runtime / DAG / 監査
```

**段階6 を終えた時点で必ず一度止まること。** 本書 8章の enrichment 検証を実施し、
結果を設計担当へ報告する。診断の実測値（L2b enrichment 2.07〜2.54）を再現できなければ、
残りのレンズを実装しても無駄になる。

段階10 を終えた時点で、全レンズについて再度 enrichment 検証を行う。

---

## 6. 各段階の仕様

### 段階1: データモデルと契約

実装するもの:

- `Finding` のスキーマ（[`design/finding_model.md`](design/finding_model.md) 2章のとおり）
- `Endpoint` レジストリ（[`design/endpoint_model.md`](design/endpoint_model.md) 2章）
- 文脈 ID の体系
- JSON Schema を `CONDUCTOR_modules/schemas/` へ置く

文脈 ID の形式を次で固定する。診断モジュールと同じ形式にすること。

```text
CL|<space_id>|k<n_clusters>|c<cluster_index>    クラスタ由来
QT|<feature_name>|q<percentile>                 分位分割由来
SC|<scaffold_hash>                              骨格由来
```

`Finding.entities` は Phase 6 の統合で連結キーになる。**必須フィールドである。**

### 段階2: Phase 1 表現生成

Pipeline planのDescription Nodeは`CONDUCTOR_modules/tools/description_node.py`を唯一のtracked `launch_path`とする。実行時生成scriptやRuntime外からの18 Skill直列起動は受入対象外とする。

0.1.x の Description Skill と Database をそのまま使う。新規実装は次のみ。

- 各空間への **Tier**（1/2/3）と **構造性**（structural / non-structural）のタグ付与
- タグは [`design/feature_space_roles.md`](design/feature_space_roles.md) 2章と 3.5 節の表のとおり
- 0.2.1 identityから0.1.xの厳格ID patternへの決定論的bridge
- cache miss subsetをNode output外の一時directoryへ置き、距離Artifactを`<node-output>/distance/`へ固定
- `resources.workers`をCPU使用可能上限として、解決済みExecution Request、子processの`--workers`、`CONDUCTOR_AVAILABLE_CPU_CORES`、`CONDUCTOR_NODE_CPU_CORES`へ同じ値で注入し、OS affinity超過は起動前に拒否
- D015/D016は希少元素featureの構造的NaNを許容する部分有限値登録契約を持ち、それ以外は全feature有限を維持

**この2軸は直交する。** ECFP4 は Tier 3 だが構造空間、RDKit 2D は Tier 1 だが非構造空間。
混同しないこと。

D015/D016の部分有限値登録は「NaNを0へ置換する」ことではない。nullをpayload/Databaseに保持し、距離校正時に全欠測列を除外した後、残る欠測だけを観測中央値で補完する。全feature非有限またはconformer生成失敗の行は登録対象外とする。

### 段階3: 統計基盤 【最重要】

#### 3.1 並べ替え

**並べ替え単位は解析の条件付け単位に合わせる。** 単一の万能ブロックは存在しない。

| 解析 | 並べ替え単位 |
|---|---|
| L2a / L2b | **系列（同一 constant key）** |
| L1b / L5 | **Murcko 骨格** |
| L4 | Murcko 骨格 |
| L7 | 系列内の R 基ラベル |

**全体並べ替え（ブロックを無視した並べ替え）を帰無分布に使ってはならない。**
較正では L5 で enrichment を 50 倍過大評価した（ブロック 2.19 倍 vs 全体 100 倍）。

診断目的で全体並べ替えも計算してよいが、**q 値の算出には使わない**。

実装の詳細を次で固定する。

```python
def permute_within_blocks(endpoint, block_labels, rng):
    out = endpoint.copy()
    by_block = defaultdict(list)
    for i, b in enumerate(block_labels):
        if np.isfinite(endpoint[i]) and b is not None:
            by_block[b].append(i)
    for idxs in by_block.values():
        if len(idxs) > 1:
            out[idxs] = endpoint[rng.permutation(idxs)]
    return out
```

境界条件を次で固定する。

| 条件 | 扱い |
|---|---|
| ブロックラベルが `None`（骨格を取れない分子） | 並べ替えの対象から外し、値をそのまま保持する |
| ブロックサイズ 1 | 並べ替え不能。値をそのまま保持する |
| Endpoint が欠測 | 並べ替えの対象から外す |

**ブロックサイズ 1 の化合物が多いと帰無分布が狭くなる。** 較正データでは Murcko 骨格 282 に対し
961 化合物（平均 3.4）であり、singleton 骨格が相当数ある。
並べ替えに参加した化合物の割合を必ずログへ出すこと。50% を下回る場合は設計担当へ報告する。

#### 3.2 p 値と q 値の算出

並べ替えから p 値を次で求める。**分子・分母に +1 を入れること。** 入れないと B 回中 0 回のとき
p = 0 となり、BH 補正が壊れる。

```python
p = (1 + number_of_permutations_with_statistic_at_least_as_extreme) / (1 + B)
```

反復数は段階的に行う。

| 段階 | B | 目的 |
|---|---|---|
| 段階A スクリーン | 100 | 明らかに有意でない候補を落とす。p の下限は 1/101 ≈ 0.0099 |
| 生存した候補 | 1000 | q 値を報告する Finding のみ。p の下限は 1/1001 ≈ 0.001 |

B=100 の段階では p ≤ 0.05 を通過条件とする。**この段階で BH 補正を適用しない**
（暫定スクリーンであり、族が確定していないため）。

#### 3.3 多重比較

BH 補正を用いる。**補正の族はレンズごとに独立とする。** レンズを跨いで混ぜない。

族の定義を次で固定する。

| レンズ | 族 |
|---|---|
| L1b | （重複排除後の文脈）×（Tier 1/2 空間） |
| L2a | 3ペア以上を持つ変換 ×（重複排除後の文脈） |
| L2b | 2文脈以上に現れるフラグメント |
| L5 | （同一分割軸内の文脈ペア）×（Tier 1/2 特徴量） |
| L7 | 共通 R 基 5 個以上の系列ペア |
| L4 | 候補領域 |

文脈の重複排除（Jaccard ≥ 0.9）を補正の**前**に行うこと。
較正データでは 270 文脈のうち 104 が近重複を持っていた。重複を残すと族サイズが水増しされる。

#### 3.4 bootstrap（robustness スコア用）

```text
反復数 B = 200
再抽出単位 = ブロック（Murcko 骨格）。骨格ごと復元抽出する
robustness = 主張の方向と有意性（p ≤ 0.05）が保たれた反復の割合
```

**化合物単位の復元抽出をしてはならない。** 非独立性を無視することになる。

### 段階4: Fragment engine

#### 4.1 変換の3クラス

| クラス | variable | cut 数 |
|---|---|---|
| `terminal_substitution` | 末端フラグメント | 1 |
| `linker_replacement` | 2点接続の非環部分 | 2 |
| `ring_system_replacement` | 環系全体 | N（環系の接続数） |

**cut 数の上限 2 という制約を設けてはならない。** 環系の接続数から決まる。

環系置換は環系から外へ出る結合（exocyclic bond）だけを切る。**環結合そのものは切らない。**

#### 4.2 実装上の落とし穴 【必読】

診断モジュールの実装で実際に踏んだ罠である。

> **環フラグメントと残りフラグメントは同じ dummy 数を持ちうる。**
> dummy 数で「どちらが環か」を判別してはならない。

`{置換基}—フェニル—{環}` のような分子で末端環を切ると、環側も残り側も dummy 1 個になる。
**原子インデックスで判定すること。** `Chem.FragmentOnBonds` は元の原子インデックスを保持し、
dummy を末尾へ追加するため、環系の原子集合との積で一意に決まる。

```python
parts = Chem.GetMolFrags(broken)                      # 原子インデックス
ring_part = [f for f, idxs in parts if set(idxs) & ring_atoms]
```

参照実装: `CONDUCTOR_modules/diagnosis/diagnosis/transforms.py` の `_cut_with_indices`。

#### 4.3 サイズ制約

全クラス共通で次を適用する。参照実装は診断モジュール `transforms.py` の定数。

| 制約 | 値 |
|---|---|
| 分子の最小 heavy atom 数 | 6。未満は fragmentation しない |
| constant 側の最小 heavy atom 数 | 4。2-cut では各 constant フラグメントそれぞれに適用 |
| variable の最大割合 | 分子全体の heavy atom の 60% |
| 環系置換の variable 最小 heavy atom 数 | 3 |

#### 4.4 環系置換の attachment 数（C-12 の決定）

| N（環系の接続数） | 扱い |
|---|---|
| 1 | 採用。attachment 対応は自明 |
| 2 | 採用。constant 側を canonical SMILES 順で整列して対応付ける |
| 3, 4 | **一意または対称等価な対応が付く場合のみ採用。** 曖昧なら除外し件数を記録する |
| 5 以上 | **除外。** 件数のみ記録する |

較正データは N ≤ 4 の設定で 1,579 ペアを得ている。

#### 4.5 canonical key の構成

同じ constant を持つ分子どうしをペアにするための鍵である。**形式を次で固定する。**

```text
1-cut     constant フラグメントの canonical SMILES（dummy は [*] に統一）
2-cut     2つの constant フラグメントの canonical SMILES を辞書順に整列し " | " で連結
N-cut     N 個の constant フラグメントの canonical SMILES を辞書順に整列し " | " で連結
```

**dummy 原子のラベルを統一すること。** `Chem.FragmentOnBonds` は既定で結合インデックス由来の
isotope ラベルを付けるため、そのままでは同じ constant が別の鍵になる。

```python
Chem.FragmentOnBonds(mol, bonds, addDummies=True, dummyLabels=[(0, 0)] * len(bonds))
```

#### 4.6 フラグメント表

L2b が必要とする。

```text
series_key -> {fragment_smiles: [compound_index, ...]}
```

系列 = 同一 constant key。R 基が2種類以上ある系列のみ保持する。

**同一系列内で同じフラグメントが複数化合物に現れる場合**（立体異性体など）は、
それらの Endpoint の平均を1観測として扱う。個別に数えると同じ情報を二重計上する。

### 段階5: Phase 2 文脈構築

#### 5.1 文脈カタログ

4種類を生成する。

| 種類 | 生成元 |
|---|---|
| クラスタ所属 | **average-linkage 凝集型** × 全 Description × クラスタ数 grid |
| 特徴量の範囲分割 | Tier 1/2 特徴量の分位点分割 |
| 骨格クラス | Murcko / MCS / BRICS / RECAP |
| 活性域 | frontier / 中域 / 低域（**L6 廃止に伴い診断目的のみ。レンズの条件には使わない**） |

#### 5.1.1 クラスタリングの仕様

**手法は average-linkage 凝集型の1種類のみとする。** 0.1.x は Butina / DBSCAN / Leiden /
Louvain 等 6 手法を持っていたが、0.2.1 では使わない。理由は次の2点である。

- 較正は凝集型のみで実施し、**270 文脈という数と、8章の受け入れ基準（enrichment）は
  この構成に基づいている**。手法を増やすと文脈数が数倍になり、較正値と比較できなくなる
- 手法の多様性が「切り口の多様性」に寄与するかは未測定である

複数手法の導入は 0.2.2 で、診断により有効性を確認してから判断する。

| 項目 | 値 |
|---|---|
| 手法 | average-linkage 凝集型クラスタリング（距離行列を事前計算して渡す） |
| クラスタ数 grid | 10, 20, 40 |
| 距離計量（fingerprint 空間） | 1 − Tanimoto |
| 距離計量（記述子空間） | 標準化後のユークリッド距離。全欠損列と定数列は除外し、欠損は列中央値で補完 |

**Description ごとに距離行列を1回だけ計算し、全 k で使い回すこと。** 再計算は無駄である。

#### 5.1.2 分位分割の仕様

Tier 1 記述子それぞれについて、25 / 50 / 75 パーセンタイルで切った「以下」側を文脈とする。
「以上」側は補集合であり、別文脈として二重計上しない。

#### 5.1.3 重複排除の手順

```text
1. 全文脈ペアの Jaccard を計算する
2. Jaccard ≥ 0.9 のペアを連結成分としてまとめる
3. 各成分から代表を1つ選ぶ。選び方は「サイズ最大、同点なら文脈 ID の辞書順先頭」
4. 除外した文脈は代表への参照とともに記録する（削除しない）
```

較正データでは 270 文脈のうち 104 が近重複を持っていた。

#### 5.2 翻訳

Tier 3 由来の文脈を Tier 1/2 の語へ翻訳する。

```text
1. 目的変数を「文脈 C に属するか否か」の二値とする
2. 説明変数を Tier 1 記述子に限定する
3. 正則化ロジスティック回帰を 3-fold CV で当てる
4. 判別に寄与する記述子とその方向を取り出す
5. AUC < 0.70 なら「翻訳不能」とする
```

較正データでは AUC 中央値 0.96、99% が 0.70 以上だった。**翻訳が Finding を殺す心配は無い。**
ただし別プロジェクトでは異なりうるため、翻訳不能率を必ず報告すること。

### 段階6: L2b（主力レンズ）

**最初に実装するレンズ。** ドライランで最も強い信号を示した（enrichment 2.07〜2.54）。

#### 6.1 フラグメント寄与

```text
系列 s における化合物 i の Endpoint   y_si
系列平均                             ȳ_s
フラグメント F の寄与  contrib(F) = mean over s of (y_si − ȳ_s)   where frag(i) = F
```

**系列平均を引く操作が骨格主効果を除去する。** これが L2b が機能する理由であり、
L3 / L6 が機能しない理由でもある（本書 6.7 節）。

#### 6.2 検定

2つの問いを別々に検定する。

| 問い | 検定 |
|---|---|
| フラグメント F は一貫した効果を持つか | contrib(F) の平均が 0 と異なるか |
| **F の効果は文脈で変わるか** | contrib(F) の文脈間分散が帰無を超えるか |

較正データでは文脈間 SD の中央値が 0.16（ノイズ 0.10〜0.14 をわずかに超える程度）。
**フラグメント寄与は文脈をまたいでかなり一貫している。** 文脈依存を示すのは上位1割程度である。
2番目の問いで候補が少ないことは異常ではない。

#### 6.3 検定統計量を次で固定する

**問い1: フラグメント F は一貫した効果を持つか**

```text
観測値   t = mean(contrib_F) / (sd(contrib_F) / sqrt(m))     m = F が現れる文脈数
帰無     系列内で Endpoint を並べ替え、同じ t を再計算する
p        (1 + #{|t_perm| >= |t_obs|}) / (1 + B)
```

**問い2: F の効果は文脈で変わるか**

```text
観測値   v = var(contrib_F)                                  文脈間分散
帰無     系列内並べ替えで同じ v を再計算する
p        (1 + #{v_perm >= v_obs}) / (1 + B)
```

較正データでは文脈間 SD の中央値が 0.16（ノイズ 0.10〜0.14 をわずかに超える程度）。
**問い2 で候補が少ないことは異常ではない。** 文脈依存を示すのは上位1割程度である。

#### 6.4 適用範囲と境界条件

| 条件 | 扱い |
|---|---|
| F が 1 文脈にしか現れない | **除外。** 較正データでは 392 中 241（62%）がこれ |
| F が 2 文脈 | 問い1 のみ（問い2 は分散が推定できない） |
| F が 3 文脈以上 | 問い1・問い2 の両方 |
| 系列に Endpoint 有効化合物が 2 未満 | その系列を寄与計算から除外する |
| contrib の分散が 0 | t が発散する。p = 1 として扱い候補にしない |

#### 6.5 環の比較への適用

**環系置換の変換は 1,434 種類に散って検定不能だが、環そのものは多数の文脈に現れる。**
したがって環を variable フラグメントとして同じ枠組みに載せる。

```text
系列 = 環系を除いた残り（constant）
フラグメント = 環系
```

末端置換の系列とは別の系列集合として扱い、**混ぜない**。多重比較の族も分ける。

### 段階7: 残りのレンズ

> **2026-09-19本番訂正:** 現行L5は統計手続きの形は実装したが、同じcontext×feature相関をcontext pairごとに再計算し、`--workers`を実計算へ接続していない。961化合物・64コア・755 GiB RAMの専用機で実質1コアのまま8時間以上継続したため、本節の受入は撤回する。Boolean context membership matrix、相関表の一回計算、符号集合からの候補生成、checkpoint可能なparallel taskへ再設計する。詳細は[`CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md`](CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md)を参照する。

> **横断監査追補:** L1b、L2a、L2b、L7もworker未接続である。L4はCPU予算を候補Descriptionへ伝播しD016/D019を明示並列化するが、generation/scoreとDescription space間は逐次である。ただしL5以外の本番律速は未計測であるため、一律に再実装せず、Lens別baselineと複数prototypeを比較して変更範囲を決める。同文書6章の「問題ないこと／確認済み課題／未確認リスク／第一候補案」を区別する。

優先順に実装する。

| 順 | レンズ | 実装の要点 |
|---|---|---|
| 1 | L5 | 同一分割軸から生じた文脈ペアに限定（総当たりは爆発する）。Fisher z 差検定 |
| 2 | L1b | 文脈内の λ。帰無は骨格内並べ替え。**歩留まりは悪いが信号はある** |
| 3 | L2a | 3ペア以上を持つ変換のみ。平均シフトと**分散縮小**を独立に検定する |
| 4 | L7 | 共通 R 基 m ≥ 5 のみ。m=3 では Spearman に検出力が無い |
| 5 | L4 | 下側信頼限界 × 密度ギャップ × 到達可能性。到達可能性は L2 の変換 DB を参照 |

#### 7.1 L2a の分散縮小を落とさないこと

平均シフトだけを検定すると、「Global では効果が散るが層別すると揃う」という知見を取り逃がす。
層ごとの効果が正負に散れば平均は 0 になり、平均シフト検定では検出されない。
**独立に検定すること。**

#### 7.2 L4の計算量を開始前に拘束すること

L4は全生成候補を無条件に全Tier 1/2空間へ流してはならない。Description実行前に、到達経路数、変換の観測pair支持数、到達元化合物数、candidate IDの順で決定論的に順位付けし、既定100候補へ制限する。既定のTier 1/2空間数9に対し候補Description行数のhard上限を900とし、さらにcost classを`low=1, medium=4, high=16, very_high=64`で重み付けしたcost unitsのhard上限を10,000とする。いずれかの上限を超える設定ではsubprocessを起動せず`needs_design_review`とする。生成総数、選択数、cap除外数、空間数、予定行数、cost class別行数、cost unitsをmanifestへ記録する。

このcapは無作為subsampleではなく、観測された到達可能性の支持が強い候補を優先する解析母集団の定義である。値を変更する場合はresolved configを新しく作り、Run中の自動変更は禁止する。

### 段階8: Phase 4 スコアリング

```text
足切り:  statistical_strength ≥ θ₁  AND  robustness ≥ θ₂
順位:    composite = non_triviality × actionability × frontier_relevance
```

**加重和ではなく足切り＋積を使う。**

較正データでは交絡（MW/logP/TPSA）が説明する Endpoint 分散は 7% のみだった。
したがって **`non_triviality` は多くの Finding で 1 に近くなり、強い識別軸にならない**。
順位付けは `actionability` と `frontier_relevance` が主に担う。

#### 8.1 5軸の算出式を次で固定する

```text
statistical_strength
    レンズ内で q 値の昇順に順位を付け、1 - (rank - 1) / n_candidates_in_lens
    → [0, 1]。レンズを跨いで比較可能にするための正規化であり、q の絶対値は使わない

robustness
    ブロック単位 bootstrap（B=200）で、主張の方向と p ≤ 0.05 が保たれた反復の割合
    → [0, 1]

non_triviality
    E_raw = 効果量（レンズ固有。L2b なら mean(contrib_F)）
    E_adj = MW / cLogP / TPSA / 骨格ダミー を回帰で落とした後に残る効果量
    non_triviality = clip(E_adj / E_raw, 0, 1)
    E_raw = 0 のときは 0 とする

actionability
    1.0  具体的な化合物 ID と適用する変換・フラグメントが両方一意に定まる
    0.6  最適化の方向は定まるが対象化合物が一意でない
    0.2  記述のみ。次の一手を示さない
    → 下限を 0 にしない。積で完全に消えることを避けるため

frontier_relevance
    y_med  = 観測 Endpoint の中央値
    y_top  = 観測 Endpoint の 95 パーセンタイル
    y_reach = この Finding が示唆する一手を適用したとき到達しうる Endpoint
              = max over 関与化合物 c of ( endpoint(c) + 推定効果量 )
    frontier_relevance = clip( (y_reach - y_med) / (y_top - y_med), 0, 1 )
    → 一手を示さない Finding（actionability 0.2）は 0.5 を代入する
```

較正データでは交絡が説明する Endpoint 分散は 7% のみだった。
したがって **`non_triviality` は多くの Finding で 1 に近くなり、強い識別軸にならない**。
順位付けは `actionability` と `frontier_relevance` が主に担う。

#### 8.2 足切り水準

θ₁ / θ₂ は実データで候補プールのサイズを見てから決める。**初期値は次とする。**

```text
θ₁ = 0.5（レンズ内パーセンタイル）
θ₂ = 0.7（bootstrap で主張が保たれた割合）
```

**初期値で上位 K=10 を埋められない場合は θ を下げる前に設計担当へ報告すること。**
候補が枯れる原因が閾値ではなくレンズの実装誤りである可能性がある。

#### 8.3 レンズ間で重複する Finding の統合（C-1 の決定）

同じ現象を L2b と L5 が別々に検出しうる。K=10 という狭い枠では実害が大きい。

```text
2つの Finding を重複とみなす条件:
    entities を 2 つ以上共有する
    かつ claim.subject_type が同じ

処理:
    composite スコアが高い方を残す
    低い方に merged_into = <残った Finding の ID> を記録し、削除しない
```

### 段階9: Phase 5 深堀

[`design/deep_dive_protocol.md`](design/deep_dive_protocol.md) のとおり実装する。

**子問いは自由記述させない。** テンプレート T01〜T10 からの選択とパラメータ埋めに限定する。

`T01`（部分集合分割）の化学的分割軸のうち、次は機械的に算出する。

- 骨格クラス、置換基サイズ、極性、環の有無、立体化学
- **置換基の電子効果**: Hammett σ のルックアップ → 無ければ Gasteiger 部分電荷 → 任意で xTB 電荷
- **置換位置**: 骨格ごとの attachment index 正規化

**プロジェクト固有 SMARTS パターン**は人間が与える。**相互排他を前提としないこと。**
パターン A がパターン B の部分集合であるケースがある。各パターンを独立な二値フラグとして扱い、
包含関係を機械検出して階層的に多重比較補正を行う。

#### 段階9-1 状態判定は決定論とする（C-4 の決定）

**LLM に状態を判定させない。** 再現性が失われ、監査の根拠が崩れるためである。
次の規則で機械的に決める。

```text
親 Finding の効果量 E_parent、方向 D_parent（符号）

SURVIVED       子検定の q ≤ 0.05 かつ 効果の符号が D_parent と一致
WEAKENED       部分集合 A で q ≤ 0.05 かつ符号一致、
               補集合 B で q > 0.05 または |効果| < 親の 50%
               → 主張を「A に限る」へ精緻化する
REFUTED        子検定の q ≤ 0.05 かつ 効果の符号が D_parent と**逆**
INCONCLUSIVE   上記のいずれにも当たらない。
               典型は n が検定の下限に満たない、または q > 0.05 で部分集合構造も無い
```

LLM が担うのは次の3つだけである。

| 判断 | 入力 | 出力 |
|---|---|---|
| どのテンプレートをどのパラメータで呼ぶか | 親ノードの主張と既実行テンプレート一覧 | テンプレート ID とパラメータ（最大3、0 可） |
| 木全体の narrative 要約 | 深堀木と引用可能行 | 引用付きの短い文章 |
| Finding 間の関連付け | エンティティを共有する Finding 群 | 統合 narrative |

#### 段階9-2 予算の消費規則

```text
検定実行回数は「決定論層が実際に検定を走らせた回数」で数える
LLM がテンプレートを選んだが n 不足で実行できなかった場合も 1 回と数える
（同じ選択を繰り返して予算を浪費させないため）
```

#### 段階9-3 条件付け深度は 1 とする

**単一条件のみを文脈として使う。条件の組合せ（C₁ ∧ C₂）を作ってはならない。**

```text
深度1   単一条件           C₁                                   ← 実装する
深度2   異なる軸の組合せ    C₁ ∧ C₂（例: クラスタ ∧ logP 分位）   ← 実装しない
```

理由は次の2点である。

- 較正データで深度1の文脈が 270 あり、重複排除後でも十分な数がある
- 深度2は文脈数が組合せで増えて多重比較の族が膨らむ一方、有効性が未測定である

**深度2は 0.2.2 の検討事項である。** 仕様概要書の決定事項7 も同じ内容になっている。

`Finding.claim.condition_depth` フィールドは残す（0.2.2 での拡張に備える）が、
0.2.1 では常に 1 を書き込むこと。

### 段階10: Phase 6 統合と報告

#### 10.1 統合はエンティティ共有グラフによる

```text
1. 各 Finding が参照するエンティティを抽出する
2. エンティティを共有する Finding 間に辺を張る
3. 連結成分を取り出す
4. 成分ごとに LLM が1段落の統合 narrative を書く（引用強制）
```

#### 10.2 引用検証

次の4点を機械検証する。

```text
1. narrative 内に現れる全ての数値トークンが、citations の指す行に存在するか
   （正規表現で数値を抽出し、対象行の値と照合。丸め誤差は相対 1% まで許容）
2. 引用された compound_id / pair_id が Run 内に実在するか
3. 引用された table_ref のファイルが実在し、行番号が有効範囲内か
4. Finding.test の p 値・q 値が、対応する検定結果ファイルの値と一致するか
```

**1件でも不整合があれば Phase 6 を失敗させる。報告を自動修正しない。**

不整合時のエラーには「どの narrative のどの数値が、どの引用行と一致しなかったか」を
必ず含めること。LLM の再生成で直せるようにするためである。

#### 10.3 LLM の役割

| 担当 | 内容 |
|---|---|
| 決定論層 | 発見、順位付け、閾値、検定手法の選択、数値の算出 |
| LLM | 説明、接続、深堀の分岐選択、narrative 要約 |

**LLM に発見も順位付けもさせない。** 前提は Local LLM（27B クラス、オフライン）である。
深堀状態は段階9-1のpure functionが決定し、LLMには判断させない。

providerが実装するtaskは `select_deep_dive`、`summarize_deep_dive`、`compose_component_narrative` の3種類に固定する。共通system prompt、task別prompt、空/null応答、引用marker、JSONL stdoutの制約は [`prompt/CONDUCTOR_0.2.1_prompts.md`](prompt/CONDUCTOR_0.2.1_prompts.md) 5章を実装契約とする。

### 段階11: Runtime

0.1.x の Runtime 思想（State/DAG の唯一の Writer、Execution Request、Lease、監査）は健全である。
ただしコードは流用せず再実装する。Phase 構成が変わっているためである。

---

## 7. テスト戦略

| 層 | 内容 |
|---|---|
| 単体 | 各関数。特に Fragment engine の3クラス分解 |
| 契約 | JSON Schema 適合、Finding 必須フィールド、引用検証 |
| 回帰 | 合成データでの決定論的再現 |
| **較正再現** | **本書 8章。最重要** |

合成データ生成器は `CONDUCTOR_modules/diagnosis/diagnosis/inputs.py` の
`make_synthetic_dataset()` を流用できる。3部品構成（置換基 — 中央フェニル — 末端環）で、
変換3クラスすべてが成立するよう作ってある。

---

## 8. 受け入れ基準 【実測値の再現】

**通常の実装計画と違い、本プロジェクトには実装前の実測値がある。**
診断モジュールを較正データへ適用した結果を、本実装が再現しなければならない。

較正データで実装を走らせ、次を確認する。

**基準の意図は「診断が信号を見つけた所で実装も信号を見つけ、見つけなかった所で見つけないこと」**
であり、数値の厳密一致ではない。手続きが違えば数値はずれる（確認事項 Q-005 の回答）。

| 項目 | 基準 | 較正での実測値（参考） |
|---|---|---|
| L2b の enrichment | **> 1.5** | 2.07 / 2.31 / 2.54 |
| L5 の enrichment | **> 1.5** | 2.19 / 1.82 / 1.81 |
| L1b の enrichment | **1.1 〜 1.8** | 1.45 / 1.43 / 1.29 |
| L3 / L6（実装した場合） | **1.0 ± 0.15** | 1.02〜1.08 / 0.98〜1.01 |
| 変換3クラスの pair 数 | TERM 9,548 / RING 1,579 / LINK 436 | ±10%。**RING は減少しうる**（4.3 の制約を各 fragment へ個別適用するため） |
| 文脈数（診断互換 subset） | 270 | ±20% |
| 翻訳 AUC 中央値 | 0.96 | ≥ 0.90 |

許容幅が広いのは、診断のスクリーンが簡約版であり、本実装はより厳密だからである。
**桁が違う、あるいは enrichment が 1.0 に落ちる場合は実装の誤りを疑うこと。**

特に次を確認する。

> **L1a / L3 / L6 を実装した場合、enrichment が 1.0 付近になるはずである。**
> これらをレンズとして復活させてはならない。

### 8.1 並べ替え実装の検証

L5 で次を確認する。**並べ替え実装の正しさを最も鋭く検出する。**

```text
骨格内並べ替えの帰無  ≈ 148（観測 325 に対し enrichment 2.19）
全体並べ替えの帰無    ≈ 3   （enrichment 100 倍に見える）
```

全体並べ替えの値が出たら、ブロック並べ替えが機能していない。

---

## 9. 実装前に確認を要する事項

以下は初期計画時に実装前確認として列挙した記録である。設計回答は実装詳細仕様書へ反映済みであり、現在の正式受入残件ではない。将来ここへ影響する変更を行う場合は、**実装者が独断で決めず、設計担当へ確認すること。**

| # | 項目 | 誰が決めるか | 理由 |
|---|---|---|---|
| 1 | **プロジェクト固有 SMARTS パターン** | **人間（外部提供）** | 初期実装は機械算出の分割軸だけで動かせる。後から追加可能 |
| 2 | θ₁ / θ₂ の最終値 | 実装後に設計担当 | 候補プールの実サイズを見てから決める。初期値は 8.2 節 |
| 3 | **L1b を最終的に残すか** | 実装後に設計担当 | enrichment 1.3〜1.5、FDR 70〜77%。下流の選別で救えるかは実装後でないと分からない |
| 4 | Similar core 緩和の効果 | 実装者が実測して報告 | 診断で skip された。実装後に数値を出す |
| 5 | Runtime の Phase 境界とチェックポイント | 実装者が設計して提案 | DAG 設計時に詰める |

**上記以外は本書で決定済みである。** 迷いが生じたら本書と
[`design/calibration_results.md`](design/calibration_results.md) を確認し、
それでも決まらない場合のみ設計担当へ問い合わせること。独断で決めない。

### 9.1 本計画で新たに決定した事項

設計協議で保留されていたもののうち、本書で決定したもの。

| 元の番号 | 項目 | 決定 | 記載箇所 |
|---|---|---|---|
| C-1 | レンズ間で重複する Finding | entities を2つ以上共有し subject_type が同じなら重複。高スコア側を残す | 8.3 |
| C-4 | 深堀の状態判定 | **決定論とする。** LLM に判定させない | 段階9-1 |
| C-6 | 深度2条件 | **0.2.1 では実装しない** | 段階9-3 |
| C-7 | `frontier_relevance` の式 | 8.1 に明示 | 8.1 |
| C-12 | 環系置換の N≥3 対応 | N≤4 かつ一意/対称等価のみ採用。N≥5 は除外 | 4.4 |
| C-2 / C-3 | L4 の領域定義と到達可能性 | L4 は実装順序の最後。仕様は 7章の表のとおり | 7 |
| D-4 | 距離計量 | fingerprint は 1−Tanimoto、記述子は標準化ユークリッド | 5.1.1 |

---

## 10. 進め方

以下は実装時に適用した順序の記録である。段階11と実装適合性確認は完了しており、現在の次工程はStage 11実装報告書に記載した正式較正・本番相当確認である。

段階6（L2b）を終えた時点で **一度止めて 8章の enrichment 検証を報告すること。**
そこで実測値を再現できなければ、残りのレンズを実装しても無駄になる。

その後は段階7〜11 を順に進め、段階10 を終えた時点で全体の enrichment 検証を再度行う。

---

## 11. 補足: 運用プロンプト集

### 11.1 成果物

0.2.1の正式プロンプト集を [`prompt/CONDUCTOR_0.2.1_prompts.md`](prompt/CONDUCTOR_0.2.1_prompts.md) として版管理する。0.1.xのpromptをコピーして使わない。0.1.x Runtimeに固有のRound承認、旧Node名、旧Analysis ID、On-demand操作は0.2.1 promptへ持ち込まない。

プロンプト集は最低限、次を含む。

1. 状態のread-only確認
2. 入力と既存Description Databaseのread-only Preflight
3. offline providerの3タスクprobe
4. 既存Databaseを再利用する新規本番Run
5. 同一Program・別Endpointの新規Run
6. 較正データによる正式受入Run
7. 中断Runの安全な再開
8. 完走結果と引用のread-only監査
9. Failed Node、record無効化、LLM失敗の特別対応
10. 3種類の内部LLM task prompt

### 11.2 実装境界

運用プロンプトはMain Agentへの権限と停止条件を明示する。read-only promptからNode実行、Run state変更、Database更新へ進んではならない。新規Run promptは、明示されたProgram、Endpoint、入力、設定、Run rootの範囲だけを実行権限とする。

内部LLM promptはprovider実装の入力であり、文書だけではPhase 5/6を実行できない。正式較正・本番相当確認の前に、`llm.command`を設定したoffline providerへ3タスクのfixtureを送り、次を検証する。

本番構成では、Ubuntu CPU機上の`CONDUCTOR_modules/local_llm_provider/`を、別GPU機上の承認済み`vllm serve` OpenAI互換APIへ接続する参照実装とする。全ての決定論的計算はCPU機で行い、GPU serverはLLM推論だけを担当する。擬似OpenAI互換serverによる契約testは許容するが、正式受入前にはCPU機から実vLLM modelへ3タスクを各1回probeする。

- request 1行に対してresponse JSON objectが1行だけ返る
- `request_id`が保持される
- `llm_response.schema.json`へ適合する
- 選択templateとparameterがevidence内に限定される
- narrativeの`[[citation_id]]`と`citations`配列が一致する
- 根拠不足時に空の`selections`または`null` narrativeを返せる
- stdoutへログやMarkdownが混入しない
- timeout、process failure、schema違反が設定回数だけ再試行される

### 11.3 既存Databaseを使う本番移行手順

1. 同じProject rootの `data/description_database/<PROGRAM_NAME>/` をread-onlyで監査する。
2. schema version、calculation version、calculation signature、canonical SMILES整合性をDescription別に確認する。
3. 初回書込み前にwriter不在を確認し、SQLite backup APIでバックアップする。
4. 互換recordはhitとしてそのまま使い、missだけを計算・登録する。
5. 0.1.x Run Artifactを移行せず、0.2.1のRun root、Execution Request、Pipeline planを新規作成する。
6. Phase 1〜6完了後、hit/miss/registered件数、LLM失敗率、引用検証結果を監査記録へ残す。

古いDatabaseがschema version `1.0.0`でない場合、または現行Capabilityより前の契約で作成されている場合は無条件に再利用しない。変換処理をその場で発明せず、read-only調査結果を設計担当へ報告する。

### 11.4 事前確認済み本番Runの決定論的開始経路

3.4AではMain AgentにPipeline planやExecution Requestを設計させない。`cs-production-run`を正式な本番開始Skillとし、利用者が用意する単一の`run_spec.json`を、版管理された`CONDUCTOR_modules/pipeline/production_pipeline.v0.2.1.json`へ決定論的に展開する。

実装物は次のとおりとする。

- `.claude/skills/cs-production-run/`: receipt検証、固定DAG compile、Runtime委譲
- `CONDUCTOR_modules/schemas/run_spec.schema.json`: 入力、Program、Endpoint、config、provider config、Run root、CPU/memory上限の単一入力契約
- `CONDUCTOR_modules/schemas/preflight_receipt.schema.json`: 3.2A、3.2B、3.3の合格証跡
- `CONDUCTOR_modules/schemas/pipeline_plan.schema.json`: compile済みDAG契約
- `CONDUCTOR_modules/tools/create_preflight_receipt.py`: 合格済みPreflightをscope/hashへ結び付けるCLI
- `CONDUCTOR_modules/tools/production_run.py`: 13 NodeのRequestとPipeline planを生成するcompiler/launcher

3件のreceiptは同じRun Spec、入力CSV、Endpoint registry、resolved config、provider config、固定Blueprint、実装fingerprint、Ubuntu hostname、CPU affinityへ結び付ける。Run Specまたは実装を変更した場合はhash不一致として拒否し、古い合格判断を流用しない。

3.4A開始時に再確認するのは、receipt整合性と次の最小guardだけとする。

1. 入力/config/provider configが読め、resolved configに非空の`llm.command`がある。
2. `data/description_database/<PROGRAM_NAME>/`が存在しない。
3. Run rootが存在しない。
4. ProgramとRun rootの排他lockを取得できる。
5. `workers`が現在のCPU affinity以下である。

合格後は確認待ちを挟まず、固定DAGを`cs-runtime`へ渡す。request templateの手作業、Skill契約の再抽出、fixture plan探索、Runtime sourceの再調査は本番開始手順に含めない。これらはBlueprintまたは契約を変更する開発時だけ行う。

Runtimeは`node://<node>/<role>`に加え、Reportが親NodeのManifestを引用検証へ渡すための`manifest://<node>`を解決する。両参照ともPipeline planで宣言された依存Nodeかつ`succeeded`状態に限定する。

本番処理の全体像は[`images/CONDUCTOR_0.2.1_process_overview.png`](images/CONDUCTOR_0.2.1_process_overview.png)を社内説明用の基準図とする。`llm.command`の実行契約の正本は、本計画11.2節、実装詳細計画書のLocal LLM節、`llm_request.schema.json`/`llm_response.schema.json`、および`local_llm_provider/provider.py`であり、プロンプト集は運用手順を示す。
