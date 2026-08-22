# CONDUCTOR Orchestration Policy

## 目的

手動起動されたMain Agentが一つの人間承認Roundを指揮します。全体に一貫した説明を無理に求めず、GlobalとLocalの変化、独立Description間の支持、矛盾、例外、反証を探します。機械的状態管理はRuntime、科学計算は短命Executor、既存結果の解釈は短命Interpreterへ委ねます。

## 基本計算

人間の明示的省略がなければ、高コストを含む全Description、直接構造Clustering、代表DescriptionのVector Clusteringを揃えてからOperator探索へ進みます。MCSも基本計算に含めます。高コストDescriptionはRound開始時に一回だけまとめて承認します。

## Operator探索

探索段階は`exploration`一種類です。初期探索と追加探索を別FSMや別commandとして扱いません。

Runtimeは次の単純な規則で最大100 Analysis Nodeを選びます。

1. 成功済み同一signatureを除外する。
2. Globalを優先し、概ね`Global, Global, Local`の比率にする。
3. 過去のCapability、Description／Clustering、scopeの実施数が少ない候補を優先する。
4. 同点は固定seedで選び、Roundを跨いで偏りと重複を抑える。
5. Localは同一Operator・互換入力のGlobal comparatorがある場合だけ選ぶ。

これは機械的に科学結論を決める規則ではありません。`SCIENTIFIC_DECISION`では人間priority、Insight、反証候補に基づき、同一Clusterの別Operator、sibling Cluster、Global比較、別Description上の同一Cluster等をMainが選びます。

Wall Timeは実行余裕でありNode上限を増やしません。Description／Clusteringの基本計算はAnalysis 100件の外です。

## MMP

A014 Global DBは一度だけ作り、全Cluster screeningと後続RoundのLocal照会へread-onlyで再利用します。標準は1～2 cuts、radius 0～2、core heavy atoms 8以上、core fraction 0.5以上、variable heavy atoms 10以下です。3 cutsまたはradius 3～5は人間が明示した拡張探索だけで使います。

全Pair詳細はCSVへ保持しますが、DBは正規化し、反復文字列、派生Summary、native work DBを重複保存しません。MMPを通常Operatorの全直積へ展開しません。

## Clusterとmetric

5化合物未満のClusterは登録しません。30化合物未満のlocal modelは作りません。全体の50%超を占めるClusterはGlobalに近いことを解釈へ明記します。構造凝集性が高い小Clusterには優先余地があります。

Vector Clusteringは手法別calibrationを使います。binary fingerprintはTanimoto、USR/USRCATはManhattan、embedding／疎countはCosine、一般連続descriptorは標準化後Euclideanを原則とし、endpointをparameter選択へ使いません。

## 複数Roundと終端

過去結果は削除せず、短いResult Cardと可変attentionで取捨選択します。Roundを跨いで全Artifactや長文Reportを読み直しません。人間意見は次のRound contractへ添付します。Orchestratorは新Roundを自発的に作りません。

RoundはInterpretationとFull Auditまでが一単位です。ゼロInsightでもReportを作ります。許可済み作業が残る間は理由なく終了せず、100 Analysis Nodeへ達した場合は残候補を次Roundへ送り、当該RoundのInterpretationへ進みます。
