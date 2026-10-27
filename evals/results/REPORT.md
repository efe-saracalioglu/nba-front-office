# NBA-Bench results

## Rules engine vs LLMs (100 trades)

| Judge | Exact | Verdict right | Approves illegal trades | Rejects legal trades | Seconds |
|---|---|---|---|---|---|
| Rules engine | 100% | 100% | 0% | 0% | <0.001 |
| gpt-oss:120b-cloud | 94% | 99% | 1.7% | 0.0% | 9.78 |
| llama3.1:8b | 16% | 57% | 20.7% | 73.8% | 6.27 |
| llama3.2:3b | 42% | 42% | 100.0% | 0.0% | 3.86 |

## Exact-answer layer

Ablation rows (v1 and its variants) share one system version; v2 is the shipped system after the fixes below.

| Config | Accuracy | Routed to stats | SQL right first try | Avg seconds | Avg tokens |
|---|---|---|---|---|---|
| Multi-agent v2 (after fixes) | 99% | 100% | 94% | 11.3 | 4,475 |
| Multi-agent v1 | 86% | 75% | 73% | 10.9 | 3,487 |
| No SQL self-correction | 86% | 76% | 73% | 18.8 | 3,388 |
| All 20B models | 84% | 74% | 69% | 19.4 | 3,588 |
| Single agent | 99% | 0% | 0% | 18.2 | 6,220 |

## Open-ended trade scenarios

Ablation rows (v1 and its variants) share one system version; v2 is the shipped system after the fixes below.

| Config | Judge overall | Goal fit | Realism | Grounding | Risk | Proposals legal | Pass every check | Avg seconds | Avg tokens | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| Multi-agent v2 (after fixes) | 3.25 | 4.46 | 2.79 | 3.96 | 4.29 | 100% | 100% | 67.1 | 17,752 | 0.0052 |
| Multi-agent v1 | 2.79 | 4.00 | 2.54 | 3.67 | 4.08 | 100% | 100% | 60.6 | 16,336 | 0.0047 |
| No devil's advocate | 2.42 | 4.21 | 2.12 | 3.58 | 2.04 | 100% | 96% | 38.1 | 10,850 | 0.0025 |
| All 20B models | 2.54 | 3.17 | 2.96 | 2.58 | 2.75 | 100% | 100% | 119.6 | 17,944 | 0.0022 |
| Single agent | 1.25 | 2.96 | 1.08 | 2.21 | 1.12 | 94% | 6% | 87.5 | 110,211 | 0.0203 |

## Prompt injection against the scout

| Attack | Undefended success | Defended success | Defended flagged |
|---|---|---|---|
| status flip | 100% | 0% | 100% |
| authority | 100% | 0% | 100% |
| trade steer | 100% | 0% | 100% |
| canary | 100% | 0% | 100% |
| benign | 0% | 0% | 0% |

## Judge checked against deterministic checks

All 96 scenario replies, grouped by what the rules engine and constraint checks found.

| Group | n | Goal fit | Realism | Grounding | Risk | Overall |
|---|---|---|---|---|---|---|
| Empty reply or crash | 10 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| No trade proposed | 29 | 3.55 | 3.31 | 2.76 | 3.07 | 2.79 |
| Every proposal passes every check | 40 | 4.58 | 2.25 | 3.90 | 3.15 | 2.80 |
| Some proposal fails a check | 17 | 3.47 | 1.12 | 2.94 | 1.18 | 1.41 |

Empty replies scored 1: 100%. Probability the judge ranks a fully passing reply above one with a failing proposal (AUC): overall 0.837, goal fit 0.715, grounding 0.657.

## System fixes: before vs after

Fixes: factual one-player questions routed to the SQL analyst with their own prompt, a salary ceiling for backup and cheap targets, first-round picks required for the talent a counterparty gives up, and unambiguous payroll and hard-cap lines in the memo fact sheet.

Exact answers: 85.7% -> 98.8% (12 questions fixed, 1 broken; exact McNemar p = 0.0034).

Scenarios, paired over 24 requests, one run each; proposals passing every check 100% -> 100%:

| Judge dimension | Mean change | 95% bootstrap CI | Wilcoxon p | Better / worse |
|---|---|---|---|---|
| overall | +0.46 | [-0.29, +1.21] | 0.307 | 11 / 8 |
| goal fit | +0.46 | [-0.33, +1.25] | 0.283 | 9 / 5 |
| realism | +0.25 | [-0.54, +1.00] | 0.548 | 10 / 8 |
| grounding | +0.29 | [-0.62, +1.21] | 0.734 | 10 / 6 |
| risk awareness | +0.21 | [-0.33, +0.75] | 0.506 | 8 / 5 |

The scenario gains are not distinguishable from run-to-run noise at this sample size; the exact-answer gain is.
