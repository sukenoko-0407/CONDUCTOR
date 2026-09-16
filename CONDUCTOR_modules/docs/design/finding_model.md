# Finding モデル

Status: **設計協議中。未承認・未実装。**

親文書: [`../CONDUCTOR_0.2.1_specification_overview.md`](../CONDUCTOR_0.2.1_specification_overview.md)

## 1. なぜ Finding が出力単位か

0.1.x の出力単位は「analysis unit × operator の節」だった。24 unit × 7 operator ≈ 168 節が、中身の有無にかかわらず必ず埋まる構造である。仕様が「0件でも参考・基準未達を1件表示する」と命じていたのは、**格子を必ず埋める設計**だったからである。

> 均一な網羅は、中身が無いときには均一な薄さになる。

0.2.1 では出力単位を **Finding** とする。Finding は主張・検定・反証条件・自明性・引用を持つ構造体であり、互いに順位を競う。大半は捨てられ（ただし削除はされず）、生き残りだけが上位に出る。

**良い Finding が3件なら、レポートは3件になる。** 168節にはならない。

## 2. スキーマ

```yaml
finding_id: F000042
lens: L2                      # どのレンズが生成したか

claim:                        # 主張。型に従う
  subject_type: transformation  # transformation | compound | space | feature | cluster | region
  subject_id: T_00871
  condition_id: CTX_00213     # 条件 C。複合条件なら配列
  condition_depth: 1          # 0.2.1 では常に 1。深度2は 0.2.2 の検討事項
  effect_direction: positive  # positive | negative | emergent | flip
  effect_size: 0.62           # 単位はレンズ依存（log unit / λ / r / odds ratio）
  effect_unit: log_endpoint
  support_n: 7

test:
  method: interaction_permutation
  statistic: 0.59
  p_value: 0.003
  q_value: 0.04               # BH 補正後
  null_model: size_matched_random_subset  # 帰無分布の構成法
  null_iterations: 1000

falsification:                # 反証条件。機械評価可能であること
  type: label_permutation
  parameters: {...}
  threshold: "効果が帰無分布の上側 5% に収まらなければ棄却"

triviality:
  confounders_tested: [MW, cLogP, TPSA, scaffold_class]
  adjusted_effect_size: 0.48
  verdict: notable            # trivial | notable

translation:                  # 条件 C の Tier 1/2 語への翻訳
  status: translated          # translated | untranslatable
  discriminator_auc: 0.87
  description: "芳香環数 ≥ 3, TPSA 60-90, 塩基性窒素を持つ"
  structural_overlap: low     # Murcko/MCS クラスと一致するか

entities:                     # Phase 6 の統合で Finding を連結する鍵
  context_ids: [CTX_00213]
  scaffold_ids: [SCF_007]
  transformation_ids: [T_00871]
  compound_ids: [CPD-0231, CPD-0447]
  feature_ids: [D019::homo_lumo_gap]

citations:                    # 行レベルの引用。narrative の全主張はここを指す
  compound_ids: [CPD-0231, CPD-0447, ...]
  pair_ids: [MMP-01823, ...]
  table_refs: ["L2_interaction.csv#row_871", ...]

scores:
  statistical_strength: 0.91  # 型内パーセンタイル
  robustness: 0.78            # bootstrap 安定性
  non_triviality: 0.77
  actionability: 1.0
  frontier_relevance: 0.83
  composite_rank: 3

state:
  pipeline: reported          # candidate | screened_out | ranked | reported
  deep_dive: weakened         # survived | weakened | refuted | inconclusive | not_dived

labels: [novel, actionable]

deep_dive_summary: {...}      # 子ノードの要約。詳細は別 Artifact
narrative: "..."              # 引用付きの短い文章
```

## 3. 型

Finding は次の5要素を必ず持つ。欠けるものは Finding として成立しない。

```text
主張      [対象] は [条件] のとき [効果] を示す
検定      どの統計手続きで確かめたか
反証条件  何が観測されたらこの主張は棄却されるか
自明性    既知の軸（MW / logP / TPSA / 骨格）で説明できるか
引用      どの表のどの行が根拠か
```

**型が LLM の出力制御と検定の自動化を同時に担う**のが設計の要点である。型に従わない出力は構造的に生成できず、型に従った出力はそのまま機械検定の仕様になる。

## 4. 反証条件

### 4.1 なぜ必須か

反証条件を書けない主張は、検定に回す前に棄却する。これは弱いモデルに対して驚くほどよく効く拘束具であり、「なんとなくそれっぽい文章」を構造的に排除できる。

同時に、反証条件はそのまま決定論層の検定仕様になる。**人間の言葉と機械の手続きを一つのフィールドで繋ぐ。**

### 4.2 反証条件の文法

自由記述させない。次の4型のいずれかとし、パラメータを埋める形とする。

| 型 | 内容 | 対応する検定 |
|---|---|---|
| `label_permutation` | 条件ラベルを無作為に置換しても同等の効果が出るなら棄却 | 置換検定 |
| `subset_removal` | 特定の部分集合（骨格・外れ値・単一化合物）を除くと効果が消えるなら棄却 | 逐次除去 |
| `parameter_perturbation` | 近傍サイズ k や閾値を変えると結論が変わるなら棄却 | パラメータ走査 |
| `resampling` | bootstrap 再抽出で方向・有意性が保たれないなら棄却 | bootstrap |

