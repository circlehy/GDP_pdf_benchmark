# Pipeline report: golden_v0_single_pdf_battery

- Documents: **1**
- Available source documents: **3**
- Generated: **6** — `{'structured_layout': 3, 'visual_spatial': 2, 'text_reasoning': 1}`
- Static accepted/rejected: **2 / 4**
- Candidates after deduplication: **2**
- Verifier statuses: `{'passed': 2}`
- Applied bbox repairs: **2**
- Applied rubric overrides: **0**
- Human review statuses: `{'approved': 2}`
- Final statuses: `{'passed': 2}`
- Difficulty assessed/admitted: **2 / 2**
- Difficulty labels: `{'hard': 2}`
- Exact document-text accounting: **True**
- Exact image-token accounting: **False**
- Release ready: **False**

## Static rejection reasons

- `gdp_like_structural_gate`: 2
- `rubric_covers_all_gold_claims`: 4

## Final blockers

- None

## Context accounting

| Document | Pages | Text tokens | Image tokens* | Input tokens* | Utilization |
|---|---:|---:|---:|---:|---:|
| sha256:8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57 | 88 | 41,596 | 221,430 | 269,170 | 51.3% |

### Generated task sequence estimates

| Sample | Pages | Text content tokens | Image tokens* | Sequence tokens* | Utilization |
|---|---:|---:|---:|---:|---:|
| pdfsft_9feb1b4ef1bede13f8bb | 88 | 42,126 | 221,430 | 263,556 | 50.3% |
| pdfsft_70d759e909584a64d0ae | 88 | 42,202 | 221,430 | 263,632 | 50.3% |
| pdfsft_564c57e375b09d6e7880 | 88 | 42,218 | 221,430 | 263,648 | 50.3% |
| pdfsft_1ef2a218c4a76a94f3cc | 88 | 42,177 | 221,430 | 263,607 | 50.3% |
| pdfsft_e90ab36ad602d9f120aa | 88 | 42,107 | 221,430 | 263,537 | 50.3% |
| pdfsft_7a7f3a06f4ad7b3ef271 | 88 | 42,120 | 221,430 | 263,550 | 50.3% |

\* Text counts use the configured target tokenizer when marked exact. Image and total counts remain estimates until the target vision processor and final chat template are frozen.

## Interpretation

`release_ready=false` is expected while human review, judged difficulty, or exact target token accounting is incomplete. The pipeline must report zero release-ready records rather than silently weakening those gates.

Machine-readable report: [pipeline_report.json](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/golden_v0_single_pdf_battery/pipeline_report.json)
