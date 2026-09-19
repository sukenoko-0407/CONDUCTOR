# CONDUCTOR 0.2.1 R1 修正計画書

Status: **協議中。未承認。**
作成日: 2026-09-19
改訂: **R1.1（2026-09-19）。全レンズへ拡張し、未確定事項をゼロにした。**

> **R1.1 での変更点**
> - 本番定数が確定した（64コア / 700 GiB / 専有、Mordred 1800列）。
> - **L4 に潜在的なメモリ欠陥を発見した**（M-12）。候補 cap の引き上げを塞いでいる。
>   **本番で観測された KILL は L5 であり L4 ではない**（第1.3節）。
> - **L1b と L2a にも計算量と族の欠陥があることを実測で確認した**（M-10 / M-11）。
>   初版の「測定するまで L5 以外を変更しない」方針は取り下げる。
> - L2b と L7 は測定の結果、**変更しないと決定した**（推測ではない）。
> - 予算値（`max_units` / メモリ / 進捗間隔 / L4 cap）を**すべて確定した**（M-14）。
> - **実機測定を前提とする項目は残っていない。**

対象読者: **本設計の議論に参加していない実装担当者。**

委任表現（「適切に判断する」「必要に応じて」）を使わない。決められないものは「確認を要する」と明示する。

---

## 0. 読む順序

| 順 | ファイル | 理由 |
|---|---|---|
| 1 | 本書 | 何を変えるか |
| 2 | `CONDUCTOR_0.2.1_scale_measurement_report.md` | **全数値の根拠。実測値である** |
| 3 | `CONDUCTOR_0.2.1_specification_overview.md` の **【R1】【R1.1】** 箇所と **R1-1〜R1-17** | 改訂された契約 |
| 4 | `CONDUCTOR_0.2.1_spec_conformance_audit.md` | なぜこうなったか |
| 5 | `CONDUCTOR_0.2.1_independent_performance_review.md` | 性能面の詳細評価 |

**実装担当者は [`CONDUCTOR_0.2.1_R1_implementer_brief.md`](CONDUCTOR_0.2.1_R1_implementer_brief.md) から読み始めてください。** 本書はその正本として参照されます。

**R0 の実装計画書・詳細仕様書は引き続き有効である。** 本書は差分だけを定める。

---

## 1. 前提の確認

### 1.1 実装は仕様に適合していた

適合監査で有意な逸脱は見つからなかった。**本件は実装の不具合ではなく、仕様の欠陥である。**
実装担当者に責はない。

### 1.2 【R1.1】欠陥は L5 だけではない

全レンズを測定した結果を示す。詳細と根拠は `CONDUCTOR_0.2.1_scale_measurement_report.md`。

| Lens | 欠陥 | 現行 | 修正後（本機12コアで実測） |
|---|---|---|---|
| **L5** | 計算量 ＋ 族 | **7.43 時間** / 族 556,189 (k_min 11,113) | 7.3 分 / 族 52 (k_min 1.0) |
| **L1b** | 計算量 ＋ 族 | 0.44 時間 / 族 763 (k_min 15.2) | 0.5 分 / 族 84 (k_min 1.7) |
| **L2a** | 計算量 ＋ 族 | 0.65 時間 / 族 647 (k_min 12.9) | 1.6 秒 / 族 117 (k_min 2.3) |
| **L4** | **潜在メモリ欠陥** | cap 100 なら可。**cap 10,000 で 114.6 GiB** | 1.79 GiB / 1.2 分（cap 250,000 でも） |
| L2b | なし | 数分 / 族 75 (k_min 1.5) | **変更しない** |
| L7 | なし | 数十秒 / 族 86 (k_min 1.7) | **変更しない** |

> **L5 / L1b / L2a は、統計予算（k_min ≤ 10）を超過している。**
> **速くしても Finding はゼロのままである。統計を先に直す。**

### 1.3 【R1.1】L4 について正確に述べる

**本番で観測された KILL は L5 である。L4 ではない。**
L4 の 25万候補は是正報告 R-08 の guard で起動前に停止しており、この機構は正しく働いている。

ただし `l4.py:335` は `(候補 × 観測 × 特徴量)` の3次元配列を実体化しており、
**現行 guard はこのメモリを model していない**（見ているのは記述子の行数と cost unit だけである）。

> **結果として、候補 cap を 100 から上げた瞬間に guard を通過したまま OOM する。**

0.2.1 の目的は「中身の薄さ」の解消である。**cap 100 は L4 の出力を直接細らせている。**
700 GiB の専有機で cap を上げるのは自然な要求であり、**この欠陥がそれを塞いでいる。**

---

## 2. 実装しないもの

