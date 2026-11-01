# Token Benchmark: baseline_v2

Case:
NVDA / 2026-09-23

Measured runs (valid / target):
5 / 5

Configuration:
- analysts: market, social, news, fundamentals
- research rounds: 1
- risk rounds: 1
- quick model: CS5351/DeepSeek-V4-Flash
- deep model: CS5351/DeepSeek-V4-Flash
- provider: openai_compatible
- cache policy: preserve_existing

## Run totals

| Metric | Mean | Median | Std | Min | Max |
| --- | --- | --- | --- | --- | --- |
| input_tokens | 185,082.0 | 169,923.0 | 34,988.8 | 149,285.0 | 239,600.0 |
| output_tokens | 30,156.0 | 29,590.0 | 1,987.0 | 27,832.0 | 33,223.0 |
| total_tokens | 215,238.0 | 199,421.0 | 36,722.4 | 178,875.0 | 272,823.0 |
| cached_input_tokens | 47,948.8 | 38,528.0 | 25,273.7 | 24,448.0 | 88,960.0 |
| llm_calls | 20.2 | 20.0 | 2.4 | 17.0 | 23.0 |
| tool_calls | 31.4 | 31.0 | 2.1 | 29.0 | 34.0 |
| tool_rounds | 6.4 | 7.0 | 1.9 | 4.0 | 9.0 |
| runtime_ms | 572,041.3 | 541,537.6 | 161,490.7 | 422,603.4 | 843,741.5 |

## Token usage by agent

| Agent | Mean Input | Mean Output | Mean Total | % of Run |
| --- | --- | --- | --- | --- |
| Market Analyst | 41,154.6 | 5,624.6 | 46,779.2 | 21.7% |
| Fundamentals Analyst | 25,778.8 | 5,843.4 | 31,622.2 | 14.7% |
| Neutral Analyst | 19,339.4 | 1,789.8 | 21,129.2 | 9.8% |
| Bear Researcher | 16,493.8 | 2,789.0 | 19,282.8 | 9.0% |
| Conservative Analyst | 16,257.2 | 1,557.6 | 17,814.8 | 8.3% |
| Aggressive Analyst | 13,473.8 | 1,407.2 | 14,881.0 | 6.9% |
| Bull Researcher | 12,710.0 | 1,889.8 | 14,599.8 | 6.8% |
| Research Manager | 10,789.2 | 2,728.8 | 13,518.0 | 6.3% |
| Trader | 10,129.6 | 978.8 | 11,108.4 | 5.2% |
| Portfolio Manager | 9,005.8 | 2,035.0 | 11,040.8 | 5.1% |
| News Analyst | 7,833.8 | 2,184.6 | 10,018.4 | 4.7% |
| Sentiment Analyst | 2,116.0 | 1,327.4 | 3,443.4 | 1.6% |

## Tool behavior

| Agent | Tool Calls | Tool Rounds | Tool Result Bytes |
| --- | --- | --- | --- |
| Market Analyst | 13.0 | 2.6 | 37,557.6 |
| Fundamentals Analyst | 7.2 | 2.0 | 31,628.2 |
| Neutral Analyst | 0.0 | 0.0 | 0.0 |
| Bear Researcher | 0.0 | 0.0 | 0.0 |
| Conservative Analyst | 0.0 | 0.0 | 0.0 |
| Aggressive Analyst | 0.0 | 0.0 | 0.0 |
| Bull Researcher | 0.0 | 0.0 | 0.0 |
| Research Manager | 0.0 | 0.0 | 0.0 |
| Trader | 0.0 | 0.0 | 0.0 |
| Portfolio Manager | 0.0 | 0.0 | 0.0 |
| News Analyst | 11.2 | 1.8 | 3,552.0 |
| Sentiment Analyst | 0.0 | 0.0 | 0.0 |

## Quality / Coverage

Usage complete:
5/5

Attribution complete:
5/5

Telemetry complete:
5/5

## Individual runs

| Run | Input | Output | Total | LLM | Tools | Rounds | Runtime | Status | Valid |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 169034 | 27832 | 196866 | 19 | 30 | 5 | 422,603.4 | completed | yes |
| 02 | 169923 | 29498 | 199421 | 20 | 33 | 7 | 541,537.6 | completed | yes |
| 03 | 239600 | 33223 | 272823 | 23 | 29 | 9 | 843,741.5 | completed | yes |
| 04 | 149285 | 29590 | 178875 | 17 | 31 | 4 | 565,046.9 | completed | yes |
| 05 | 197568 | 30637 | 228205 | 22 | 34 | 7 | 487,277.3 | completed | yes |
