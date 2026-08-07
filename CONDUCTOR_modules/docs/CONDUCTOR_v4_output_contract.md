# CONDUCTOR 4.3.0 出力契約

## 1. 共通規則

- 一般利用とCONDUCTOR利用を明確に分ける。
- `--output-dir`があれば規定保存先より優先する。
- 既存成果物を暗黙に上書きしない。
- 全artifactへ生成元Skill、version、設定、input hash、作成時刻を記録する。
- 科学計算結果はimmutableとし、salienceやQuestion statusを書き戻さない。

## 2. 一般利用

`--conductor`を付けない。既定保存先は以下とする。

```text
results/<stage>/<skill-name>/<timestamp-or-input-basename>/
```

Descriptionは主にCSV、Clusteringはmembership／summary CSV、Operatorは数値CSVを返す。CONDUCTOR専用State、Round、Evidence ledgerを要求しない。

## 3. CONDUCTOR利用

Orchestratorが`--conductor`、project、run ID、予約Node ID、設定、node固有output directoryを渡す。

```text
results/CONDUCTOR/<project>/<run-id>/
├─ state.json
├─ snapshots/
├─ summaries/
│  └─ state_summary.json
├─ indices/
│  ├─ coverage_index.json
│  ├─ evidence_digest.jsonl
│  ├─ salience_view.jsonl
│  ├─ salience_history.jsonl
│  ├─ question_ledger.jsonl
│  └─ relation_index.jsonl
├─ rounds/
│  └─ RND0001/
├─ description/
├─ grouping/
├─ analysis/
└─ interpretation/
```

`CONDUCTOR_modules/`へ解析結果を書き込まない。

## 4. Description

```text
description/<skill-name>/<ND####>/
├─ <description>.csv
├─ description_manifest.json
├─ execution_event.json
└─ warnings.json                 # warningがある場合
```

manifestはrepresentation family、value semantics、natural metric、algorithm parameter、seed、model／conformer情報を含む。standalone数値CSVの意味を変更しない。

## 5. Grouping

```text
grouping/<skill-name>/<NG####>/
├─ cluster_membership.csv
├─ cluster_summary.csv
├─ grouping_manifest.json
├─ group_registry.json
└─ execution_event.json
```

run全体のGroup indexは以下へ集約する。

```text
grouping/group_index/
├─ group_registry.csv
└─ Cpd_Group_matrix_G000000_099999.csv
```

Group IDはrun-globalとし、Grouping Skillのlocal labelとは分離する。registryはsource Node／Description、algorithm、parameter、membership semantics、count、statusを持つ。

## 6. Operator

```text
analysis/<skill-name>/<NO####>/
├─ <operator-result>.csv
├─ evidence.json
├─ evidence_digest.json
├─ operator_report.html
├─ analysis_manifest.json
└─ execution_event.json
```

数値CSVは科学計算の正本、`evidence.json`は機械可読な観察、digestはRound間の軽量検索用、HTMLは人間が個別解析を確認するためのreportである。

Evidenceにはrun-global Evidence ID、Operator、scope、sample数、Group、評価Description、Grouping、metric、主要統計、不確実性、warning、artifact pathを含める。大量の行やpairをInterpretationへ複製せず、CSVまたは補助artifactへの参照にする。

## 7. Interpretation

```text
interpretation/<NI####>/
├─ interpretation.json
├─ interpretation.md
├─ interpretation.html
├─ interpretation_context.json
├─ id_reservation.json
├─ triage_updates.json
├─ question_updates.json
├─ relation_updates.json
├─ analysis_requests.json
└─ execution_event.json
```

過去Interpretationを上書きしない。Finding、Hypothesis、Question、RelationはRun内IDを引き継ぎ、同一entityの変更はrevisionとして記録する。

## 8. Round

```text
rounds/RND0001/
├─ round_request.md
├─ round_manifest.json
├─ round_summary.json
├─ round_summary.md
├─ evidence_set_manifest.json
├─ triage_updates.json
└─ next_round_brief.json
```

`round_summary`は作業logではなく、このRoundで何が追加・変更され、何が未解決かを示すcompact handoffである。`next_round_brief`は別Claude Code sessionでも利用できる機械可読な入口とする。

## 9. State summaryと再構築

`state.json`は正本control plane、`state_summary.json`と各indexはmaterialized viewである。indexはStateとimmutable artifactから再構築できなければならない。Orchestratorは通常raw Stateや全Evidenceを全文読込しない。

## 10. Hashと上書き

artifactのhash不一致は成功扱いにしない。同じNodeのretryは予約済みoutput directoryとID reservationを再利用し、別entityとして二重登録しない。completed Round、Finding、Hypothesis、Question、RelationのIDを再利用しない。
