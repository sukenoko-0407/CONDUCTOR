# CONDUCTOR 0.2.1 性能・頑健性 独立レビュー

作成日: 2026-09-19
立場: 先行Agent案とは独立に、repository の仕様・実装・testを確認して評価する。

---

## 1. Executive summary

**L5の8時間は症状であり、根本ではない。** 根本は次の3点である。

1. **較正時と本番で入力規模が桁違いに変わったが、それを検出する仕組みが無い。**
   較正（診断module）はTier 1/2を6空間・約12特徴量で行った。本番はTier 1/2が9空間・**推定2,550特徴量**（うちD015 Mordred 2Dが約7割）である。文脈も較正270に対し本番は**推定2,200**。L5のuniverseは`context_pair × feature`なので、**推定5,400万行**へ膨らむ。

2. **L5は同じ相関を約19回重複計算している。** 必要なのは`context × feature`の相関表（推定570万）だが、実装は`context_pair`ごとに両端の相関を計算するため約1億700万回計算する。worker未接続はその上に乗る二次的問題である。

3. **【最重要】性能を直しても、現在の設定ではL5がFindingを1件も出せない可能性が高い。**
   BH family（`L5|correlation_sign_conflict`）は候補数そのものであり、推定10⁵〜10⁶。permutation B=1000のp値下限は`1/1001 ≈ 1e-3`。BHが1件でも棄却するには、**p値下限に張り付くtestが1万件規模で必要**になる。`L5を速くする`ことは、**ゼロ件を速く出すこと**になりかねない。

したがって推奨する順序は、**先に統計的実行可能性を測り、次に重複を除き、最後にBLAS化する**である。process shard、resource token、mmapなどの機構は現時点では不要な複雑化と判断する。

**頑健性の観点での本命の提案は、L5固有の最適化ではない。** 「各Lensが実行前に仕事量を申告し、Runtimeが予算で門番する」**cost model contract**である。これはL4の25万候補とL5の5,400万universeを**どちらも実行前に止められた**唯一の機構である。

---

## 2. 確認した事実

### 2.1 L5の計算構造

`C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l5/python/conductor_lens_l5/l5.py`

| line | 事実 |
|---|---|
| 143 | `context_pairs`は各axis内の全2組合せ。`combinations(ids, 2)` |
| 147-170 | context pairごとに全featureを走査し、両端の相関を計算してuniverse rowを作る |
| 150-151 | `_correlation(x, y, membership[left_id])`をpairごとに呼ぶ。**同じ`(context, feature)`が、そのcontextが属するpair数だけ再計算される** |
| 165 | `global_r`もrow生成のたびに再計算される。featureごとに一度でよい |
| 167 | **各universe rowが`"x": x`で特徴量ベクトル参照を保持する**。dictは5,400万個生成される |
| 180-193 | permutation loop。最初の`calibration_permutations`(20)回は**universe全体**を再評価し、その後に候補subsetをもう一度評価する（185-188行と190-193行で重複） |
| 196-205 | final loopは生存候補のみ。ここは適切 |
| 全体 | **process/thread並列は一切ない。`--workers`はkernelへ到達していない** |

`_correlation`（84-91行）は`np.corrcoef`で2×2行列を作る。要素数20〜100の配列に対してPython/numpy呼び出し overheadが支配的である。

### 2.2 規模の推定

| 量 | 推定値 | 根拠 |
|---|---|---|
| Tier 1/2 空間 | 9 | `CONDUCTOR_modules/tools/description_adapter.py:33-34` (TIER_1=D001,D006 / TIER_2=D003,D012,D013,D014,D015,D016,D019) |
| Tier 1/2 特徴量 | **約2,550** | D015 Mordred 2D 約1,800が約7割を占める |
| 文脈 | 約2,200 | cluster 18空間×k grid、quantile Tier1特徴量×3、scaffold 4種 |
| axis内 context pair | **約21,000** | k=40のaxisだけでC(40,2)=780 |
| universe行 | **約5,350万** | 21,000 × 2,550 |
| 観測時の相関計算 | 約1億700万回 | universe行 × 2 |
| calibration時の相関計算 | **約21億回** | 20反復 × 1億700万 |

21億回 × 約15 μs ≈ **8.9時間**。本番観測の「1コアで8時間以上」と整合する。

### 2.3 重複度

```text
必要な distinct 相関  = contexts × features = 2,200 × 2,550 ≈ 570万
実際に計算している数  = context_pairs × features × 2 ≈ 1億700万
重複度               ≈ 19倍
```

各contextが平均19個のpairに参加するためである。

### 2.4 cs-stat-core