| 項目 | 理由 |
|---|---|
| **process 並列化（shard / resource token / mmap）** | 修正後の置換検定コストは全レンズ合計で本機12コア約10分。shard は決定性・checkpoint・BLAS thread との相互作用を増やし、**頑健性を下げる** |
| **shard checkpoint** | 修正後の最長 Node は L5 の 7.3 分。**最初からやり直せる時間であることを受入条件にする** |
| **B の引き上げ** | 族縮小後は B=1000 で k_min が全レンズ 1.0〜2.3。**引き上げ不要**（実測） |
| **特徴量重複排除を統計対策として扱うこと** | 実測で族はほぼ変わらない。計算量と可読性のためだけに行う |
| **L2b / L7 の変更** | **測定した上で不要と判断した**（族 75 / 86、k_min 1.5 / 1.7、計算量も予算内）。推測による据え置きではない |
| **L4 の候補 cap 引き下げ** | 現行 cap は 100 であり、引き下げる余地がない。**M-12 適用後は逆に引き上げ可能になる**（M-15、分離可能な判断） |
| **64コア機での再測定を前提とした設計判断** | 本測定は本番寸法そのままで行った上界である。**何を直すかは本書で確定する**（測定レポート第7節） |

---

## 3. 変更一覧

| ID | 変更 | 種別 | 対象 |
|---|---|---|---|
| **M-1** | 仕事量の事前見積もり契約 | 実装 | 全 Lens + Runtime |
| **M-2** | 長時間 Node の進捗報告 | 実装 | 全 Lens + Runtime |
| **M-3** | L5 の比較単位を「文脈 vs 軸内補集合」へ | **仕様変更** | L5 |
| **M-4** | L5 の BH 族を axis ごとに分割 | **仕様変更** | L5 |
| **M-5** | 相関表の一回計算（行列化） | 実装 | L5 |
| **M-6** | Tier 1/2 特徴量の重複排除 | **仕様変更** | **L5 のみ**（R1.1 で L1b を除外） |
| **M-7** | 較正設定 hash の記録と照合 | 実装 | Runtime |
| **M-8** | 本番設定での較正やり直し | 運用 | — |
| **M-9** | 受入基準へ計算量を追加 | 実装 | test |
| **M-10** | L1b の近傍表を一回計算、族を空間別に分割 | 実装 ＋ **仕様変更** | L1b |
| **M-11** | L2a の `_pair_deltas` を配列化、族を変換別に分割 | 実装 ＋ **仕様変更** | L2a |
| **M-12** | **L4 の距離計算を平方展開へ（OOM 修正）**、スコアリングを一括化 | 実装 | L4 |
| **M-13** | L4 の候補記述子から cost class `very_high` を除外 | **仕様変更** | L4 |
| **M-14** | 予算値の確定 | 実装 | Runtime |

---

## 4. 各変更の仕様

### M-1 仕事量の事前見積もり契約

全 Lens が次を実装する。

```python
@dataclass(frozen=True)
class WorkEstimate:
    unit_count: int               # 主要ループの反復数
    family_size: int              # BH 族の見積もり（最大の族）
    peak_memory_bytes: int        # 保持する最大構造の推定
    detail: dict[str, int]        # 内訳（contexts, features, pairs, candidates など）

def estimate_work(inputs) -> WorkEstimate: ...
```

Runtime は **Skill 起動前に** これを呼び、次を検査する。

| 検査 | 閾値 | 超過時 |
|---|---|---|
| `unit_count` | **`unit_count / units_per_second ≤ Node wall-clock 予算`**（M-14） | `needs_design_review` |
| `peak_memory_bytes` | Node の memory 予算 **64 GiB**（M-14）。**特徴量比例の項を含めること**（M-16） | `needs_design_review` |
| **`family_size`** | **`α (B+1) k_min`** = 0.05 × 1001 × 10 = **500** | `needs_design_review` |

**自動的に cap や閾値を変更しない。** 停止して人間へ返す。

見積もりは厳密でなくてよいが、**桁を外してはならない**。実測との比を記録し、3倍以上ずれたら警告する。

### M-2 長時間 Node の進捗報告

各 Lens は主要ループ中に一定間隔で次を Runtime へ報告する。

```text
{completed_units, total_units, elapsed_seconds}
```

- 報告間隔は **5 秒以上かつ全体の 1% 進むごと**のいずれか遅い方（M-14 で確定）
- Runtime は最終報告が**報告間隔の 20 倍**（下限 60 秒・上限 600 秒）途絶えた Node を `stalled` として記録する
- **固定 10 分は用いない。** 修正後の最長 Node（L5 の 7.3 分）より長く、検知器として働かない
- **自動 KILL はしない。** 人間が気づけることが目的である

### M-3 【仕様変更】L5 の比較単位

**変更前**: axis 内の全2組合せ。k=40 の軸で 780 ペア。

**変更後**: **各文脈と、その axis 内補集合**。k=40 の軸で 40 比較。

```text
axis A に属する文脈 C について
  内側 = C のメンバー
  外側 = (A に属する全文脈のメンバーの和集合) − C のメンバー
  両側で相関を計算し、|r| >= 0.30 かつ符号が逆なら候補
```

| | 変更前 | 変更後 |
|---|---|---|
| 問い | 「クラスタ1とクラスタ2で符号が逆か」 | **「この文脈は、同じ切り口の残りと符号が逆か」** |
| 比較数（k=40 軸） | 780 | **40** |
| 本番の候補数（R1.1 確定値） | 約 556,189 | **約 10,227** |

