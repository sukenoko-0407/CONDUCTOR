# Interpretation Guidelines

## Observation, interpretation, hypothesis

- Observation is a value, distribution, ranking, pair, exception, warning, or statistical result produced by an Operator.
- Interpretation states what an observation may mean within its applicability conditions.
- A hypothesis integrates interpretations into a falsifiable explanation or design direction.

Do not rewrite an Operator result as though it were a mechanistic conclusion.

## Evidence independence

Evidence is not independent merely because different Operators produced it. SALI, activity-cliff detection, and kNN consistency based on the same Morgan fingerprint and the same local pairs may be strongly dependent. Record shared representation, compounds, pairs, endpoint, assay, and preprocessing.

Stronger support generally comes from different information sources, such as an interpretable descriptor association, an MMP transformation, an orthogonal shape representation, and an interaction fingerprint agreeing within the same scope.

## Contradiction and alternatives

For every hypothesis, search for:

- evidence with the opposite direction;
- compounds and groups outside the proposed scope;
- exceptions inside the proposed scope;
- assay-condition differences and measurement uncertainty;
- group overlap or selection effects;
- missing descriptions and failed calculations;
- a simpler alternative explanation.

An absence of contradicting evidence is not proof when relevant Operators were not run.

## Confidence

Use confidence labels as calibrated summaries. Explain sample size, effect magnitude, uncertainty, evidence independence, exceptions, warnings, and untested alternatives. Never convert correlation or enrichment alone into a causal claim.

## Actionability

Recommend next analysis only when it distinguishes explicit alternatives or tests scope. For structural implications, describe transformations, positions, interaction goals, or property directions. Do not generate concrete new SMILES in v4 initial scope.

## Human report

Lead with notable findings, then observation, supporting evidence, contradicting evidence, scope, confidence, next analysis, structural implication, and human review points. Keep evidence IDs visible.
