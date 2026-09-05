# Description calculation_version更新規則

Status: **CONDUCTOR 0.1.10正式運用規則**

## 1. 目的

`calculation_version`は、Description Databaseに保存したvectorを将来のRunで再利用できるか判断するための計算契約Versionである。CONDUCTOR本体やReportのVersionではなく、各Description Capabilityの出力値とfeature schemaの意味を識別する。

人間が配布済みSkillを直接編集する運用は想定しない。計算script hashはcache signatureへ追加せず、正式なSkill更新時のVersion管理を信頼境界とする。

## 2. 必須条件

- 全Description Capabilityは`capability.json`に`calculation_version`を明示する。
- 形式は正の整数を表す文字列とし、初期値は`"1"`とする。
- 未指定時の暗黙的な`"1"` fallbackは禁止する。
- 欠落、不正形式、空文字はpackage verificationとRuntimeの両方でfail-fastする。
- 一つのCapability IDについて、出力へ影響する変更ごとに単調に増加させる。

## 3. Versionを上げる変更

次の変更では必ず`calculation_version`を上げる。

1. 計算algorithm、数式、ライブラリ呼出し方法の変更
2. SMILES parse、3D生成、最適化、標準化、欠損処理の変更
3. featureの追加、削除、名称、順序、型、単位、意味の変更
4. invalid SMILES、timeout、部分欠損等の出力statusまたはvector表現の変更
5. 固定model、model weight、checkpoint、tokenizerの変更
6. 出力値へ影響する既定parameterの変更
7. bug修正によって既存入力の計算値が変わり得る場合

例:

```text
D019 calculation_version: "1" -> "2"
```

旧Version recordは物理削除しない。新Versionではcache missとなり、新しいrecordを計算・登録する。

## 4. Versionを上げない変更

次の変更だけで計算値とfeature schemaが変わらない場合、Versionは上げない。

- README、SKILL.md、Prompt、説明文の修正
- A009／MMP等のReport Template変更
- log、diagnostic、error messageの表現変更
- test追加
- Runtime schedulingやUI導線だけの変更
- cache lookup／merge処理の修正で、最終vectorが同一であることをtestで確認できる場合

## 5. 他のsignature要素との関係

cache再利用は`calculation_version`だけではなく、Runtimeが生成するcalculation signature全体で判断する。

- `calculation_version`: 計算契約の明示Version
- parameters: Runごとの計算条件
- environment lockfile: 依存環境
- model識別情報: 使用model
- representation／semantics: vectorの意味
- batch-dependent計算ではchemical dataset signature

Parameterや環境が変化してsignatureが一致しない場合は、同じ`calculation_version`でもcache missとなる。逆に、出力へ影響するSkill実装変更をparameterや環境だけで表現できない場合は、必ず`calculation_version`を上げる。

## 6. Modelの運用

- model pathへ異なるweightを上書きしない。
- 可能な場合はimmutableなmodel directoryまたはrevisionを使う。
- model／weight更新は`calculation_version`を上げる。
- model更新を同一Versionとして既存Databaseへ混在させない。

## 7. Release手順

Description Skillを変更した担当者は次を確認する。

1. 同一fixtureの旧版／新版vectorを比較する。
2. 値、列、statusのいずれかが変わる場合はVersionを上げる。
3. capability、canonical catalog、生成copyを同期する。
4. package verifierで全DescriptionのVersionを検証する。
5. Version一致cache hitとVersion不一致cache missのtestを実行する。
6. 変更理由をrelease noteまたはcommit記録へ残す。

## 8. 禁止事項

- Version欠落を暗黙の`"1"`として処理しない。
- 古いrecordのVersionを書き換えない。
- Version不一致を手動でcache hit扱いにしない。
- Reportだけの変更を理由にDescription vectorを無効化しない。
- 計算値が変わる変更を文書修正として扱わない。
