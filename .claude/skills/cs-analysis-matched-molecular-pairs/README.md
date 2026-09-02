# SKILLの目的

Top化合物要因、Hit周辺SAR、または網羅MMPデータを人間向けに提示します。

## 想定利用シーン

Type-Iは各Series／fallback ClusterのTop 1を扱う定型解析、Type-II/IIIはOn-demandです。上位K化合物を詳しく調べる場合は対象IDを明示してType-IIを実行します。Type-I/IIは対象へ接続する成果物だけを保存し、包括的CSV・SQLiteはType-IIIだけが生成します。Type-IIでは、人間が明示した同一RunのType-III Databaseを任意で再利用できます。

Type-I/II対象別HTMLはTargetを常にTo、NeighborをFromとして表示します。同じTarget–Neighborに複数Coreがある場合、HTMLでは最大Coreによる最小変換だけを残します。Target／Neighbor 2D構造、Target全体SMILESと基本情報表、Core・置換前・置換後の詳細表、Neighbor全体／置換前／置換後を横並びにした変換図を固定順で表示し、未縮約データは原本CSVに保持します。

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
| 1.0.0 | Type-I/II/IIIへ再設計 |