**scaffold axis のように文脈が axis を覆わない場合も、和集合を外側とする。** 全化合物ではない。

Finding の `condition_id` は `{context_id}|complement` とする。`entities.context_ids` は当該文脈のみとする。

`support_n`は、特徴量とEndpointがともにfiniteで相関へ実際に使用した一意な化合物indexの和集合件数とする。focal contextとaxis内補集合は排他的なので、置換計算前に`shared_n=0`、`support_n=n_a+n_b>=1`を検証する。変更前実装のように、特徴量欠測を含む生のContext共通所属数を特徴量別の`n_a/n_b`から減算してはならない。重複Contextと部分NaN特徴量を組み合わせ、旧式では`support_n<=0`になる回帰fixtureを必須とする。

### M-4 【仕様変更】L5 の BH 族を axis 分割

**変更前**: `family_key = "L5|correlation_sign_conflict"`（単一族）

**変更後**: `family_key = f"L5|{axis_id}|correlation_sign_conflict"`

異なる切り口の検定を同じ族へ入れる統計的根拠はない。L2a が `L2a|{class}|{question}` で分割しているのと同じ考え方である。

実測で族あたり **52**、k_min **1.04** となる（R1.1 の確定値）。

### M-5 相関表の一回計算（科学的契約を変えない）

`(context × compound)` の boolean 行列 `M` を1回作り、permutation ごとに5つの GEMM で全相関を得る。

```python
Xf  = np.isfinite(X).astype(float)
X0  = np.nan_to_num(X, nan=0.0)
yv  = y[:, None]
n   = M @ Xf
Sx  = M @ X0
Sxx = M @ (X0 ** 2)
Sy  = M @ (Xf * yv)
Syy = M @ (Xf * yv ** 2)
Sxy = M @ (X0 * yv)
num = n * Sxy - Sx * Sy
den = np.sqrt(np.maximum(n * Sxx - Sx**2, 0.0) * np.maximum(n * Syy - Sy**2, 0.0))
R   = np.where(den > 0, num / den, np.nan)
```

あわせて次を行う。

- **universe を行として実体化しない**（現行は 4,320 万 dict を list へ保持）
- **`global_r` は feature ごとに1回だけ計算する**（現行は row 生成のたび）
- **calibration の結果を screen へ再利用する**（現行は同じ permutation で二重評価）
- **BLAS の thread 数に `workers` を渡す**。process 並列は使わない

**数値同値性**: 実測で loop 方式との相対差は最大 `3.72e-10`。**許容幅 1e-9 とする。**

### M-6 【仕様変更】Tier 1/2 特徴量の重複排除

```text
1. Tier 1/2 全特徴量の pairwise |Pearson r| を計算する
2. |r| >= 0.95 を辺として連結成分を作る
3. 各成分から代表を1つ選ぶ（Tier 昇順、次に feature ID 辞書順）
4. **L5 だけ**が代表特徴量を使う。除外分は代表への参照つきで記録する
```

> **【R1.1 改訂】対象は L5 のみである。L1b へは適用しない。**
>
> 理由は3つある。
> 1. **L1b の入力は space 単位の距離行列であり feature 列ではない。** 代表 feature 化には距離の再構築が要り、文脈カタログの再生成を伴う。影響範囲が桁違いである。
> 2. **M-10a 適用後、L1b の計算量に feature 数は現れない。** コストは `(space × context × member) × k` の gather である。
> 3. **dedup は族を縮めない。** L1b の族は M-10b（空間別分割）が 763 → 84 にする。
>
> **context builder と Phase 1 artifacts は変更しない。**

**この変更の目的は計算量と可読性である。検出力の問題は M-3/M-4 が解決する。**
実測で族はほぼ変わらない（初版測定で 1,155,558 → 1,154,917）。近似的に同一の記述子を5件の Finding として報告しないための措置でもある。

### M-7 較正設定 hash の記録と照合

較正値（enrichment 等）と一緒に、取得時の設定 hash を記録する。

```text
descriptor_set / 空間ID一覧 / Tier 1/2 特徴量数 / k grid / 文脈最小サイズ / B / α
```

本番実行時に不一致を検出したら **警告を出す**（停止はしない）。

### M-8 本番設定での較正やり直し

R0 の受入基準（L2b enrichment > 1.5 等）は `fast` 設定（6空間）で取得した値であり、**本番設定（9空間・2,111特徴量）に対して未検証**である。

M-3〜M-6 適用後に、**本番設定で較正を取り直す**。新しい受入基準はその値で定める。

### M-9 受入基準へ計算量を追加

R0 実装計画書 8 章へ次を追加する。

```text
- worker 1 / 2 / 64 で同一の Finding 集合を得る
- wall-clock、CPU time、平均/最大 busy CPU 数、peak RSS を記録する
- 「workers が伝播したか」ではなく「実際に消費されたか」を検証する
  判定: CPU time / wall-clock が worker 数の 50% 以上
- speedup 倍率を事前に約束しない。測定値を報告する
```

