# CONDUCTOR 0.2.1 R1 実装質問

この文書には、R1 実装前に正本間の不一致または未定義を解消する必要がある事項だけを記載する。blocking 質問は、該当 stage のコードを推測で実装しない。

## Q-001 L4 candidate cap の既定値

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-14/M-15、`CONDUCTOR_0.2.1_R1_remediation_plan.md`
- **何が不明か**: M-14 は `l4 max_candidates = 250,000` を既定値として示す一方、M-15 は cap 250,000 を optional/separable とし、採用は M-12/M-13 後の判断としている。現行値100から R1-1 で上げるのか、R1-10 まで維持するのかが一意でない。
- **仮に進めるならどうするか**: R1-1〜R1-9 は現行 cap 100を維持し、M-12/M-13、64 GiB guard、2M row guard、段階性能試験の合格後、別 commit の R1-10 で250,000へ変更する。
- **その案で進めた場合の影響**: 安全性は高いが、M-14 表を文字どおり defaults へ反映した状態にはならず、R1-9までは探索範囲が限定されたままになる。

## Q-002 L2b/L7 の時間予算に使う処理速度

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-1/M-14 と「変更しない範囲」
- **何が不明か**: M-1 は全 Lens に `WorkEstimate` を要求するが、M-14 の `units_per_second` は L5/L1b/L2a/L4 だけで、L2b/L7 の値と unit 定義がない。未知値のまま `unit_count / units_per_second <= 3600` を判定できない。
- **仮に進めるならどうするか**: L2b/L7 には family/memory estimate だけを適用し、時間 gate は未適用と明記する。production 前に限定 fixture で unit と throughput を測定し、defaults 追加後に時間 gate を有効化する。
- **その案で進めた場合の影響**: R1-1 時点では全 Lens に同一の1時間保証を与えられない。一方、根拠のない速度を設定して誤って合格・停止させることは避けられる。

## Q-003 全 Lens progress と L2b/L7 非変更方針の両立

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-2 と変更禁止範囲
- **何が不明か**: M-2 は全 Lens の loop progress を要求するが、同じ文書は `l2b.py` と `cs-lens-l7` を変更しないとしている。wrapper だけでは process の生存 heartbeat は出せても、内部の honest `completed_units` は取得できない。
- **仮に進めるならどうするか**: L1b/L2a/L4/L5 は core callback で実進捗を出す。L2b/L7 は wrapper が `completed_units=0` の liveness heartbeat だけを出し、完了時に100%へする。これは loop progress ではないことを manifest に記録する。
- **その案で進めた場合の影響**: Runtime の無通信監視は全 Lens で可能になるが、L2b/L7 の途中進捗率と estimate/actual unit 比は得られない。

## Q-004 M-6 を L1b へ適用する科学的意味

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-6、現行 `conductor_lens_l1b/l1b.py` と Phase 1 distance artifacts
- **何が不明か**: L5 は feature 列を直接使うため代表 feature 化が明確だが、L1b は space 単位の既成 distance matrix を入力にする。代表 feature を L1b へ適用するには distance を再構築する必要があり、context builder が使った distance と L1b が使う distance が異なる可能性がある。また、space をまたぐ相関 component で代表が別 space に選ばれた場合の扱いも未定義である。
- **仮に進めるならどうするか**: feature dedup は space 内だけで行い、各 space に最低1代表を残す。Phase 1 で representative mapping と reduced distance artifact を同時生成し、context builder と L1b の両方が同じ reduced distance を使う。ただしこれは context builder 非変更方針を変更するため、明示承認を必要とする。
- **その案で進めた場合の影響**: L1b の計算量と family は減るが、context membership と lambda が変わる科学的仕様変更になる。Phase 1/context artifacts の再生成が必須で、旧 Run は再開できない。