`.claude/skills/cs-stat-core/python/conductor_stat_core/statistics.py`

- `permute_within_blocks`(25-55行)は毎回block groupをPython loopで再構築する。961要素 × 1000反復で約100万反復。**律速ではないが不要な再計算**である。
- `benjamini_hochberg`(87-115行)は`family_key`ごとに独立補正しており、仕様どおり。実装に誤りは無い。
- `empirical_p_value`(65-84行)は分子分母に+1を入れており、仕様どおり。

### 2.5 L5のBH family

`l5.py:212` — `family_key="L5|correlation_sign_conflict"`。**L5全体で単一family**である。
`l5.py:207-219` — TestRecordは`candidate_by_key`（符号矛盾候補）に対してのみ作られる。universeではない。

したがってfamily size = 候補数である。

---

## 3. 現状で問題ないこと

これらは変更を要しない。

| 項目 | 根拠 |
|---|---|
| L5の科学的契約 | 同一axis限定、Pearson、\|r\|≥0.3、逆符号、Fisher z差、骨格内並べ替え、段階B=100/1000、BH。いずれも仕様どおりで誤りは無い |
| `empirical_p_value`の+1補正 | `statistics.py:84` |
| BHのfamily独立性 | `statistics.py:87-115`。family_keyごとに独立 |
| 骨格内並べ替えの実装 | `statistics.py:25-55`。null block・singleton・欠測の扱いが仕様どおり |
| L4のcandidate/row/cost guard | 是正報告R-08。**これは正しい形の対策であり、並列化後も維持すべき** |
| L5のfinal loopの段階化 | `l5.py:196-205`。生存候補のみへ絞っており適切 |

---

## 4. 確認済みの課題

### C-1 L5の相関重複（確定）

静的に確認できる。`l5.py:147-170`および`180-193`。重複度約19倍。

### C-2 L5 calibrationとscreenの二重評価（確定）

`l5.py:185-188`でuniverse全体を評価した直後、`190-193`で候補subsetを再評価する。calibration結果を再利用していない。最初の20反復で**約2倍の無駄**がある。

### C-3 universe materialization（確定）

`l5.py:145,168`。5,400万個のdictをlistへ保持する。1個500 byteとして**約27 GB**。755 GiBあるため即死はしないが、GC圧とcache missを生む。**そもそも行として実体化する必要がない。**

### C-4 workerが計算kernelへ届いていない（確定）

L5に並列化コードが存在しない。L1b/L2a/L2b/L7も同様（stage11報告の追補と一致）。
**R-03の受入条件「全境界で64」は伝播を検証したが消費を検証していない。** これはtestが誤った対象を検証していた例である。

### C-5 【最重要】BH family sizeと permutation下限の非整合（要測定・高リスク）

- family size = 候補数。推定10⁵〜10⁶
- B=1000のp値下限 = `1/1001 ≈ 1e-3`
- BHが順位kで棄却する条件は `p_(k) ≤ 0.05·k/n`
- n=600,000なら、p=1e-3で棄却されるには **k ≥ 約12,000** が必要

つまり**p値下限に張り付くtestが1万件規模で存在しない限り、L5は1件もFindingを出さない。**

較正時（診断）は候補325件規模であり、この問題は現れなかった。**本番でfeature数とcontext数が2桁増えたことで初めて顕在化する。**

> **これは性能問題ではなく設計問題である。L5を1000倍速くしても、出力がゼロなら意味がない。**

### C-6 進捗の不可視（確定）

8時間、異常を示す信号が無かった。長時間Nodeにheartbeat/progressが無い。

---

## 5. benchmarkが必要な未確認事項

断定を避ける。以下は測定前に結論を出さない。

| # | 測定対象 | 測定しないと決められないこと |
|---|---|---|
| B-1 | L5の実候補数と、p値下限に張り付くtest数 | **C-5が現実の障害か。最優先** |
| B-2 | Tier 1/2の実feature数（D015の実列数を含む） | universe規模の確定 |
| B-3 | 実context数とaxis別context数分布 | context_pair数の確定 |
| B-4 | L1b/L2a/L2b/L7の本番wall-clock、peak RSS、候補数 | L5以外に遅延があるか。**現時点で「遅い」と断定しない** |
| B-5 | 特徴量間の相関構造（\|r\|>0.95の組の割合） | feature重複排除でfamilyをどこまで減らせるか |
| B-6 | matrix形とloop形の相関値の一致精度 | 数値同値性の許容幅 |

---

## 6. Lens別評価