### M-10 【R1.1】L1b の近傍表と族

#### 10a 近傍表を一回だけ作る（科学的契約を変えない）

`l1b.py:38-44` は permutation のたびに `np.lexsort` で近傍順序を計算し直している。
**距離行列は permutation で変化しない。** 変わるのは Endpoint だけである。

```python
def neighbor_index(distance, indices, neighbor_k):
    """(空間, 文脈) ごとに1回だけ呼ぶ。以後 permutation では使い回す。"""
    sel = np.asarray(sorted(indices), dtype=int)          # 昇順であること
    sub = distance[np.ix_(sel, sel)].copy()
    np.fill_diagonal(sub, np.inf)
    order = np.argsort(sub, axis=1, kind="stable")[:, :neighbor_k]
    return sel, sel[order]                                # targets, neighbours

# permutation ごと
lam = 1.0 - np.mean((y[targets] - y[neighbours].mean(axis=1)) ** 2) / global_variance
```

**`sel` を昇順に保ち `kind="stable"` を使うこと。** これにより現行の
`np.lexsort((candidates, distance[target, candidates]))` と**同順位の扱いが一致する**。
どちらも「距離昇順、同距離なら添字昇順」である。

**数値同値性: 実測で相対差 0.000e+00（完全一致）。** 同順位距離でも一致することを確認済み。
**受入条件は `lambda` の完全一致とする**（1e-9 ではない）。

全 (空間 × 文脈) の近傍表を1本の配列へ連結し、permutation ごとに一括 gather する。
近傍表メモリは 0.07 GB。1 permutation が 31.1 ms になる（本機12コア実測、本番寸法）。

#### 10b 【仕様変更】族を空間別に分割する

**変更前**: `family_key = "L1b|conditional_flatness"`（単一族）
**変更後**: `family_key = f"L1b|{space_id}|conditional_flatness"`

| | 族サイズ | k_min (B=1000) |
|---|---|---|
| 現行（単一） | 763 | **15.2** ← 目標10を超過 |
| 空間別（9族） | **84** | **1.68** |

λ は空間ごとに定義される量であり、異なる距離空間の検定を同じ族へ入れる根拠はない。
**axis 別まで割ると族が 0.4 になり割りすぎである**（第9節の停止規則）。

### M-11 【R1.1】L2a の配列化と族

#### 11a `_pair_deltas` を整数配列で書き直す（科学的契約を変えない）

`l2a.py:39,46` の `pairs.iloc[index][column]` は**行ごとに pandas Series を構築する**。
ペア1件あたり3回発生し、1回の呼び出しで **2,334.8 ms** かかる（11,563ペア、本機実測）。
これが 1,000 回呼ばれて **0.65 時間**になる。

```python
# 1回だけ作る
from_idx = <compound_from の整数添字配列>
to_idx   = <compound_to   の整数添字配列>
series_members = [<各 constant_key に属する化合物の整数添字（昇順・重複なし）>]

# permutation ごと
vals = y.copy()
for members in series_members:
    if members.size > 1:
        vals[members] = vals[members[rng.permutation(members.size)]]
delta = vals[to_idx] - vals[from_idx]
```

**1.4 ms / 回（1,653×）。B=1000 で 1.6 秒。**

あわせて `pairs.groupby(...).groups` の再計算をやめ、候補形成ループ（`l2a.py:88-89`）の
`pairs.loc[index, "compound_from"]` も事前配列の参照へ置き換える。

**候補が0件でも screen 100 回は実行される。** 現行はその場合でも 4 分を捨てている。
`candidates` が空なら screen ループへ入らないこと。

#### 11b 【仕様変更】族を変換別に分割する

**変更前**: `family_key = f"L2a|{class}|{question}"`
**変更後**: `family_key = f"L2a|{class}|{transformation_id}|{question}"`

| | 族サイズ | k_min |
|---|---|---|
| 現行（class × question） | 647 | **12.9** ← 目標10を超過 |
| ＋ 変換別 | **117** | **2.34** |

L2a の問いは「**この変換**の効果は文脈によって変わるか」である。掃引しているのは文脈であり、
**1つの変換について文脈を掃く集合**が族の自然な単位である。
**axis 別まで割ると族が 6 になり割りすぎである。**

### M-12 【R1.1】L4 の潜在メモリ欠陥の修正

#### 12a 距離計算を平方展開へ（科学的契約を変えない）

`l4.py:335` が `(候補数 × 観測数 × 特徴量数)` の3次元配列を実体化している。
**Tier 1/2 の9空間のうち8空間が euclidean であり、すべてこの経路を通る。**

| 候補数 | D015 Mordred（1600列）での所要メモリ |
|---|---|
| **100（現行 cap）** | **1.2 GiB。落ちない** |
| 10,000 | 114.6 GiB |
| 50,000 | 572.8 GiB |
| **250,000** | **2,864 GiB → OOM** |

**現行 cap では問題が顕在化しない。だから cap を上げられない。**