## Q-005 Calibration signature の比較対象

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-7
- **何が不明か**: signature に含める field と mismatch 時の warning-only は定義されているが、「現在の signature」を何に対して比較するか、reference calibration の path/config field/選択規則がない。
- **仮に進めるならどうするか**: `calibration.reference_manifest` という絶対 path の config を追加し、存在する場合だけ hash を比較する。未指定は warning ではなく `not_compared` と記録し、Run を止めない。
- **その案で進めた場合の影響**: 比較が明示的で監査可能になるが、新しい config 契約が増える。reference を指定し忘れた Run は signature を記録しても drift warning を出せない。

## Q-006 L4 の descriptor cost と scoring cost の結合方法

- **区分**: blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-1/M-14/M-15/M-16
- **何が不明か**: L4 の throughput は `candidate*space/s` で定義される一方、同一 node 内の re-description は `candidate*cost_weight` と実測 ms/cost-unit で支配される。`WorkEstimate` には単一 `unit_count` しかなく、一方だけでは1時間 budget を正しく判定できない。
- **仮に進めるならどうするか**: `unit_count=C4*S4` を公称値として維持し、`detail.description_cost_units=W` を使って `estimated_seconds=(C4*S4)/31700 + W*0.00804/available_workers` と Runtime の L4 専用式で評価する。
- **その案で進めた場合の影響**: 現行 dataclass を変えず両コストを扱えるが、Lens 共通の `unit_count / units_per_second` という単純規則に L4 だけ例外が入る。0.00804秒が並列 worker に完全反比例しない場合は過小評価し得るため、保守係数が必要になる。

## Q-007 Work estimate の起動プロトコル

- **区分**: non-blocking
- **出所**: `CONDUCTOR_0.2.1_R1_implementer_brief.md` の M-1、現行 Runtime/Skill CLI
- **何が不明か**: `estimate_work(inputs)` は定義されているが、Runtime が Python API として import するか、Skill の Pixi 環境内で CLI として起動するかは指定されていない。
- **仮に進めるならどうするか**: 通常 workload と同じ `launch.py` に `--estimate-work` を渡し、stdout の JSON 1行を Runtime が検証する。推定は output directory を作らず、同じ request/config/input を読む。
- **その案で進めた場合の影響**: dependency/version 差を含めて本番 Skill 環境で推定でき、Runtime と各 Lens の package 依存を結合しない。一方、各 node の前に短い subprocess 起動 overhead が加わる。

## 集計

- 質問数: 7
- blocking: 6
- non-blocking: 1

---

# 設計担当からの回答（2026-09-19）

**7件すべてに確定回答します。blocking は残りません。**

質問の品質が高く、**うち3件は正本側の欠陥を突いています**（Q-001 の矛盾、Q-004 の適用不能、Q-006 の設計不備）。
該当箇所は修正計画書と仕様概要書を改訂しました。**以後は改訂後の記述を正とします。**

あわせて、**詳細計画に1件の正確性欠陥**と**1件の許容幅の誤り**を見つけました。第A節に記します。

---

## A-001 【重大・正確性】M-10a の近傍は「文脈内」から選ぶこと

詳細計画 M-10a にこうあります。

> space ごとに stable exact sort した full neighbor table を一度作り、context member index を連結して利用する

**この記述は2通りに読め、一方は誤りです。**

| 読み方 | 正誤 |
|---|---|
| 距離行列の各行を全体で整列し、**上から辿って文脈メンバーだけを k 個拾う** | **正しい** |
| 全化合物に対する上位 k の表を作り、**そこから文脈メンバーを絞り込む** | **誤り** |

L1b の λ は「**文脈の中での**近傍による予測誤差」です。全体上位 k に文脈メンバーが1つも入らないことは普通に起きます。
後者の読み方は静かに間違った λ を返し、**テストが 1e-9 許容なら気づけません。**

> **要件: 各 (space, context) について、近傍は必ずその文脈のメンバーの中から k 個選ぶこと。**

構成方法は任意です。次のどちらでも構いません。

