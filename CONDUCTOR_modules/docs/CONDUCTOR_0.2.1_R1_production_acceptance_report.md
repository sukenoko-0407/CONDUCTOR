# CONDUCTOR 0.2.1 R1 本番正式受入報告

作成日: 2026-09-21  
状態: **正式受入済み**

## 1. 受入対象

- Run ID: `RUN-71F880902191A1AA99F4`
- Git commit: `458131e`
- Runtime Node: `13/13 succeeded`
- 最終判定: 3.8相当のread-only監査により**受入可能**

この報告は利用者が本番機のruntime、manifest、citation validationおよびreportをread-only監査して
伝達した値を記録する。生データは本書へ複製しない。

## 2. Phase 5/6

### P05 deep dive

| 項目 | 値 |
|---|---:|
| logical calls | 3470 |
| failed logical calls | 213 |
| failure fraction | 0.06138328530259366 |

failure fractionは設定上限0.20以内である。P05はM-31実装前の成功attemptであるため、213件のtask/error
type別内訳は存在しない。内訳取得だけを目的としたP05再実行は行わない。

### P06 report

| 項目 | 値 |
|---|---:|
| component count | 1 |
| logical calls | 1 |
| semantic retry count | 0 |
| failed logical calls | 0 |
| failure fraction | 0.0 |
| null narrative components | 0 |
| citation validation status | succeeded |
| citation validation errors | 0 |

P06限定復旧後の叙述は初回応答で受理され、semantic retryやfail-closed nullを必要としなかった。
strict citation validationは成功している。

## 3. Lens telemetry

`observed_units_per_second`とL5以外のengine/versionはartifactへ記録されていなかった。下表は伝達された
`unit_count`、`estimated_seconds`、`actual_wall_seconds`を正本値として記載する。derived rateは
versioned既定値へ使用しない。

| Lens | engine/version | unit_count | estimated_seconds | actual_wall_seconds | estimate/actual |
|---|---|---:|---:|---:|---:|
| L1b | 未記録 | 123877540 | 51.96 | 1126.58 | 0.046122 |
| L2a | 未記録 | 9985976 | 1.72 | 1247.3 | 0.001379 |
| L2b | 未記録 | 2198196 | 54.0 | 17.06 | 3.165299 |
| L4 | 未記録 | 900 | 1.59 | 719 | 0.002211 |
| L5 | matrix_blas_v1 | 9375294684 | 3210.7 | 24.056 | 133.467742 |
| L7 | 未記録 | 86086 | 17.9 | 4.00 | 4.475000 |

L1b、L2a、L4は実時間を大幅に過小評価し、L5、L2b、L7は過大評価した。ただし全Nodeは設定された
60分以内で完了しており、今回のRunの受入を妨げない。

## 4. 結論と後続作業

CONDUCTOR 0.2.1 R1は、本番入力、実Local LLM provider、Phase 1〜6、strict citation validationを含む
end-to-end Runとして正式受入可能である。

利用者の明示判断により、次回Runを待たず危険側の見積りを是正する。R1.3暫定値としてL1bを
`100000 units/s`、L2aを`8000 units/s`へ変更し、L4には`720秒`の固定オーバーヘッドを加える。
高速化後のL5は実測速度の約1/8に相当する`50000000 units/s`へ変更し、十分な安全余裕を残しつつ
不要なguard停止を抑える。L2b/L7は現状値を維持する。次回以降はP06が各Lensのexact telemetry、
engine、cost model versionと評価をJSON/HTMLへ自動集約し、この暫定値を継続評価する。

受入済みRunや成果物は変更しない。HTML実装前に完了した本Runは、P06 manifestと成果物hashを検証する
read-only export toolからRun root外へ静的HTMLを出力する。
