# CONDUCTOR 0.1.4 仕様変更履歴

0.1.4は0.1.3のMain Agent Orchestration、短命Executor／Interpreter、Runtime単一Writer、5状態Node、DAG、最大200 Analysis Node、人間管理のRoundを維持した加算的更新です。

## 主な変更

- Operator `A014 cs-analysis-matched-molecular-pairs`を追加。
- mmpdb 3.1.4で1～3 cutを列挙し、Exact CoreとEnvironment radius 0～5を保持。
- Global MMP Database、非圧縮全情報CSV、Parquet、集約表、固定HTMLを生成。
- 全Clusterを一つのScreening Nodeで確認し、代表的なClustering viewだけをLocal detailへ進める。
- MMPが見つからない結果も成功したNegative Resultとして保持。
- MMP instance数と一意な化合物Pair数を分離し、効果をPair-weighted、Core差をCore-weightedで集約。
- Global／Cluster-local HTMLを固定section、日本語、低彩度、構造図埋め込みで生成。
- A014 Globalを単独Execution packetとし、複数Artifactを行数照合後にatomic promotion。
- 0.1.3 Run StateとArtifactを読込み可能とし、既存Active RoundへA014を遡及追加しない。

Description、Clustering、A001～A013の科学計算kernelと一般利用CLIは変更していません。
