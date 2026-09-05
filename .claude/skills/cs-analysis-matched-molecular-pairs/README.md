# SKILLの目的

Top化合物要因、Hit周辺SAR、または網羅MMPデータを人間向けに提示します。

## 想定利用シーン

Type-Iは各Series／fallback ClusterのTop 1を扱う定型解析、Type-II/IIIはOn-demandです。上位K化合物を詳しく調べる場合は対象IDを明示してType-IIを実行します。Type-I/IIは対象へ接続する成果物だけを保存し、包括的CSV・SQLiteはType-IIIだけが生成します。Type-IIでは、人間が明示した同一RunのType-III Databaseを任意で再利用できます。

Type-I/II全体HTMLはanalysis unitごとのTargetを4列で示します。対象別HTMLの最上部には、Targetを中心、Exact Coreを中間、Neighborを外周とする横長のMMP relationship mapを表示します。Neighbor cardには置換前fragment、Endpoint、Favorable deltaを改行して示します。Targetは紺、Exact Coreは緑、Neighborはオレンジです。関係図はExact Core上位3件・各CoreのNeighbor上位3件までとし、省略時は図中に件数とSection 4への導線を明記します。Section 1ではTargetを単独行、その下の折り畳み領域へTargetに2D整列したNeighborを4列で示します。同じTarget–Neighborでは包含される小さいCoreを除き、包含関係にないCoreは残します。Exact Coreごとにcard化し、Favorable delta上位5件を展開、残りを折りたたみます。変換図はNeighbor全体／Target全体／置換前／置換後の4列で、Targetは共通構造によりNeighborへ2D整列します。Core画像と件数cardは横並びにし、HTMLでの整理・折りたたみ状況は実件数で説明します。Section 4は主要galleryを先に置き、`表示内容`と`掲載範囲`を別々の折り畳みにし、詳細CSVリンクをSection末尾へ配置します。未縮約データは詳細CSVに保持します。

## 環境構築

PixiがRDKitとmmpdbを準備します。

## 利用例

CONDUCTORではRuntimeが作成したRequestをLauncherへ渡します。

```bash
python scripts/launch.py --conductor-request /absolute/path/execution_request.json
```

## 制約事項

1-cutのみ。外部SMILESだけのType-II対象は受け付けません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 0.1.10 | 対象別レポート最上部へMMP relationship mapを追加。Section 4の表示内容／掲載範囲を分離し、詳細CSVリンクを末尾へ配置 |
| 1.0.0 | Type-I/II/IIIへ再設計 |