```python
# 変更前
distance = np.sqrt(np.sum((normalized_right[:, None, :] - normalized_left[None, :, :]) ** 2, axis=2))

# 変更後
sq_left  = np.einsum("ij,ij->i", normalized_left,  normalized_left)
sq_right = np.einsum("ij,ij->i", normalized_right, normalized_right)
distance = np.sqrt(np.maximum(
    sq_right[:, None] + sq_left[None, :] - 2 * normalized_right @ normalized_left.T, 0.0))
```

**メモリが特徴量数に依存しなくなる。250,000 候補で 1.79 GiB。**
**数値同値性: 相対差 中央値 0.00e+00 / 最大 4.82e-16。** 許容幅 1e-9 を満たす。
`np.maximum(..., 0.0)` は必須である。展開形は丸めで負になりうる。

#### 12b スコアリングの冗長を除く

`l4.py:396,400` の `eligible` と `lexical` は**候補に依存しない**が、候補ループの内側にある。
250,000 候補 × 9空間 = 225万回、毎回 961 件を走査し直している。

- `eligible` / `lexical` をループの外へ出す
- 候補ごとの `np.lexsort` を全候補一括の `np.argpartition(D, k, axis=1)[:, :k]` へ置き換える
- `stats.t.ppf(0.95, k-1)` は `neighbor_k` が固定なので**1回だけ引く**
- `stats.ttest_1samp` のループ呼び出しをやめ、`mean` / `std` から t 統計量を直接作る

**0.27 時間 → 0.18 分**（250,000 候補 × 9空間、本機実測）。

### M-13 【R1.1・仕様変更】L4 の候補記述子から `very_high` を除外する

M-12 適用後、L4 の制約は距離計算ではなく**候補の記述子計算**へ移る。
Tier 1/2 の cost unit 合計は候補1件あたり **99** であり、そのうち **64 が D019（xTB）**である。

> **L4 は、cost class が `very_high` の空間では候補をスコアリングしない。**

- 残る8空間（cost unit 35）なら 250,000 候補でも 64コアで数分である
- L4 のスコアは空間横断の**最小値**（保守側）を採るため、空間が1つ減っても手続きは成立する
- 合成されていない仮想化合物への半経験的量子化学計算は、根拠として最も弱い
- **使用した空間の一覧を evidence 行へ記録する**（`space_ids_json`）

`select_l4_candidates` の `description_cost_classes` から `very_high` を除いて渡す。
これにより候補1件あたり **35 cost unit**（99 − 64）になる。

### M-15 【R1.1・分離可能】L4 の候補 cap を引き上げる

**これは他の変更と独立に採否を決められる。** 採らなくても M-1〜M-14 は成立する。

現行の既定は **100 候補 / 900 行 / 10,000 cost unit** である。
**0.2.1 の目的は「中身の薄さ」の解消であり、cap 100 は L4 の出力を直接細らせている。**

Node 予算 60 分のうち 20 分を候補記述子へ配分すると、実測単位コスト 8.04 ms / 64コアから

```text
予算 cost unit = 20 x 60 x 64 / 0.00804 = 約 9,550,000
候補上限       = 9,550,000 / 35 unit    = 約 273,000
```

| 項目 | 現行 | 改定案 |
|---|---|---|
| `candidate_cap` | 100 | **250,000** |
| `max_candidate_description_cost_units` | 10,000 | **9,000,000** |
| `max_candidate_description_rows` | 900 | **2,000,000** |
| 距離行列メモリ | — | 1.79 GiB |
| 距離計算 | — | 1.0 分 |
| 記述子計算 | — | 約 18 分（64コア） |

> **M-12 と M-13 が入るまで cap を上げてはならない。** 上げた瞬間に guard を通過したまま OOM する。

### M-16 【R1.1】`estimate_work` は特徴量比例のメモリを含めること

現行 guard の欠落はここにある。`peak_memory_bytes` に次を必ず含める。

```text
候補数 x 観測数 x 8          (距離行列)
候補数 x 最大特徴量数 x 8     (候補の記述子行列)
文脈数 x 特徴量数 x 8 x 枚数  (L5 の相関表)
```

**特徴量数に比例する項を見落とすと、guard を通過したまま OOM する。**
L4 の現行 guard は記述子の行数と cost unit しか見ておらず、これが cap 引き上げを危険にしている。

### M-14 【R1.1】予算値の確定

初版で「実装者が本番機で測定して提案」としていた値を確定する。

| 項目 | 確定値 |
|---|---|
| **Node wall-clock 予算** | **60 分**（修正後の最長 Node は L5 の 7.3 分） |
| **Run 全体の予算** | **6 時間** |
| **Node メモリ予算** | **64 GiB**（修正後の最大は L4 の 1.79 GiB。R0 の 2,864 GiB を確実に弾く） |
| **進捗報告間隔** | **5 秒、または全体の 1% のいずれか遅い方** |
| **stalled 判定** | **報告間隔の 20 倍。下限 60 秒、上限 600 秒** |
| **L4 候補 cap** | **100（現行維持）。** 引き上げは M-15 で別 stage として行う |
| **k_min** | **10**（設計担当が決定済み） |

