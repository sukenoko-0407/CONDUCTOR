# Evidence Interpretation

## SKILLの目的

Operator EvidenceをDescription、Grouping、Group、scope、metric、Roundを横断して整理し、専用Agentが人間向けの解釈レポートを作るための下書き・context・rendererを提供します。

## 想定利用シーン

global/local差、Group間差、異原理Description間の一致、矛盾、例外、negative resultを比較し、Finding・Hypothesis・Question・追加解析候補を整理するときに利用します。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を自動構築・再利用し、cacheをSkill内`env/`へ固定します。

## 利用例

一般利用:

```bash
python .claude/skills/cs-analysis-interpret-evidence/scripts/launch.py \
  --evidence-dir path/to/evidence
```

CONDUCTOR利用ではOrchestratorが`NI####`、`RND####`、ID reservation、State、出力先をすべて指定します。生成直後は機械下書きであり、専用Interpreterが編集後に`render`します。

同じRunでもRoundごとに新しい`NI####`を作ります。同一Roundで視点を分ける場合は、Orchestratorが`--interpretation-focus`を記録します。

## 制約事項

- Interpretationはread-onlyの終端処理であり、Stateや計算Nodeを変更しません。
- 新規IDはState予約を使い、以前のIDを更新するときはrevisionを増やします。
- Markdown/HTMLは作業記録ではなく、具体的な観察・解釈・制約を示す人間向けレポートです。
- Questionは深掘り義務ではなく、人間がallow/defer/skipを判断できます。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 複数Roundの継続ID、Question、選択的Evidence、解釈レポートに対応。 |
