# CONDUCTOR 0.2.1 HTMLレポートガイド

## 1. レポートの目的

HTMLはFindingを人間が検討するための入口です。単なる表ではなく、「構造・条件・効果・統計・反証・根拠」を
Lensに適した図でまとめます。一方、監査正本はRun内のJSON/JSONL、Evidence table、artifact manifestです。

## 2. 出力構成

```text
P06 output/
├── report.html                         # 全体入口
├── finding_reports/
│   ├── <rank-1 finding_id>.html        # 上位20件すべて
│   └── ...
├── report.json
├── final_findings.jsonl
├── citation_validation.json
└── artifact_manifest.json
```

- `report.finding_page_k=20`: 標準で個別HTMLを作る件数。
- `report.overview_detail_k=10`: 表紙で図と説明を展開する件数。
- `scoring.display_k=10`: Scoringの受入gate。レポート件数とは別の設定。

reportable Findingが20件未満なら、その全件について個別HTMLを作成します。20位より下も、人間がFinding IDを
指定すれば、受入済み成果物から追加LLM・追加解析なしでRun root外へ生成できます。

## 3. 表紙

表紙は次の順で読みます。

1. 監査状態、Finding数、LLM failure fraction。
2. 1～10位の詳細card。Lens固有図、claim、effect、support、p/q、score、deep-diveを確認。
3. 11～20位のタイトル一覧。興味があるものを個別pageで開く。
4. Lens別Finding数と、Findingを共有entityで結んだcomponent narrative。
5. 監査付録。全Finding、telemetry、citation registry。

順位はp値昇順ではありません。p/q値は必要条件の一部で、最終順位は固定gate後のcomposite scoreです。

## 4. 個別レポート

個別HTMLには必ず以下を含めます。

- Finding ID、Lens、rank、Endpoint
- claim、condition、effect direction／effect size／unit、support_n
- 全testのstatistic、p、q、多重性族
- score 5軸とcomposite
- triviality／confounder評価
- deep-dive状態と引用付きnarrative
- falsification ruleとparameters
- 関連entity、引用Evidence行
- Lens固有の科学図

引用にない外部知識や機序推定は追加しません。図の入力が不足する場合は文章だけで代替せず、P06を
reporting contract errorとして停止します。

## 5. Lens固有図

### L1b — 局所SAR

注目化合物と解析時に保存した距離順近傍を2D構造で示し、Endpointと局所誤差改善を可視化します。
レポート生成時に近傍探索をやり直しません。

### L2a — 文脈依存MMP

変換fragmentのbefore/after、代表full-molecule pair、文脈内外の実測効果分布を示します。
「どの置換が、どの文脈で効いたか」を構造と数値の両方で確認できます。

### L2b — fragment効果

fragment構造、系列別残差寄与、fragment一致部を強調した代表化合物を示します。一貫性と異質性を
同じ形式で比較できます。

### L4 — Frontier candidate

未観測candidate、既知source、sourceからcandidateへの到達関係、feature-space別の近傍Endpoint分布を示します。
候補は予測値ではなく、探索優先度として読みます。

### L5 — 相関反転／条件依存関係

focal contextと補集合を色分けしたfeature–Endpoint散布図と群別回帰線を示します。全体相関では隠れる
方向差を確認します。

### L7 — 系列間移植性

両series core、共通R-group、同じR-groupを持つ代表実測化合物pair、系列A/BのEndpoint対応を示します。
SARの移植可能性またはrank reversalを構造対応とともに確認します。

## 6. 信頼性の確認

個別知見を採用する前に、最低限次を確認します。

- pipeline stateが`reportable`である。
- q値、多重性族、support_nが目的に対して妥当である。
- deep-diveがSURVIVED／WEAKENED／REFUTED／INCONCLUSIVEのどれか。
- Evidence行と図がclaimを直接支える。
- falsification ruleに対する次の実験が現実的である。

LLM narrativeがnullでも、決定論的Findingと図は失われません。逆に文章が自然でもcitation validationが
失敗したRunは正式受入できません。

## 7. 既存受入Runへの適用

HTML実装前のRunには
[`prompt/CONDUCTOR_0.2.1_R1_HTML_report_export_prompt.md`](prompt/CONDUCTOR_0.2.1_R1_HTML_report_export_prompt.md)
を使用します。RuntimeとP06 manifestを照合し、hash検証済みP03/P06成果物からRun root外へ派生出力します。
P06、Lens、scoring、LLMは再実行しません。