- 文脈の部分行列を取り出して整列する（設計担当の検証実装はこちら）
- 全体行を整列しておき、文脈メンバーを上から k 個拾う（メモリ `S*N*N*4` を許容できるなら可）

**同順位の扱いは「距離昇順、同距離なら化合物 ID 昇順」です。** 現行 `np.lexsort((candidates, distance))` の
`candidates` は `ids`（compound_id 昇順）への位置添字なので、詳細計画の「compound ID lexical」という記述と一致します。**この点は正しいです。**

## A-002 【許容幅の誤り】M-10a は exact であって 1e-9 ではない

詳細計画 §5 M-10a と §7.3 が `relative difference <= 1e-9` としています。
**引き継ぎ書 6.1 の指定は「完全一致」です。**

設計担当の検証では、連続距離40試行・同順位距離（整数距離行列）ともに **相対差 0.000e+00** でした。
同じ値を同じ順序で足すだけなので、丸め差は生じません。

> **1e-9 を許容すると A-001 の取り違えを検出できません。exact を受入条件にしてください。**
> **同順位距離を含む fixture を必ず入れてください**（設計担当は整数距離行列で確認しました）。

`<= 1e-9` でよいのは **M-5（L5 の相関、実測 3.72e-10）と M-12a（L4 の距離、実測 4.82e-16）**だけです。
こちらは平方展開・行列積で演算順序が変わるため、厳密一致を要求できません。
**M-11a（L2a の delta）も exact です。** 整数添字の gather で丸めが生じません。

---

## Q-001 L4 candidate cap の既定値 → **あなたの案を採用します**

**正本側の矛盾です。指摘のとおりでした。**
修正計画書 M-14 の表に `L4 候補 cap | 250,000（据え置き）` と書いてあり、M-15 と矛盾していました。
**「据え置き」は現行値 100 を指すつもりでしたが、250,000 と併記したため意味が壊れていました。**
M-14 の表を `100（現行維持。引き上げは M-15）` へ改訂しました。

> **確定: R1-1〜R1-9 は cap 100 を維持します。250,000 への変更は R1-10 の別 commit です。**

「R1-9 までは探索範囲が限定されたまま」という影響認識も正しいです。**それを受け入れます。**
R1 の目的は Finding がゼロになる状態の解消であり、探索範囲の拡大は別の目的です。混ぜません。

## Q-002 L2b/L7 の `units_per_second` → **実測値を与えます。時間 gate は全 Lens に適用してください**

**「根拠のない速度を設定しない」という判断は正しいです。** 値がなかったのは正本の不備でした。
本日このマシンで実測しました。

| Lens | unit の定義 | 1 permutation | B=1000 | `units_per_second` |
|---|---|---|---|---|
| **L2b** | **系列内 observation 数**（`_contributions` が走査する延べ件数） | 62.0 ms | 1.03 分 | **50,858** |
| **L7** | **candidate × question** | 14.3 ms | 14.3 秒 | **6,004** |

```text
L2b: unit_count = (B+1) x 系列内 observation 合計   （実測時 3,155）
L7 : unit_count = (B+1) x candidate 数 x 2          （実測時 86）
```

L7 の値が小さいのは、`np.random.default_rng()` を candidate ごと・反復ごとに作っているためです。
**総時間が 14.3 秒なので最適化しません。** 遅さの理由が分かった上で据え置きます。

> **確定: 時間 gate は全 Lens に適用してください。例外は作りません。**

これらは開発機（12コア）の値であり、**本番では下回りません**。gate が誤って停止させる方向には働きません。
`estimate/actual` の比が3倍以上ずれたら警告する仕組み（M-14）で、値の劣化は検出できます。

## Q-003 progress と「L2b/L7 非変更」の両立 → **あなたの案を採用します**

**「変更しない」の意味を明確にします。**

> **変更しないのは、統計的契約とアルゴリズムです。ファイルに一切触れるな、という意味ではありません。**