`max_units` は固定値を置かない。固定件数はデータ規模が変わると意味を失うためである。

> **【R1.1 改訂】Runtime の時間 gate は `WorkEstimate.estimated_seconds` を直接見る。**

```python
@dataclass(frozen=True)
class WorkEstimate:
    unit_count: int
    family_size: int
    peak_memory_bytes: int
    estimated_seconds: float      # 各 Lens が自分のコストモデルで算出する
    detail: dict[str, int]
```

| 役割 | 担当 |
|---|---|
| Runtime の時間 gate | **`estimated_seconds ≤ Node wall-clock 予算`** |
| `units_per_second` | **各 Lens の estimator の内部定数**（設定に置く） |
| `unit_count` | **`estimate/actual` 比の検証用**に残す |

初版は `unit_count / units_per_second` を Runtime 側の共通規則としていたが、
**L4 は「候補×空間のスコアリング」と「記述子の cost unit」という異なる2つのコストを持ち、
単一の `unit_count` では表せない。** Lens 固有の式を Runtime へ漏らさないため、
**各 Lens が秒を返す形へ改める。**

```text
L4 以外 : estimated_seconds = unit_count / units_per_second * 1.25
L4      : estimated_seconds = ((C4*S4)/units_per_second_l4 + W*0.00804/workers) * 1.25
          C4=候補数  S4=D019除外後の空間数  W=候補記述子の cost unit 合計
```

保守係数 **1.25** は M-16 のメモリ係数と同じ値である。記述子計算が worker 数へ完全には
反比例しない可能性を吸収する。`units_per_second` は実装時に下表の測定値で初期化し、
Run ごとに実測比を記録して更新する。

| Lens | unit の定義 | B=1000 の所要 | 本機12コアでの実測 `units_per_second` |
|---|---|---|---|
| L5 | 比較 × 特徴量 | 7.3 分 | 1,595,592 / 0.437 秒 ≈ **3.65e6** |
| L1b | (空間 × 文脈 × メンバー) | 0.5 分 | 922,752 / 0.031 秒 ≈ **2.98e7** |
| L2a | ペア | 1.6 秒 | 11,563 / 0.0016 秒 ≈ **7.23e6** |
| L4 | 候補 × 空間 | 1.2 分 | 2,250,000 / 71 秒 ≈ **3.17e4** |
| **L2b** | **系列内 observation 数** | **1.03 分** | 3,155 / 0.062 秒 ≈ **5.09e4** |
| **L7** | **candidate × question** | **14.3 秒** | 86 / 0.0143 秒 ≈ **6.00e3** |

**【R1.1 追補】L2b と L7 の値も実測した。時間 gate は全 Lens に適用する。例外は作らない。**
L7 の値が小さいのは `np.random.default_rng()` を candidate ごと・反復ごとに生成しているためである。
**総時間が 14.3 秒なので最適化しない。** 遅い理由を把握した上で据え置く。

### 進捗報告の粒度

M-2 の目的は「人間が気づけること」である。**14 秒の Node に進捗率は要らない。**

| Lens | `progress_granularity` |
|---|---|
| L1b / L2a / L4 / L5 | **`loop`**。core callback で実進捗を出す |
| L2b / L7 | **`node`**。wrapper の liveness heartbeat のみ |

**`l2b.py` と `l7.py` へ callback を入れることは禁じていない。**
「変更しない」とは統計的契約とアルゴリズムを変えないという意味である。
ただし総所要時間から見て割に合わないため、`node` 粒度でよい。
**採った粒度を manifest へ記録すること。**

**進捗報告 10 分・stalled 10 分という初版の値は破棄する。** 修正後の最長 Node より長く、検知器として働かない。

---

## 5. 実施順序

**【R1.1】順序を改めた。** 初版は L5 を先に直し、他 Lens は本番測定後に判断する順序だった。
測定により他 Lens の欠陥が確定したため、**最も重い欠陥から直す順序へ変える。**

```text
段階R1-1  M-1 + M-14 + M-16  仕事量見積もり契約と予算値   ← 以後の作業中に同じ事故を起こさない
段階R1-2  M-2                進捗報告
段階R1-3  M-3 M-4 M-10b M-11b（全 Lens の族）            ← 統計問題の解決。ここで止まって報告
段階R1-4  M-6                特徴量重複排除
段階R1-5  M-5 M-10a M-11a M-12（計算量とメモリ）          ← ここで初めて性能に着手
段階R1-6  M-13               L4 の very_high 除外
段階R1-7  M-7                較正設定 hash
段階R1-8  M-8                本番設定での較正やり直し
段階R1-9  M-9                受入基準の追加
段階R1-10 M-15               L4 の候補 cap 引き上げ（採用する場合のみ）
```

**段階R1-3 を終えた時点で必ず止まり、報告すること。**
統計問題が解決していなければ、性能を直しても意味がない。

**段階R1-10 は M-12 と M-13 の完了後にのみ実施する。** 順序を入れ替えると OOM する。

**L2b と L7 は変更しない。** 測定の結果、族（75 / 86）も計算量も予算内である。