レンズごとに既定の反証型を定める。

| レンズ | 既定の反証型 |
|---|---|
| L1 条件付き平坦性 | `label_permutation`（同サイズランダム部分集合） |
| L2 変換 × 文脈 | `label_permutation`（文脈ラベル置換） |
| L3 局所逸脱 | `parameter_perturbation`（k 変更）＋ `subset_removal`（近傍から当該化合物を除く） |
| L4 未踏領域 | `subset_removal`（構築可能性・既存一致の確認） |
| L5 符号矛盾 | `label_permutation`（文脈ラベル置換） |
| L6 濃縮クラスタ | `label_permutation`（クラスタラベル置換） |

## 5. 状態

### 5.1 パイプライン状態

```text
candidate     段階A（レンズ別スクリーン）を通過した
screened_out  段階Bの足切りで落ちた。削除はしない
ranked        段階Bの順位付けで上位 K 件に入った
reported      Phase 6 で報告に載った
```

### 5.2 深堀の判定

```text
survived      全ての子問いが主張と整合
weakened      一部の子問いが境界条件を発見した
refuted       子問いが主張と直接矛盾する結果を出した
inconclusive  サンプル不足等で判定不能
not_dived     深堀対象に入らなかった（上位 K 件の外）
```

**`weakened` は失敗ではない。** 「この変換が効くのは文脈 C のうち電子求引基を持つサブセットに限る」という結果は、主張の**精緻化**であり、多くの場合むしろ元の主張より有用である。報告時にもそのように扱う。

`refuted` が出た Finding は報告から外すが、削除せず理由付きで保持する。何が棄却されたかは診断情報である。

## 6. ラベル

スコアとは別に、Finding の性質を示すラベルを付与する。

| ラベル | 意味 |
|---|---|
| `novel` | 構造空間では見えず、非構造空間でのみ検出された |
| `known_confirmed` | 構造空間でも見える。化学者が既に知っている可能性が高い |
| `trivial` | サイズ・脂溶性等の既知軸で説明できる |
| `actionable` | 具体的な次の一手（化合物 ID・変換）が一意に定まる |
| `untranslatable_context` | 条件が Tier 1/2 の語へ翻訳できなかった |
| `frontier` | 示唆する一手が観測済み上位活性域に届く |
| `tolerance` | 変換しても Endpoint が変わらない（分散が小さい場合のみ） |
| `selection_biased` | 使用した Endpoint に系統的欠測が検出されている |

### `known_confirmed` を出す理由

既知の知見が Finding として出ることは**許容し、むしろ価値として扱う**。系が正しく較正されていることの証明になり、Module 自体の信用に繋がる。

ただし既知の知見だけを提示するのでは意味がないため、スコアリングでは `novel` を優先する。両方を出し、ラベルで区別する。

## 7. 引用規則

### 7.1 原則

> narrative 内の全ての主張は、`citations` の行を指さねばならない。

監査可能性は**決定論からではなく、引用の検証可能性から**得る。これにより LLM に判断させつつ、根拠のない主張を機械的に落とせる。

### 7.2 検証

Phase 6 で次を機械検証する。

1. narrative 内の全ての数値が `citations` の指す行に存在するか
2. 引用された compound_id / pair_id が Run 内に実在するか
3. 引用された table_ref が実在し、行番号が有効か
4. `test` の p 値・q 値が対応する検定結果と一致するか

1件でも不整合があれば Phase 6 を失敗させる。**報告を自動修正しない。**

### 7.3 副次的効果

引用強制は監査のためだけの仕組みではない。**弱いモデルの脱線を防ぐ拘束具**として実用的に効く。引用可能な範囲でしか書けない、という制約が、27B クラスのモデルの出力品質を実質的に押し上げる。

## 8. 保持方針

> **何も削除しない。**

| 対象 | 扱い |
|---|---|
| 段階Aで落ちた候補 | 集計のみ保持（件数と落ちた理由の分布） |
| 段階Bの足切りで落ちた候補 | 全件を理由付きで保持（`screened_out`） |
| `trivial` とラベルされた Finding | 保持。既定表示には出さない |
| `refuted` となった Finding | 保持。棄却理由を記録 |
| `untranslatable_context` | 保持。多数を占める場合は特徴量設計の診断情報として報告 |

表示は上位 K 件が既定である。全件は CSV / JSON から辿れる。

0.1.x の反省として、**「該当なし」を埋めるために near-miss を1件表示する**ような運用はしない。該当が無ければ件数を示すだけでよい。

## 9. 未決事項

1. Finding ID の採番規則（Run 内通番か、レンズ別か）
2. （0.2.2 送り: 複合条件（深度2）の `condition_id` 表現）
3. レンズ間で重複する Finding の統合規則（同じ現象を L2 と L5 が別々に検出した場合）
4. `effect_size` をレンズ横断で比較可能にする正規化の要否
5. narrative の長さ上限
6. 反証条件のパラメータ既定値（各型ごと）
7. `entities` に含めるべき種類が上記5つで十分か

集約は [`open_questions.md`](open_questions.md)。
