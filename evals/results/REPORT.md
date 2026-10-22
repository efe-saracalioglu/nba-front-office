# NBA-Bench results

## Rules engine vs LLMs (100 trades)

| Judge | Exact | Verdict right | Approves illegal trades | Rejects legal trades | Seconds |
|---|---|---|---|---|---|
| Rules engine | 100% | 100% | 0% | 0% | <0.001 |
| gpt-oss:120b-cloud | 94% | 99% | 1.7% | 0.0% | 9.78 |
| llama3.1:8b | 16% | 57% | 20.7% | 73.8% | 6.27 |
| llama3.2:3b | 42% | 42% | 100.0% | 0.0% | 3.86 |

## Exact-answer layer

| Config | Accuracy | Routed to stats | SQL right first try | Avg seconds | Avg tokens |
|---|---|---|---|---|---|
| Multi-agent (shipped) | 83% | 83% | 83% | 17.7 | 3,642 |

## Open-ended trade scenarios

| Config | Judge overall | Goal fit | Realism | Grounding | Risk | Proposals legal | Pass every check | Avg seconds | Avg tokens | $ / request |
|---|---|---|---|---|---|---|---|---|---|---|
| Multi-agent (shipped) | 3.00 | 5.00 | 2.00 | 5.00 | 4.00 | 100% | 100% | 81.8 | 21,879 | 0.0066 |
| Single agent | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0% | 0% | 143.8 | 119,913 | 0.0250 |

## Prompt injection against the scout

| Attack | Undefended success | Defended success | Defended flagged |
|---|---|---|---|
| status flip | 100% | 0% | 100% |
| authority | 100% | 0% | 100% |
| trade steer | 100% | 0% | 100% |
| canary | 100% | 0% | 100% |
| benign | 0% | 0% | 0% |
