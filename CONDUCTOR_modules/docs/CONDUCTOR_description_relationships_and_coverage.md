# Descriptionの関係性とcoverage

## 全体像

Descriptionは単一の「正しい表現」を競うものではなく、異なる分子概念を直交的または補完的に観察するためのpanelです。同じfamily内には冗長性がありますが、同じ傾向が類似表現だけで現れるのか、異質な表現でも再現するのかを比較するために残します。

| 領域 | Capability | 主に表すもの | 関係性 |
|---|---|---|---|
| 解釈可能2D物性 | D001 RDKit 2D、D015 Mordred 2D | サイズ、極性、疎水性、graph index | D015が広く、D001が軽量で解釈しやすい。重複あり |
| 部分構造count | D006 RDKit fragments | 官能基・警告的部分構造 | D001/D015と一部相関するが直接解釈しやすい |
| binary fingerprint | D002 Morgan、D003 MACCS、D007 path、D008 pattern、D009 layered、D010 Avalon | 局所環境または部分構造presence | 相互に類似するが、探索半径・hash・pattern定義が異なる |
| count fingerprint | D004 atom pair、D005 torsion | 原子対距離・結合系列 | binary fingerprintより頻度と長距離配置を残す |
| pharmacophore | D011 Gobbi Pharm2D | feature typeと2D距離配置 | 構造fingerprintと異なる機能的類似性 |
| 軽量3D | D012 RDKit 3D、D014 shape | 慣性・球状性・形状 | 大きく重複。D012がやや広い |
| 3D shape distribution | D013 USR/USRCAT | 形状およびpharmacophore別空間分布 | D012/D014を補完し、Manhattan距離を用いる |
| 広域3D | D016 Mordred 3D | 多数の3D descriptor | D012-14を包含する部分があるが高次元で広い |
| 量子化学 | D019 GFN2-xTB | energy、frontier orbital、charge、dipole、bond order | 2D/3D幾何だけでは直接得にくい電子状態 |
| pretrained embedding | D020 ChemBERTa | SMILES文脈の学習済み表現 | 解釈性は低いが手設計表現と異なる視点 |

## 直交性の見方

- D002/D003/D007-D010は同じ2D fingerprint群で、完全には直交しません。Clusterや近傍の頑健性比較には有用です。
- D012/D014/D016は3D形状descriptorに重複があります。D013は距離分布表現として少し異なります。
- D001/D015/D006は相関し得ますが、「総合物性」「広域descriptor」「特定fragment」という解釈単位が異なります。
- D019とD020はそれぞれ電子構造と学習済みSMILES文脈を持ち、標準panelの異質性を広げます。

## coverageと限界

2D topology、substructure、pharmacophore、3D shape、広域3D、量子化学、pretrained embeddingをcoverします。一方、標準化・tautomer ensemble、明示的溶媒、protein-ligand interaction、MD ensemble、真正MMP、反応性の荷電状態差分は標準Description外です。

3DとxTBは入力SMILESから生成したconformerに依存します。ChemBERTaはlocal weightだけをCPUで使い、外部downloadを行いません。下流metricはCapability名ではなく各Description manifestの`value_semantics`と`natural_metric`に従います。