---

## 6. 受入条件

### 6.1 科学的同値性（実装変更のみ対象）

次の変更は**同じ統計量を速く計算するもの**であり、値が変わってはならない。

| 変更 | 対象 | 基準 |
|---|---|---|
| M-5 | L5 の相関値 | 相対差 ≤ **1e-9**（実測 3.72e-10） |
| **M-10a** | **L1b の lambda** | **完全一致**（実測 0.000e+00。1e-9 ではない） |
| M-11a | L2a の delta | **完全一致**（整数添字の gather であり丸めが生じない） |
| M-12a | L4 の距離 | 相対差 ≤ **1e-9**（実測 4.82e-16） |
| M-12b | L4 の lower bound / p 値 | 相対差 ≤ **1e-9** |

いずれも **p 値と Finding 集合は完全一致**すること。

**M-3 / M-4 / M-6 / M-10b / M-11b / M-13 は科学的契約の変更であり、同値性は要求しない。**
変更前後の候補数・族サイズ・Finding 数を報告する。

### 6.2 統計予算

**全 Lens** について `族サイズ ≤ α (B+1) k_min` = 0.05 × 1001 × 10 = **500** を満たすこと。

| Lens | 修正後の族 | 見込み族サイズ | k_min |
|---|---|---|---|
| L5 | `L5\|{axis_id}\|correlation_sign_conflict` | 52 | 1.04 |
| L1b | `L1b\|{space_id}\|conditional_flatness` | 84 | 1.68 |
| L2a | `L2a\|{class}\|{transformation_id}\|{question}` | 117 | 2.34 |
| L2b | `L2b\|{class}\|{question}`（変更なし） | 75 | 1.50 |
| L7 | `L7`（変更なし） | 86 | 1.72 |

**L4 は parametric t 検定であり p 値に下限が無い。k_min 制約の対象外である。**

見込みを上回る場合は原因を報告すること。**族を勝手に細かく割って回避してはならない**（第9節）。

### 6.3 性能

| 項目 | 基準 |
|---|---|
| worker 1 / 2 / 64 | **同一の Finding 集合** |
| CPU 利用 | CPU time / wall-clock ≥ worker 数の 50% |
| 各 Node の wall-clock | **60 分以内** |
| Run 全体 | **6 時間以内** |
| peak RSS | **Node あたり 64 GiB 以内** |

**参考値**（本機12コア、本番寸法での実測。64コアでこれを上回ることはない）:

```text
L5   7.3 分   L1b 0.5 分   L2a 1.6 秒   L4 1.2 分（距離）+ 0.2 分（スコア）
```

**倍率を約束しない。測定値を報告する。** ただし上表の予算は超えないこと。

### 6.4 resource safety

- `estimate_work` が次を**起動前に**停止することを試験する
  - **L5 の R0 設定**（族 556,189）
  - L1b の R0 設定（族 763）、L2a の R0 設定（族 647）
  - **M-12 を入れない状態で cap を 10,000 にした L4**（3次元配列 114.6 GiB）
- `peak_memory_bytes` に**特徴量数に比例する項が含まれている**ことを試験する（M-16）
- 見積もりと実測の比を記録し、3倍以上のずれを警告する

### 6.5 KILL 復旧

- 修正後の最長 Node は L5 の 7.3 分である。**最初からやり直せる。checkpoint を実装しない**
- 60 分の Node 予算を超える Node が現れた場合は、checkpoint ではなく**原因を報告する**

---

## 7. 実装前に確認を要する事項

**【R1.1】未確定事項は無い。** 初版に残っていた5項目はすべて解決した。

| # | 初版での扱い | R1.1 での確定内容 | 根拠 |
|---|---|---|---|
| 1 | `k_min` の値 | **`k_min = 10`** | 設計担当が決定（「単一の解析で最低限 Finding を10件拾いたい」） |
| 2 | `max_units` / memory 予算 | **wall-clock 換算方式。Node 60分 / Run 6時間 / メモリ 64 GiB** | M-14。修正後の最長 Node 7.3 分、最大メモリ 1.79 GiB の実測から |
| 3 | 進捗間隔と stalled 判定 | **5 秒（または1%）/ 報告間隔の20倍、下限60秒・上限600秒** | M-14。L5 の 437 ms/permutation から |
| 4 | L1b にも同種の変更が要るか | **要る。M-10a（近傍表）＋ M-10b（族を空間別）** | 族 763 → k_min 15.2 で超過。計算量も 0.44 時間 |
| 5 | Mordred 導入後の実特徴量数と候補化率 | **Mordred 1,800列 / Tier1-2 合計 2,111列。候補化率 L1b 0.079・L2a 0.2204** | 利用者確認値と本機での実測 |

さらに、初版が扱っていなかった次を確定した。

