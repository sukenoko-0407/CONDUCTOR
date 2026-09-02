# SKILLの目的

Top化合物要因、Hit周辺SAR、または網羅MMPデータを人間向けに提示します。

## 想定利用シーン

Type-Iは定型解析、Type-II/IIIはOn-demandです。Type-I/IIは対象へ接続する成果物だけを保存し、包括的CSV・SQLiteはType-IIIだけが生成します。Type-IIでは、人間が明示した同一RunのType-III Databaseを任意で再利用できます。

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
