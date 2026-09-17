# CONDUCTOR 0.2.1 段階6停止報告

> **履歴文書。** 2026-09-17 に段階7以降への明示承認を受けたため、現在の実装状況は [`CONDUCTOR_0.2.1_stage11_implementation_report.md`](CONDUCTOR_0.2.1_stage11_implementation_report.md) を参照する。本書の「段階7へ進まない」は停止時点の記録として残す。

実施日: 2026-09-17  
branch: `0.2.1`  
実装開始時 HEAD: `0af835c10f901c00450621d36c44a706345ed09d`

## 判定

**段階1〜6の実装と合成回帰は完了した。段階7へは進まない。**

正式な較正合否は未判定である。仕様が基準とする較正データは961化合物だが、repository内で利用可能な `chemble_jak2_download_01.csv` は231化合物であり、同一データではない。また、正式報告に必要な18 Description実成果物に基づくcontext catalogも提供されていない。このため、231件で基準を超えた結果を961件較正の代用にはしない。

## 実装済み範囲

| 段階 | 状態 | 主な検証 |
|---|---|---|
| 1 契約 | 完了 | 0.2.1 schemas、catalog、Endpoint、ID、manifest |
| 2 Description統合 | 完了 | 現存18 Skillのcold/warm cache、同一ID異構造拒否、距離artifact |
| 3 統計基盤 | 完了 | block permutation、+1/+1 p、family別BH、block bootstrap |
| 4 Fragment engine | 完了 | TERM/LINK/RING、N≤4、個別constant制約、mapping、immutable SQLite、Similar core |
| 5 Context builder | 完了 | average-linkage、下側quantile、4 scaffold種、連結成分dedup、3-fold翻訳 |
| 6 L2b | 完了 | 系列内再配置、100/1000 staged test、問い別・TERM/RING別BH、Finding、enrichment |

段階7以降のレンズは未実装である。catalogの `checkpoint` も `stage6_l2b` としている。

## 231件 JAK2 sanity check

入力:

- path: `chemble_jak2_download_01.csv`
- SHA-256: `b87bd10fffaf51dcaf4449021770d07452aa4c979f48329a0f6aaaf6179af1ad`
- compounds: 231、valid structures: 231
- Endpoint: `pIC50`、変換なし、higher-is-better
- seed: 20260916
- Similar-core workers: 12
- L2b: screen B=100、final B=1000、enrichment B=20

結果:

| 指標 | 値 |
|---|---:|
| accepted fragmentations | 4,548 |
| exclusions | 10,342 |
| TERM pairs | 4,054 |
| LINK pairs | 725 |
| RING pairs | 0 |
| transformations | 3,793 |
| fragment-observation series | 389 |
| L2b eligible series | 199 |
| L2b fragments | 137 |
| tests | 223 |
| final B=1000 candidates | 20 |
| candidate Findings | 3 |
| permutation participation | 1.00 |

一貫効果のseries-internal nullに対する enrichment:

| absolute t threshold | observed | null mean | enrichment |
|---:|---:|---:|---:|
| 2.0 | 32 | 10.55 | 3.03 |
| 3.0 | 20 | 4.35 | 4.60 |
| 4.0 | 13 | 2.45 | 5.31 |

このデータでは全finite thresholdで `>1.5` だが、RING seriesが0であり、961件較正の代用にはならない。

Similar-core緩和の監査値:

| class | mappings |
|---|---:|
| exact | 1 |
| radius2 | 10,548 |
| radius1 | 891 |
| mcs_mapped attempted | 3,628 |
| mcs unique | 678 |
| mcs failed | 2,950 |

単一processではFMCSが実用時間を超えたため、候補をdeterministic shardへ分けるprocess並列を追加した。12 workerで同じ候補集合を約100秒で完走し、worker数1/2でtable内容が一致することを回帰テストしている。

## 基準値との差分を現時点で帰属できる要因

- 入力が961件の較正データではなく231件JAK2である。
- 231件では共通constantを持つRING比較が成立せず、RING pairが0だった。
- 本実装は診断版と異なり、各constant fragmentへ個別にheavy-atom制約を適用する。
- attachment mappingが一意または対称等価でないpairを除外する。
- 同一series・同一fragmentの複数compoundを1つのEndpoint平均へ集約し、series平均はfragment observationを等重みで計算する。
- 診断版のscreeningだけでなく、productionのseries-internal経験p値とBHを実行している。

## 検証状態

- `pytest`: **51 passed**
- package layout verifier: **succeeded**（Description 18、pipeline 5）
- 新規Skill validator: `cs-stat-core` / `cs-runtime` / `cs-fragment-engine` / `cs-context-builder` / `cs-lens-l2` すべて成功
- Pixi lock: linux-64 / win-64を全対象Skillに作成
- Pixi `--locked` smoke: `cs-lens-l2` 成功
- `git diff --check`: whitespace errorなし

## 正式な段階6判定に必要な入力

1. 961件較正CSVまたは、そのPhase 1 `compounds.csv` / `endpoints.csv`
2. 18 Descriptionを統合した `feature_spaces.json` と距離artifact
3. 段階5から生成した `context_catalog.csv`

入力受領後は `CONDUCTOR_modules/tools/run_stage6_calibration.py` で構造・L2b側を再現し、`series_count`、class別pair数、context数、参加率、候補数、enrichment、診断値との差分を確定する。正式判定と明示承認が得られるまで段階7へ進まない。