| 項目 | 確定内容 |
|---|---|
| **L4 の潜在欠陥** | `l4.py:335` の3次元配列。cap 100 では顕在化しないが、cap 10,000 で 114.6 GiB。**本番の KILL は L5 であり L4 ではない** |
| **L4 の候補 cap** | 現行 100。**M-12 / M-13 後に 250,000 へ引き上げ可能**（M-15、分離可能な判断） |
| **L4 の記述子** | cost class `very_high`（D019 xTB）を除外する |
| **L2a の欠陥** | `_pair_deltas` が 2,334.8 ms/回。族 647 で k_min 12.9 |
| **L2b / L7** | **測定の結果、変更しない**と決定 |
| **族分割の停止規則** | `k_min ≤ 10` を満たす最も粗い粒度で止める（第9節） |

> **実機測定を前提として保留した項目は残っていない。**
> 64コア機で測るのは「実際に速かったか」（第6.3節の受入）であり、「何を直すか」ではない。

**本書と仕様概要書 R1 に書かれていない設計判断を、実装者が独断で行わないこと。**
判断が必要になった場合は、実装を止めて質問すること。

### 7.1 文書の完了状態

| 文書 | R1.1 反映 |
|---|---|
| `CONDUCTOR_0.2.1_specification_overview.md` | 済（2.5節、3.1節、L5 行、決定事項 R1-1〜R1-15） |
| `CONDUCTOR_0.2.1_scale_measurement_report.md` | 済（全レンズへ拡張。全数値の根拠） |
| `design/discovery_lenses.md` | 済（L5 / L1b / L2a / L4 の各節を改訂） |
| 本書 | 済 |
| R0 実装計画書・詳細仕様書 | **変更しない。** 本書が差分を定める |

---

## 9. 族分割の停止規則

L1b / L2a / L5 の族を分割するにあたり、**どこまで割るか**の規則を定める。

> **分割は `k_min ≤ 10` を満たす最も粗い粒度で止める。**

細かく割るほど各族の BH 補正は緩くなり、族数ぶん偽陽性の期待値が増える。
分割は目的ではなく、**統計予算を満たすための最小限の手段**である。

| Lens | 粒度 | 族あたり | k_min | 採否 |
|---|---|---|---|---|
| **L5** | 単一 | 556,189 | 11,113 | ✗ |
| | 空間別（18） | 568 | 11.4 | ✗ |
| | **axis 別（196）** | **52** | **1.04** | **採用** |
| **L1b** | 単一 | 763 | 15.2 | ✗ |
| | **空間別（9）** | **84** | **1.68** | **採用** |
| | 空間 × axis | 0.4 | — | 割りすぎ |
| **L2a** | class × question | 647 | 12.9 | ✗ |
| | **＋ 変換別** | **117** | **2.34** | **採用** |
| | ＋ axis 別 | 6 | 0.12 | 割りすぎ |
| **L2b** | class × question | 75 | 1.50 | **現行のまま** |
| **L7** | 単一 | 86 | 1.72 | **現行のまま** |

**族サイズが予算を超えたとき、割って逃げてよいのは上表の粒度までである。**
それでも超える場合は、比較単位そのものを見直すこと（L5 における M-3 がその例である）。

---

## 8. この修正が防ぐもの

L4 の25万候補と L5 の4,320万 universe は、**同じ欠陥から生じた**。

> **実行前に仕事量と族サイズを検査する契約が無かった。**

M-1 はこの両方を起動前に停止する。**次の Lens でも同じく停止する。**

M-7 / M-8 は別の欠陥に対応する。**較正時の設定と本番の設定が違っていた**ことを検出できるようにする。
R0 はこれを検出できず、`fast` 設定の enrichment を本番の受入基準として書いていた。

---

## 10. R1-3 productionで判明した追加是正 M-17

### M-17 Description terminal SKIPのnegative cache化

3D Descriptionでは、SMILESが妥当でも固定条件でConformerを生成できない化合物が存在し得る。これは行単位・Capability単位の非適格であり、Description Node全体またはRun全体の失敗ではない。

- 3D Skillは入力行を欠落させず、`description_error`とmanifestの`error_type=conformer_generation_failed`を記録する。
- Description Databaseは当該行を同じcalculation signatureのactive recordとして保存し、`outcome_status=skipped`、理由`conformer_generation_failed`を監査ログへ残す。
- terminal SKIPは次回Runでcache hitとし、同じ条件で無限に再計算しない。
- 任意の実装例外、依存関係障害、資源枯渇はterminal SKIPへ格上げせず、negative cacheにも登録しない。
- miss-only batchがSKIP行だけでも、既存active recordのfeature schemaでnull列を補い、run-scoped payloadを全入力順で完成させる。
- distance metadataは`eligible_compound_ids`と非適格理由を持つ。SKIP行を中央値補完した仮想観測として解析へ入れない。
- Context clustering、L1b、L4は空間別eligible集合だけを使用する。L5は従来どおりfinite feature行だけを使用する。
- 少数のterminal SKIPがあってもP01を成功させ、下流Nodeを継続する。全化合物が非適格でfeature schemaを解決できないCapabilityは黙って捨てず停止する。

受入fixtureは「既存hit＋Conformer生成不能だけのmiss batch」を必須とし、SKIP recordの再利用、run-scoped payloadのnull行、distanceからの除外、次回miss=0を検証する。
