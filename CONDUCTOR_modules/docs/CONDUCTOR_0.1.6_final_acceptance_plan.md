# CONDUCTOR 0.1.6 最終受入試験計画

## 目的

Unit Testだけでは確認できない、Runtime Workerのprocess所有、実Pixi環境、成果物昇格、DAG更新、Interpretation終端を実データ規模で確認します。科学的な網羅解析を完遂する性能ベンチマークではなく、0.1.6制御系と代表的な科学経路の受入試験です。

## Windows拡大E2E

- 入力: `chemble_jak2_download_01.csv`の全231化合物
- Endpoint: `pIC50`、`higher_is_better=true`
- CPU予算: 8 core
- 本番経路: Human authorization → Main lease → deterministic planning → signed Packet → detached Runtime Worker → Skill固有Pixi → promotion → Interpretation → Full Audit
- Description代表: 連続2D、binary fingerprint、substructure、3D shape、Mordred 3D、ChemBERTa
- Clustering代表: Murcko、MCS、Vector Butina、Vector hierarchical
- Operator: Globalを優先し、property profile、association、projection、feature-space、landscape、Cluster評価、MMPから複数種類を実行する
- Local: 十分な化合物数を持つClusterについて、対応Global comparatorを持つ範囲で確認する
- 終端: Interpretation JSON／Markdown／HTML、Full Audit、`AWAITING_HUMAN_REVIEW`

xTBはこのWindowsのtblite native processが単一化合物でも異常終了することを確認済みのため、Windows E2Eでは人間承認による明示的除外とします。これは成功に偽装せず、受入記録に残します。

## 合格基準

1. Node ID重複、別Round自動開始、二重科学process、無限retryがない。
2. MainまたはTool callが再接続しても同じPacketを二重実行しない。
3. Runtime WorkerがPacket内Nodeをterminalまで所有し、Mainが科学Skillを直接代行しない。
4. 成功Nodeのartifact hash、Result Index、DAG参照が実在し、Run Root外へ出ない。
5. Failed／Cancelled Nodeを成功として扱わず、Round outcomeへ反映する。
6. Cluster-local ResultのInterpretationをGlobalと誤記しない。
7. InterpretationのResult参照が実在し、Markdown／HTMLが人間に読める。
8. Full Auditのerrorが0で、警告または部分完了理由が説明される。
9. 並列SkillがCPU予算を超えず、想定工程で複数process／threadを使用する。

## Linux HPCで残す受入

- 共有Pixi binary `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`
- Skill内cacheだけを使用した初回bootstrapと複数利用者からの再利用
- xTBの完走、化合物worker × 4 core、CPU総予算内での動作
- 6時間までのRuntime Worker／lease／timeout整合
- MCS、Mordred 3D、MMPのLinux process／CPU利用
- 別Claude Code sessionからの同一Run再開

## 記録方法

実行結果、Node数、失敗・除外理由、Interpretation／Audit path、並列観測、所要時間を[CONDUCTOR_verification.md](CONDUCTOR_verification.md)へ追記します。未実施項目はPASSにせず、Windows完了とLinux確認待ちを分離します。

## Windows最終実績

2026-08-22に全231化合物を用いた代表パネルE2Eを完了しました。D016 Mordred 3D、D020 ChemBERTa、C001 Murcko、C002 MCS、Global A009／A011／A013、MCS Cluster-local A009、Interpretation、Full Auditを、署名Packetとdetached Runtime Workerを通して実行しました。

- 科学Node 8件とInterpretation Node 1件が成功し、Full Auditはerror 0、warning 0でした。
- Roundは`AWAITING_HUMAN_REVIEW`、closureは`complete`へ到達しました。
- 受入用に未選択の基本計算66 Nodeと未構築環境を要するAnalysis 2 Nodeは、実行前に公式`node-cancel`で明示的に除外しました。
- 別の診断Runでは、Windows／OneDrive上での一時file置換競合と、複数Skill環境の同時初回構築による容量不足を検出しました。前者はbounded retryで修正し、後者はLinux HPC受入および運用時の事前容量確認事項として残します。
- Interpretation初回commitはGlobal scopeのMurcko ResultをCluster ID主体で記述したため品質ゲートに拒否され、scopeに整合する文面へ直した同一Nodeの次AttemptでPASSしました。誤ったscope表現をRound handoff前に止めることを実証しました。
