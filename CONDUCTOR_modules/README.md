# CONDUCTOR 0.2.1

CONDUCTORは、低分子創薬データから条件依存SAR、MMP変換、fragment効果、局所SAR、未探索候補、
系列間移植性を探索し、統計・反証・引用検証を伴うFindingとして出力する解析システムです。

数値計算、p/q値、score、状態判定は決定論的コードが担当します。Local LLMは、許可済みdeep-dive
templateの選択と、検証済みEvidenceに基づく引用付き文章化だけを担当します。LLMがTool、OS command、
統計計算を直接実行する構成ではありません。

## 現在の状態

- Version: `0.2.1`
- 本番受入: 完了
- 実行方式: Ubuntu CPUマシン上の固定DAG／single-writer Runtime
- LLM: 承認済み内部vLLM OpenAI互換APIへprovider経由で接続
- レポート: 全体HTMLと上位20件のLens別個別HTMLをP06で標準生成

正式受入の記録は
[`docs/CONDUCTOR_0.2.1_R1_production_acceptance_report.md`](docs/CONDUCTOR_0.2.1_R1_production_acceptance_report.md)
を参照してください。

## 配置

```text
project-root/
├── .claude/
│   └── skills/                 # Runtimeから起動するversioned Skill
└── CONDUCTOR_modules/
    ├── catalog/                # Skill catalog
    ├── config/                 # defaultsとresolved config例
    ├── docs/                   # 正本仕様、運用、設計、受入記録
    ├── local_llm_provider/     # JSONL providerと内部prompt
    ├── pipeline/               # 固定production DAG
    ├── schemas/                # JSON Schemaと例
    ├── tests/                  # contract/unit/integration
    └── tools/                  # Run、DB、診断、HTML export支援
```

解析中は`.claude/`と`CONDUCTOR_modules/`をread-onlyとして扱います。Runtime state、Execution Request、
artifact、Finding、report、auditはRun rootへ書き出します。Description Databaseは
`<PROJECT_ROOT>/data/description_database/<PROGRAM_NAME>/`にProgram単位で保持します。

## 最初に読む文書

1. [利用者ガイド](docs/CONDUCTOR_0.2.1_user_guide.md)
2. [仕様概要書](docs/CONDUCTOR_0.2.1_specification_overview.md)
3. [運用プロンプト集](docs/prompt/CONDUCTOR_0.2.1_prompts.md)
4. [HTMLレポートガイド](docs/CONDUCTOR_0.2.1_reporting_guide.md)
5. [文書案内](docs/README.md)

## Runの基本原則

- 1 Run = 1 Endpoint。
- 同じProgram、compound ID、canonical SMILES、calculation version/signatureが一致するDescriptionだけを再利用。
- 同一Program内の同一compound ID・異構造はfail-fast。
- 既存Run rootは上書きしない。
- 3D conformer生成不能は理由付きterminal SKIPとして記録し、解析可能な母集団で下流を継続。
- threshold、Finding、引用、成果物をRun中に自動修正しない。
- Phase 5/6では設定済みproviderだけを使い、fallback文章を生成しない。

## 標準出力

P06成功時には、監査正本のJSON/JSONLに加えて次を生成します。

- `report.html`: 上位1～10位を図と説明付きで詳述し、11～20位はタイトルとlinkを掲載。
- `finding_reports/<finding_id>.html`: 上位20件すべての個別レポート。
- Lens固有のinline SVG: 2D構造、MMP、散布図、近傍、系列対応など。
- `artifact_manifest.json`: 全成果物、入力hash、metrics、versionを登録。

HTMLは表示層です。Finding、Evidence、test、artifact manifestが監査正本です。

## 開発・配布

実行環境は各Skillの`env/pixi.toml`と`pixi.lock`で固定します。`.pixi/`、`.venv/`、`__pycache__/`、
pytest/ruff cacheはローカル生成物であり、配布物へ含めません。コード変更後は`.claude/skills/`と
`CONDUCTOR_modules/`を同じcommitから本番解析directoryへ反映してください。