| Lens | 科学的契約 | 確認済みの課題 | 未確認 | 推奨 |
|---|---|---|---|---|
| **L5** | 問題なし | 相関19倍重複、二重評価、universe実体化、worker未接続、**family size過大の疑い** | 実候補数、実feature数 | **まずB-1を測定。** 次に相関表の一回計算。最後にBLAS化 |
| **L1b** | 問題なし | 同じ形の重複（context×space×permutationでdistance再sort）、worker未接続 | 本番wall-clock | L5と同じ構造なので**同じ修正が効く**。neighbor indexの事前compile |
| **L2a** | 問題なし | worker未接続 | 本番wall-clock、pair数 | 測定まで変更しない |
| **L2b** | 問題なし | worker未接続 | 本番wall-clock | 測定まで変更しない |
| **L4** | 問題なし | generation/scoreが逐次 | cap前のraw候補生成コスト | **guardは維持。** cap前生成の逐次性だけ測定 |
| **L7** | 問題なし | worker未接続 | 本番wall-clock | 測定まで変更しない |
| L1a/L3/L6 | 診断のみ | — | — | 変更不要 |
| stat-core | 問題なし | block group毎回再構築（軽微） | — | group事前計算のみ |

**L5とL1b以外は、測定前に変更しない。** 小規模fixture合格を本番合格と扱わないのと同様に、測定なしに遅いと断定しない。

---

## 7. 先行Agent案への評価

| 案 | 判定 | 理由 |
|---|---|---|
| Boolean context membership matrix | **正しい** | `(context × compound)`のboolean行列は数百KB。これが相関表の一回計算を可能にする |
| L5 context×feature相関表の一回計算 | **正しい。最優先** | 重複19倍を直接解消する。**単独で約19倍、実装量も最小** |
| 符号集合からの候補生成 | **正しい** | axisごとに`pos = R≥0.3`, `neg = R≤-0.3`のboolean行列を作り、`pos @ neg.T`で符号矛盾数をGEMMで数えられる。calibration countもこれで足りる |
| L1b neighbor indexの事前compile | **条件付きで妥当** | 原理は正しいが、L1bの本番所要時間が未測定。B-4の後に着手 |
| L2a pair-inside/outside matrix | **証拠不足** | L2aが遅いという観測が無い。B-4の前に着手しない |
| L2a/L2b/L7の共通permutation task protocol | **不要な複雑化** | 遅いと確認されていないLensへ共通protocolを導入すると、決定性とcheckpointの検証対象が増える。**頑健性を下げる** |
| L4のdisk-backed候補集約とsharding | **条件付きで妥当** | cap前のraw生成が実際にボトルネックである場合のみ。cap自体は既に効いている |
| process並列、BLAS/OpenMP thread=1、read-only mmap | **不要な複雑化** | 下記参照 |
| Runtime resource token、Popen監視、heartbeat、node_tasks checkpoint | **heartbeatのみ正しい。他は証拠不足** | 進捗可視化は必須。token/checkpointは、そもそも長時間Nodeが無くなれば不要になる |

### process並列化を推奨しない理由

相関表の一回計算とBLAS化を行うと、L5のpermutation 1反復は**5つのGEMM**になる。

```text
(2,200 × 961) @ (961 × 2,550) を5回 ≈ 55 GFLOP/反復
```

64コアのBLASはこれを**1秒未満**で処理する。1000反復でも**10分程度**である。

この状態でprocess shardを追加しても、得られるのは既に十分な速度の更なる短縮だけであり、代わりに次を抱え込む。

- shard間の決定性保証（seed導出、結果結合順）
- 未完了shardのcheckpointと再開
- shard単位のresource token
- BLAS thread=1との相互作用

**これは頑健性を下げる取引である。** 64コアはBLASに使わせるのが最も単純で、最も壊れにくい。

---

## 8. 私の代替案

### 8.0 最優先: 実行可能性の測定（コード変更なし）

**何も最適化する前に、L5が原理的にFindingを出せるかを測る。**

現行実装のまま、**calibration_permutations=3、screen_permutations=3、final_permutations=3**、かつfeatureをD001+D006（Tier 1のみ、約285特徴量）に限定して1回走らせる。目的は統計ではなく、次の3つの実数を得ることである。

```text
universe_count / screen_candidate_count / 各axisのcontext数
```

これで **C-5（family size）が現実の障害かどうかが決まる**。約9倍縮小した設定なので1時間以内に終わる。

### 8.1 提案A: 特徴量の重複排除【科学的仕様変更・本命】

**設計には文脈の重複排除（Jaccard 0.9）があるが、特徴量には無い。** 同じ原理をもう一方の軸へ適用する。

