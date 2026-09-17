# Pipeline report: initial_pipeline_v1

- Documents: **3**
- Generated: **3** — `{'visual_spatial': 1, 'structured_layout': 1, 'text_reasoning': 1}`
- Static accepted/rejected: **1 / 2**
- Verifier statuses: `{'passed': 1}`
- Applied bbox repairs: **0**
- Applied rubric overrides: **3**
- Human review statuses: `{'approved': 1}`
- Final statuses: `{'passed': 1}`
- Difficulty assessed/admitted: **1 / 0**
- Difficulty labels: `{'medium': 1}`
- Exact document-text accounting: **True**
- Exact image-token accounting: **False**
- Release ready: **False**

## Static rejection reasons

- `gdp_like_structural_gate`: 1
- `rubric_covers_all_gold_claims`: 1

## Final blockers

- None

## Context accounting

| Document | Pages | Text tokens | Image tokens* | Input tokens* | Utilization |
|---|---:|---:|---:|---:|---:|
| sha256:7111746b33b7a23a1ac4d983b15970525d4c9bd79206f20afb79bd9342f9bc4b | 99 | 49,162 | 249,926 | 305,232 | 58.2% |
| sha256:8ee157a5465ef564105839ef5cedf8c511917057d76adb85e7642d21fa8e8c57 | 88 | 41,596 | 221,430 | 269,170 | 51.3% |
| sha256:9d392eb460a927dff295dda3d11f2a3042eba3b5a85e6b518be6e231fd5f99ef | 23 | 24,994 | 57,518 | 88,656 | 16.9% |

### Generated task sequence estimates

| Sample | Pages | Text content tokens | Image tokens* | Sequence tokens* | Utilization |
|---|---:|---:|---:|---:|---:|
| pdfsft_3e50b91d4dd88bfde776 | 23 | 25,507 | 57,518 | 83,025 | 15.8% |
| pdfsft_305fe103c90f3166301a | 88 | 42,074 | 221,430 | 263,504 | 50.3% |
| pdfsft_fc15b35117c4788afdad | 99 | 49,780 | 249,926 | 299,706 | 57.2% |

\* Text counts use the configured target tokenizer when marked exact. Image and total counts remain estimates until the target vision processor and final chat template are frozen.

## Interpretation

`release_ready=false` is expected while human review, judged difficulty, or exact target token accounting is incomplete. The pipeline must report zero release-ready records rather than silently weakening those gates.

Machine-readable report: [pipeline_report.json](/mnt/weka/home/yuan.huang/GDP_pdf_benchmark/reports/initial_pipeline_v1/pipeline_report.json)
