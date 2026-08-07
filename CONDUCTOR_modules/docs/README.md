# CONDUCTOR documentation

このdirectoryはCONDUCTOR 4.3.0のtarget specificationを収載する。ファイル名の`v4`はmajor系列名として維持する。実装が文書へ追随するまで、以下の「正本文書」を設計判断の基準とする。

## 正本文書

| 文書 | 役割 |
|---|---|
| [設計仕様](CONDUCTOR_v4_design_spec.md) | Run、Round、phase、DAG、State、Skill境界の全体仕様 |
| [Orchestration Policy](CONDUCTOR_v4_policy.md) | Orchestratorの行動原則、phase gate、承認と失敗時の扱い |
| [Interpretation Policy](CONDUCTOR_v4_interpretation_policy.md) | Evidence比較、Finding、Hypothesis、Question、salienceの規則 |
| [出力契約](CONDUCTOR_v4_output_contract.md) | 一般利用／CONDUCTOR利用のartifactと保存場所 |
| [識別子リファレンス](CONDUCTOR_identifier_reference.md) | Capability、Node、Round、Group、Evidence等のID契約 |
| [利用手順](CONDUCTOR_v4_user_guide.md) | 新規Run、後続Round、部分解析、再開方法 |
| [リファクタリング計画](CONDUCTOR_refactoring_plan.md) | 実装順序、変更境界、試験、完了条件 |

## 補助資料

- `CONDUCTOR_explanation/`は人間向け概念説明であり、細かな実装契約の正本ではない。
- HTML、PNG、`CONDUCTOR_internal_overview.pptx`は説明用snapshotであり、target specificationの正本ではない。`CONDUCTOR_explanation/`のHTMLは対応Markdownから再生成済みで、画像をbase64埋込みしている。
- `CONDUCTOR_v4_skill_catalog.md`はCapability一覧であり、Catalog生成物と照合して更新する。
- Description計算、Grouping計算、Operator数値Kernelの科学的仕様は現行Skillを基準とし、今回のcontrol-plane refactorでは原則変更しない。

## 互換性

4.3.0は新規Runを前提とし、旧Stateのimport、migration、互換wrapperを提供しない。旧成果物はread-onlyで保存できるが、新RunのcoverageやStateへ取り込まない。