```text
1. Tier 1/2 全特徴量のpairwise |Pearson r| を計算する（2,550² の相関行列。数秒）
2. |r| ≥ 0.95 を辺として連結成分を作る
3. 各成分から代表を1つ選ぶ（Tier昇順、次にfeature ID辞書順）
4. L5とL1bは代表特徴量だけを使う。除外分は参照付きで記録する
```

**これが速度と統計的検出力を同時に直す唯一の手段である。**

- Mordred 2Dは相互に極めて高相関な記述子を大量に含む。1,800列を独立な1,800検定として扱うのは統計的に正当でない
- 特徴量が仮に2,550 → 400へ減れば、universeは6.4分の1、**BH familyも6.4分の1**になる
- C-5の緩和に直接効く

**これは仕様変更である。** 承認を要する。

### 8.2 提案B: 相関表の一回計算【実装のみ・必須】

科学的契約を変えない。同じ統計量を重複なく計算する。

```python
# 1回だけ: boolean membership 行列
M = (contexts × compounds) boolean          # 数百 KB

# permutationごと: 5つの GEMM で全 (context × feature) 相関を得る
Xf  = isfinite(X);  X0 = nan_to_num(X)
n   = M @ Xf
Sx  = M @ X0
Sxx = M @ X0**2
Sy  = M @ (Xf * y[:, None])
Syy = M @ (Xf * y[:, None]**2)
Sxy = M @ (X0 * y[:, None])
R   = (n*Sxy - Sx*Sy) / sqrt((n*Sxx - Sx**2) * (n*Syy - Sy**2))
```

- universeを行として実体化しない（C-3解消）
- calibration countはaxisごとに`pos @ neg.T`のGEMMで数える。二重評価も解消（C-2）
- `global_r`はfeatureごとに1回だけ計算する
- **process並列は使わない。** BLASのthread数を`workers`に設定する

**期待効果**: 重複解消で約19倍、BLAS化で更に2桁。推定8.9時間 → **10分程度**。ただし**測定で確認する**。

### 8.3 提案C: cost model contract【頑健性・本命】

**L4の25万候補とL5の5,400万universeは、どちらも同じ欠陥から生じた。実行前に仕事量を見積もる契約が無いことである。**

L4には事後的にguardが付いたが、L5には無かった。**次のLensでも同じことが起きる。**

```python
# 全Lensが実装する契約
def estimate_work(inputs) -> WorkEstimate:
    return WorkEstimate(
        unit_count=...,          # 主要ループの反復数
        peak_memory_bytes=...,   # 保持する最大構造の推定
        detail={...},            # 内訳（context数、feature数、pair数など）
    )
```

Runtimeは**Skill起動前に**これを呼び、予算を超えたら`needs_design_review`で停止する。L4のguardをLens共通へ一般化するだけであり、新しい概念を導入しない。

これがあれば:
- L4の25万候補 → 起動前に停止
- L5の5,400万universe → 起動前に停止
- 将来のLens → 同じく停止

**変更量は小さく、効果は全Lensへ及ぶ。** 頑健性という観点でこれが最重要である。

### 8.4 提案D: 進捗の可視化【実装のみ・必須】

長時間Nodeは、進捗を出さなければハングと区別できない。

```text
各Lensは一定間隔で {completed_units, total_units, elapsed} をRuntimeへ報告する
Runtimeは所定時間更新が無いNodeをstalledとして記録する
```

自動KILLは入れない。**人間が気づける**ことが目的である。8時間気づけなかったことが問題であり、自動停止は別の事故を生む。

### 8.5 現状維持を選ぶもの

- **L2a / L2b / L7**: B-4の測定まで変更しない
- **L4のcap**: 維持。並列化後も自動拡大しない
- **stat-core**: block groupの事前計算のみ。それ以外は変更しない
- **process shard / resource token / mmap**: 導入しない

---

## 9. 比較と推奨する実験順序

### 案の比較

| | A 特徴量重複排除 | B 相関表一回計算 | C cost model | D 進捗可視化 | 先行案 matrix+shard |
|---|---|---|---|---|---|
| 変更量 | 中（新module） | 中（L5/L1b書換） | 小（契約＋Runtime） | 小 | 大 |
| 科学的同値性 | **変わる（仕様変更）** | 保たれる（数値許容幅要） | 保たれる | 保たれる | 保たれる |
| 期待効果 | universe・family 1/6 | **約19倍＋BLAS 2桁** | 事故の事前停止 | 検知 | Bと同等 |
| peak memory | 減 | **27 GB → 100 MB未満** | — | — | 減 |
| checkpoint容易性 | — | 不要（十分速い） | — | — | **shard checkpointが必要** |
| Windows/Linux再現性 | 高 | 高（BLAS版差の許容幅要） | 高 | 高 | **shard数依存の懸念** |
| 実装・test工数 | 中 | 中 | 小 | 小 | 大 |
| 頑健性への寄与 | 中 | 中 | **最大** | 大 | **負**（機構増） |