progress callback の追加は意味論を変えない機械的変更なので、**`l2b.py` と `l7.py` に入れて構いません。**
ただしあなたの案のほうが優れています。理由は総所要時間です。

| Lens | B=1000 の所要 | loop progress の必要性 |
|---|---|---|
| L5 | 7.3 分 | **必要** |
| L2b | 1.03 分 | 境界。あってもよい |
| L1b | 0.5 分 | 境界 |
| L7 | 14.3 秒 | **不要** |
| L2a | 1.6 秒 | **不要** |

M-2 の目的は「人間が気づけること」です。**14 秒の Node に進捗率は要りません。**

> **確定: L1b / L2a / L4 / L5 は core callback で実進捗を出す。L2b / L7 は wrapper の liveness heartbeat のみ。**
> **manifest に `progress_granularity: "loop" | "node"` を記録してください。**

`completed_units=0` を出すより、**`progress_granularity` を明示するほうが監査上わかりやすい**ので、
そちらを正式な形式とします。L2a は 1.6 秒で終わるため実際には報告が1件も出ませんが、契約としては `loop` です。

## Q-004 M-6 を L1b へ適用する意味 → **M-6 から L1b を外します**

**これが最も重要な指摘です。正本の誤りでした。**

修正計画書 M-6 の対象を「L5 / L1b」と書いたのは誤りです。**L5 のみが正しい。**

理由は3つあり、いずれもあなたの分析と同じ方向です。

1. **L1b の入力は space 単位の距離行列であり、feature 列ではありません。** 代表 feature 化を適用するには距離を作り直す必要があり、これは文脈カタログの再生成を伴います。**影響範囲が桁違いです。**
2. **M-10a 適用後、L1b の計算量に feature 数は現れません。** コストは `(space × context × member) × k` の gather であり、`O(m·k)` です。**dedup しても速くなりません。**
3. **dedup は族を縮めません。** これは初版測定で確認済みです（1,155,558 → 1,154,917）。L1b の族は M-10b（空間別分割）が 763 → 84 にします。**M-6 の出番がありません。**

> **確定: M-6 は L5 のみに適用します。context builder は変更しません。Phase 1 artifacts の再生成も不要です。**

「明示承認を必要とする」という判断は正しく、**承認しません。**
文脈が変わると λ も Finding も変わり、R1 の他の変更の効果を切り分けられなくなります。

修正計画書と仕様概要書の M-6 / R1-6 の記述を「L5 のみ」へ改訂しました。

## Q-005 Calibration signature の比較対象 → **あなたの案を採用します（1点だけ変更）**

設計の骨格は正しいです。`not_compared` を明示的な状態として記録する判断も良い。

**変更点は1つだけです。絶対パスをやめてください。**

```text
calibration.reference_manifest  : project root からの相対パス
未指定 / ファイル不在           : not_compared として記録し、Run を止めない
不一致                         : warning。threshold を自動変更しない
```

絶対パスは開発機と本番機（Ubuntu）で壊れます。**この Run は環境を跨ぎます。**

> **確定: 相対パス。未指定は `not_compared`。不一致は warning のみ。**

「reference を指定し忘れた Run は drift warning を出せない」という影響は受け入れます。
**M-8 で較正を取り直した時点で、その成果物を既定の reference として `defaults.yaml` に書いてください。**
それ以降は指定忘れが起きません。

## Q-006 L4 の descriptor cost と scoring cost の結合 → **`WorkEstimate` に `estimated_seconds` を追加します**

**指摘のとおり、`unit_count / units_per_second` という単一規則が設計不備です。**
ただし「L4 だけ例外」にはしません。**規則そのものを変えます。**

```python
@dataclass(frozen=True)
class WorkEstimate:
    unit_count: int
    family_size: int
    peak_memory_bytes: int
    estimated_seconds: float      # ← 追加。各 Lens が自分のコストモデルで算出する
    detail: dict[str, int]
```

