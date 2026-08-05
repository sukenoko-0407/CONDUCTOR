# CONDUCTOR Description機能ガイド

Descriptionは、化合物を解析可能な数値Vectorへ変換する入口です。同じ化合物でも表現ごとに見える近さや差が変わるため、CONDUCTORは互いに性質の異なるDescriptionを組み合わせます。

![Description機能の概念図](A1_style_set/CONDUCTOR_description_A1_style.png)

## 機能一覧

| ID | Description | 主に表すもの | 特徴 |
|---|---|---|---|
| D001 | RDKit 2D descriptors | 分子量、極性、疎水性など | 解釈しやすい連続物性。初手の基準軸 |
| D002 | Morgan fingerprint | 原子周辺の局所環境 | SARで中心的な円形fingerprint。chiralityも選択可能 |
| D003 | MACCS keys | 定義済み部分構造 | 166個の解釈しやすい構造key |
| D004 | Hashed atom-pair | 原子対と距離 | 離れた原子関係を含むcount表現 |
| D005 | Topological torsion | 連続4原子の結合パターン | 局所的な結合列を捉える |
| D006 | RDKit fragment counts | 官能基・部分構造数 | 人間の化学的説明へ接続しやすい |
| D007 | RDKit path fingerprint | 結合path | 分子グラフ上の経路類似性 |
| D008 | RDKit pattern fingerprint | 部分構造pattern | query的な部分構造の有無 |
| D009 | RDKit layered fingerprint | 複数階層のpath情報 | 原子・結合情報を層別に反映 |
| D010 | Avalon fingerprint | 部分構造・path | RDKit系とは異なるfingerprint設計 |
| D012 | RDKit 3D descriptors | 3D形状・慣性・表面 | conformerから連続3D記述子を生成 |
| D013 | USR / USRCAT | 3D形状と薬理学的原子型 | 高速な3D shape/pharmacophore比較 |
| D014 | Basic 3D shape | 形状、サイズ、扁平性 | 少数の分かりやすい3D指標 |
| D015 | Mordred 2D | 広範な2D数理記述子 | 高次元で網羅的。実験的機能 |
| D016 | Mordred 3D | 広範な3D数理記述子 | 高コスト。実行前に人間確認 |
| D017 | Gobbi Pharm2D | 2D pharmacophore | folded bitまたはSVD低次元表現 |
| D019 | Pretrained embedding | 学習済み潜在表現 | model依存・GPU候補。高コスト |
| D020 | GFN2-xTB descriptors | 電子状態・量子化学的性質 | 非常に高コスト。人間確認が必要 |

D011とD018は、独立Skillを増やさずD002のchirality option、D017のSVD optionへ統合しているため欠番です。

## 代表的な役割

- **物性**: D001、D015
- **局所構造・部分構造**: D002、D003、D006、D008
- **分子グラフ上の距離・経路**: D004、D005、D007、D009、D010
- **3D形状・pharmacophore**: D012、D013、D014、D017
- **学習済み・量子化学表現**: D019、D020

似たfingerprint同士にも違いがあります。複数の表現で同じ傾向が得られた場合、それが同じ情報の反復なのか、異なる観点からの独立した一致なのかをInterpretationで区別します。

## 入出力

- CSV入力と単一・複数SMILES入力に対応します。
- IDのないSMILESには自動IDを付与します。
- invalid SMILESは行を保持し、警告と欠損Vectorを記録します。
- 異なるcompound IDから同一Vectorが生成されても正常です。
- 一般利用では主にDescription CSVを返します。
- CONDUCTOR利用ではmanifest、warning、execution eventも併記します。

## Metricとの関係

| 表現 | 主なMetric |
|---|---|
| binary fingerprint | Tanimoto |
| USR / USRCAT | Manhattan |
| embedding / SVD / 疎なcount | Cosine |
| dense continuous descriptors | 標準化Euclidean |

詳細な直交性と重複関係は[Description間の関係性とカバー範囲](CONDUCTOR_v4_description_relationships_and_coverage.md)を参照してください。