### 推奨順序

```text
0. B-1測定（コード変更なし、縮小設定で1回走らせる）
       ↓  ここでC-5が障害と判明したら、性能作業より先に仕様を直す
1. 提案C cost model contract      ← 事故の再発防止。以後の作業を安全にする
2. 提案D 進捗可視化                ← 次の長時間Nodeで気づける
3. 提案B 相関表一回計算（L5）       ← 数値同値性testとセット
4. B-4測定（L1b/L2a/L2b/L7）       ← ここで初めて他Lensの要否が決まる
5. 提案A 特徴量重複排除            ← 仕様変更の承認後
6. L1bへ提案Bと同じ構造を適用      ← B-4で必要と判明した場合のみ
```

**1と2を先に置くのは、以後の全作業が同じ事故を繰り返さないようにするためである。** 性能改善より先に来る。

---

## 10. 仕様変更が必要な事項 / 実装だけでよい事項

### 仕様変更が必要（承認を要する）

| 項目 | 内容 |
|---|---|
| **特徴量の重複排除** | L5/L1bが使う特徴量を代表集合へ絞る。BH familyが変わるため科学的契約の変更 |
| **L5のBH family定義**（C-5次第） | 単一familyをaxis別またはfeature群別へ分割する案。測定後に判断 |
| **permutation Bの下限** | family sizeに応じてBを引き上げる規則。現行の固定1000はfamilyが大きいと機能しない |

### 実装だけでよい

| 項目 |
|---|
| 相関表の一回計算（提案B） |
| calibration/screen二重評価の解消 |
| universe行の非実体化 |
| `global_r`の一回計算 |
| BLAS thread数への`workers`接続 |
| cost model contract（提案C） |
| 進捗報告（提案D） |
| stat-coreのblock group事前計算 |

---

## 11. 受入条件

### 科学的同値性

- 縮小fixtureで、現行実装と新実装の`statistic`、`p_value`、`q_value`、Finding集合を比較する
- **matrix形は現行のloop形とbit一致しない。** 相対許容幅を明示的に定める（推奨: statistic相対1e-9、p値は完全一致、Finding集合は完全一致）
- 一致しない場合は許容幅を緩めず、原因を特定する

### 性能

- worker 1 / 2 / 64 で**同一のFinding集合**を得る
- wall-clock、CPU time、平均/最大busy CPU、peak RSSを記録する
- **speedup倍率を事前に約束しない。** 測定値を報告する

### resource safety

- peak RSSがNode予算内
- cost model contractが、L4の旧25万候補設定とL5の全feature設定を**起動前に停止する**ことを試験する

### KILL復旧

- 提案Bで十分速くなればcheckpointは不要。**Nodeを最初からやり直せる時間であることを受入条件にする**
- 10分で終わるNodeにcheckpointを付けるのは不要な複雑化である

---

## 12. Runの判断

**現Runは再開しない。新Runへ移る。**

理由は是正報告5章と同じである。加えて、C-5が未解決のままL5を再実行しても、出力がゼロになる可能性がある。

ただし**新Runを作る前に、8.0節のB-1測定を先に行う。** これはコード変更を伴わず、縮小設定で1時間以内に終わり、**その結果によって以後の作業計画が変わる**。

- C-5が障害でない場合 → 提案C→D→Bの順で実装し、新Runを作る
- C-5が障害である場合 → 性能作業より先に、特徴量重複排除（提案A）とfamily分割の仕様判断を行う

---

## 付記: この事故が示していること

L4（25万候補）とL5（5,400万universe）は、別々の不具合ではない。

**較正と本番で入力規模が変わることを、設計も実装もtestも想定していなかった。** 診断moduleは本番データで較正値を取ったが、そのとき使った特徴量セットは`fast`（6空間）であり、本番の9空間・2,550特徴量ではなかった。**較正値そのものが、本番と異なる設定で取られている。**

受入基準（enrichment > 1.5 など）も同じ設定差の影響を受ける。**L5のenrichmentを本番設定で再測定する必要がある。**

これは提案Cのcost model contractだけでは防げない。**「較正時の設定と本番の設定が同一であること」を検証する仕組み**が別に要る。最小の対策は、較正値と一緒に**そのとき使った設定のhash**を記録し、本番実行時に不一致を警告することである。
