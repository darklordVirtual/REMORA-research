# REMORA Statistical Tests

Source: results/ablation_v2_results.json

| Comparison | n | Acc A | Acc B | Delta (B-A) | 95% CI | McNemar p |
|---|---:|---:|---:|---:|---|---:|
| B_majority vs D2_balanced | 302 | 0.8278 | 0.8212 | -0.0066 | [-0.0166, 0.0000] | 0.500000 |
| C_remora vs D2_balanced | 302 | 0.6954 | 0.8212 | 0.1258 | [0.0861, 0.1689] | 0.000000 |
| C_remora vs D3_hybrid | 302 | 0.6954 | 0.7616 | 0.0662 | [0.0397, 0.0960] | 0.000002 |

McNemar uses exact binomial on discordant pairs.
