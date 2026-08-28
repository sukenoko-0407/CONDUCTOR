# CONDUCTOR Orchestration Policy

## 目的

手動起動されたMain Agentが一つの人間承認Roundを指揮します。全体に一貫した説明を無理に求めず、GlobalとLocalの変化、独立Description間の支持、矛盾、例外、反証を探します。機械的状態管理と科学process所有は決定論的Runtime、既存結果の解釈は短命Interpreterへ委ねます。

## 基本計算

人間の明示的省略がなければ、高コストを含む全Description、直接構造Clustering、代表DescriptionのVector Clusteringを揃えてからOperator探索へ進みます。MCSも基本計算に含めます。高コストDescriptionはRound開始時に一回だけまとめて承認します。

## Operator探索

探索段階は`exploration`一種類です。初期探索と追加探索を別FSMや別commandとして扱いません。

Runtimeは人間指定のOperator予算内で、次の単純な規則により最大25 Analysis Nodeずつ選びます。成功ResultをGlobal、Global–Local、sibling ClusterのReview Bundleへまとめ、既定4 Bundleずつ絶対評価してから次のSliceへ進みます。Wall Timeだけでは予算を増やしません。

1. 成功済み同一signatureを除外する。
2. Globalを優先し、概ね`Global, Global, Local`の比率にする。
3. 過去のCapability、Description／Clustering、scopeの実施数が少ない候補を優先する。
4. 同点は固定seedで選び、Roundを跨いで偏りと重複を抑える。
5. Localは同一Operator・互換入力のGlobal comparatorがある場合だけ選ぶ。

これは機械的に科学結論を決める規則ではありません。`SCIENTIFIC_DECISION`では人間priority、Insight、反証候補に基づき、同一Clusterの別Operator、sibling Cluster、Global比較、別Description上の同一Cluster等をMainが選びます。

一次評価は`favorable_evidence`、`context_contrast`、`evidence_specificity`の0～3絶対軸です。合計点を作らず、sample support、comparator validity、effect stability、independenceを分離します。化学的実行可能性はMedicinal Chemistが判断します。Localで必須Global comparatorがなければ採点しません。Description／Clusteringの基本計算はOperator予算の外です。

## MMP

A014の定型フローはGlobal DBを一度だけ作り、Local screening／detail Nodeを自動計画しません。通常InterpretationはcompactなGlobal Result Cardだけを扱います。Global–Local比較は、人間がRound終了後に`cs-analysis-interpret-mmp`を起動し、そのRoundで成功したGlobal DBとcanonical Cluster membershipをread-onlyに再集計して行います。過去RoundのDB再利用には人間によるA014 Node ID指定が必要です。

全Pair詳細はCSVへ保持しますが、DBは正規化し、反復文字列、派生Summary、native work DBを重複保存しません。MMPを通常Operatorの全直積へ展開しません。

## Clusterとmetric

5化合物未満のClusterは登録しません。30化合物未満のlocal modelは作りません。全体の50%超を占めるClusterはGlobalに近いことを解釈へ明記します。構造凝集性が高い小Clusterには優先余地があります。

Vector Clusteringは手法別calibrationを使います。binary fingerprintはTanimoto、USR/USRCATはManhattan、embedding／疎countはCosine、一般連続descriptorは標準化後Euclideanを原則とし、endpointをparameter選択へ使いません。

## 複数Roundと終端

過去結果は削除せず、短いResult Card、Review Bundle、可変Candidate class／attentionで取捨選択します。Roundを跨いで全Artifactや長文Reportを読み直しません。人間意見は次のRound contractへ添付します。Orchestratorは新Roundを自発的に作りません。

Roundは人間が`screening`または`full`を開始時に選びます。`screening`は評価索引、Round CSV、compact summary、Full Auditまで、`full`はさらに選抜Resultからの正式Interpretationまでが一単位です。ゼロInsightでもfull Reportを作ります。許可済み作業が残る間は理由なく終了せず、予算へ達したら未実行候補を次Roundへ送ります。read-only MMP Interpretationは人間起動の補助成果物であり、Round gateには含めません。