| 役割 | 変更前 | 変更後 |
|---|---|---|
| Runtime の時間 gate | `unit_count / units_per_second` | **`estimated_seconds`** |
| `units_per_second` | gate の分母 | **各 Lens の estimator の内部定数**。設定に置く |
| `unit_count` | gate の分子 | **`estimate/actual` 比の検証用に残す** |

これで L4 の複合コストは L4 の estimator の中に収まります。**Runtime 側に Lens 固有の式が漏れません。**

L4 の式はあなたの案をそのまま採用します。**保守係数 1.25 を掛けてください**（M-16 のメモリ係数と同じ値）。

```text
estimated_seconds = (C4*S4)/units_per_second_l4 + W*0.00804/available_workers
最終値 = 上式 x 1.25
```

> **「0.00804 秒が並列 worker に完全反比例しない場合は過小評価し得る」という懸念は正しいです。**
> 記述子計算は分子ごとに独立なのでスケールは良いはずですが、**保守係数はその不確実性のために置きます。**
> `estimate/actual >= 3` の警告（M-14）で実際のずれを観測し、必要なら係数を上げてください。

他の Lens は `estimated_seconds = unit_count / units_per_second * 1.25` で構いません。

## Q-007 Work estimate の起動プロトコル → **あなたの案を採用します**

`launch.py --estimate-work` で stdout に JSON 1行、が正しい設計です。

**Runtime と各 Lens の依存を結合しないことが決定的に重要**で、あなたの理由付けもそこを突いています。
Pixi で環境を分離している以上、Python API の import は選べません。

> **確定: subprocess 方式。推定は出力 directory / Database / Runtime state を作らない。**

subprocess の起動 overhead は Node あたり1回・数秒であり、Node 予算 60 分に対して無視できます。

---

## 詳細計画についてのその他の確認

### 良いと判断した点

| 箇所 | 評価 |
|---|---|
| §3.3 「5秒以上**かつ**1%以上」を AND と読んだこと | **正しい読み方です** |
| §3.3 stdout/stderr を別 thread で drain する | deadlock を避けるために必要。良い |
| §3.4 family key を tuple の canonical JSON で記録 | 文字列連結より良い。採用してください |
| §3.4 統計契約変更の前後で resume を禁止 | **必須です** |
| §4 `family_size` を設定値ではなく入力の走査で求める | **これが正しい。** 設定からの上限では guard が働きません |
| §5 M-12a 「space を逐次処理し、全 space の距離行列を同時保持しない」 | 良い |
| §5 M-11a 「candidate 0件なら permutation engine を起動しない」 | 現行は候補ゼロでも 4 分捨てています。直してください |
| §7.1 既存テストの期待値変更の洗い出し | 漏れなく見えます |
| §9 工数見積り 29–44 person-day | 妥当と判断します |

### 追加で守ってほしいこと

1. **§3.2 の gate 判定 1 で L4 を family_size gate から外す際、`family_gate: "exempt_parametric"` を manifest に記録してください。** 黙って skip しないこと。L4 が parametric な t 検定であることが理由です。
2. **§4.2 の L1b メモリ式に `S*N*N` が入っていますが、9空間 × 961² × 8 = 66 MB です。** 正しく小さい。ただし A-001 の「全体行を整列する」構成を採るなら `S*N*N*4`（整列済み添字）が加わります。**採用する構成に合わせて式を確定してください。**
3. **M-15 についてのあなたの見解（条件付き採用候補、別 commit）に同意します。** 設計担当も断定していません。R1-10 で段階測定（10k → 50k → 250k）を行うという案も妥当です。

---

## 回答後の次の手順

1. 本回答を反映して詳細計画を改訂してください。特に **A-001 / A-002 / Q-004 / Q-006** は記述の変更が必要です。
2. 改訂版を報告してください。**その時点で実装へ進んで構いません。**
3. 段階R1-3 を終えたら、**族サイズと Finding 件数を報告して一度止まってください。**

**追加の不明点が出たら、同じ形式でこの文書へ追記してください。独断で決めないでください。**

