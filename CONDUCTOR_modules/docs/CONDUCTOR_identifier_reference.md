# CONDUCTOR 識別子リファレンス

## 1. 原則

- Capability IDはRepository内で固定する。
- Nodeと科学entityのIDはRun内で一意とし、Round間で引き継ぐ。
- IDは削除、再利用、再番号付けしない。
- 表示桁は最小幅であり、桁あふれ時は自然に拡張する。
- Compound IDはinput所有者が管理し、CONDUCTORが変更しない。

## 2. ID一覧

| ID | 意味 | Scope | 採番主体 |
|---|---|---|---|
| `D001` | Description Capability | Repository | Catalog管理者 |
| `C001` | Grouping/Clustering Capability | Repository | Catalog管理者 |
| `A001` | Operator Capability | Repository | Catalog管理者 |
| `I001` | Interpretation Capability | Repository | Catalog管理者 |
| `O001` | Orchestration Capability | Repository | Catalog管理者 |
| `ND0001` | Description Node | Run | State Manager |
| `NG0001` | Grouping Node | Run | State Manager |
| `NO0001` | Operator Node | Run | State Manager |
| `NI0001` | Interpretation Node／artifact | Run | State Manager |
| `RND0001` | 解析Round | Run | State Manager |
| `G000001` | Group | Run | State Manager |
| `E000001` | Operator Evidence | Run | State Manager |
| `F0001` | Finding | Run | State Manager |
| `H0001` | Hypothesis | Run | State Manager |
| `Q0001` | Scientific Question | Run | State Manager |
| `REL0001` | Evidence／Finding間Relation | Run | State Manager |
| `REQ0001` | 追加解析要求 | Run | State Manager |
| `SCP0001` | 明示的compound scope | Run | State Manager |
| `SEV0001` | Salience変更event | Run | State Manager |

`R`単独prefixは使用しない。Roundは`RND`、Relationは`REL`とする。Hypothesisは`H`であり、Relationと混同しない。

## 3. CapabilityとNode

Capabilityは手法、Nodeは一回の実行である。例えばCapability `A006` SALIは、Run内でNode `NO0012`、`NO0041`として異なるDescriptionやscopeへ実行される。Capability IDをNode IDとして使わない。

## 4. Round間通番

```text
RND0001: F0001, F0002, H0001, Q0001, REL0001
RND0002: F0003, F0001 revision 2, H0002, Q0002, REL0002
```

同じ観察、主張、問い、関係を再評価する場合は同じIDのrevisionを増やす。対象または主張が実質的に別なら新IDを作り、`derived_from`または`supersedes`で接続する。

## 5. Entity定義

- **Evidence**: Operator数値結果。immutable。
- **Finding**: Evidenceに基づく具体的観察。重要度やstatusは可変。
- **Hypothesis**: 反証可能な説明候補。Findingごとには作らない。
- **Question**: 追加解析で識別したい問い。深掘りしない選択を許容する。
- **Relation**: corroborates、localizes、conditionalizes、contradicts、refines、exception、incomparableなどの意味関係。
- **Request**: Questionや人間指示を実行Nodeへ変換する要求。

## 6. Questionの可変状態

Questionは少なくとも次を持つ。

```json
{
  "question_id": "Q0007",
  "revision": 2,
  "deep_dive_potential": true,
  "agent_priority": "low",
  "human_decision": "skip",
  "status": "open",
  "reopen_recommended": false,
  "origin_round_id": "RND0002",
  "last_updated_round_id": "RND0004"
}
```

`human_decision`は`unreviewed/allow/skip/defer`、科学的状態の`status`は`open/in_progress/answered/closed`を使う。この二軸は独立であり、`skip`はQuestionを科学的に解決済みにする値ではない。`skip`中はOrchestratorが自動深掘りしない。新EvidenceによりAgentは`reopen_recommended=true`を提示できるが、人間decisionを変更しない。

## 7. ID予約

InterpreterはIDを自由採番しない。OrchestratorがState Managerへ必要件数を渡し、lock下でInterpretation Nodeへidempotentな正式ID blockを予約する。機械draftと専用Agentのfinal renderはこの予約だけを使う。同じNodeのretryは同じ予約を使い、未使用IDも再利用しない。後続Roundでは新しい`NI####`と予約blockを作り、既存entityの再解釈は予約内の`revisable_ids`を使って同じIDの`revision`を増やす。

## 8. HTML表示

Interpretation HTMLは各Finding、Hypothesis、Questionについて、ID、初出Round、最終更新Round、revision、status、関連Evidenceを表示する。IDだけを列挙せず、意味を説明する本文を必須とする。
