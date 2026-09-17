# GDP.pdf Benchmark Statistical Analysis Report

Last updated: 2026-09-15

Scope: Surge AI's `surgeai/GDP.pdf` release and the independent evaluation implementation by Artificial Analysis (AA)

## Executive Summary

GDP.pdf is a document question-answering benchmark built around real-world professional PDFs. The public release contains 100 tasks paired with 100 unique PDFs, spanning 10 professional domains, 4,592 document pages, and 1,275 atomic rubric criteria. It provides only a test split, with no training or validation split, and its Hugging Face page is tagged `not-for-training`. It should therefore be used to define capabilities, inform data-schema design, and support independent evaluation—not as direct SFT training data.

The main findings of this analysis are:

- The benchmark contains 100 tasks and 100 unique PDFs totaling approximately 467.44 MB.
- Each PDF has an average of 45.92 pages and a median of 26.5 pages, with a range of 1–200 pages.
- Each task has an average of 12.75 rubric criteria and a median of 11, with a range of 3–30.
- The domain distribution in the public data is not perfectly balanced: STEM/Research is the largest domain with 15 tasks, while Legal is the smallest with 7.
- In a mutually exclusive audit based on the primary evidence required to complete each task, 26 tasks primarily depend on images or spatial relationships, 57 primarily depend on tables, forms, or other structured layouts, and 17 primarily depend on continuous prose.
- For a text-only model, 74/100 is a highly optimistic information-availability ceiling. After accounting for parser damage to tables and scanned pages, the relatively robust text-answerable range is estimated at approximately 57–62 tasks.
- AA runs each task independently five times, producing 500 task-attempts. Its headline All-pass metric is the proportion of attempts in which every rubric criterion passes, rather than an ordinary partial-credit score.

## 1. Benchmark Objective and Construction

GDP.pdf does not evaluate isolated OCR or short-form question answering. It evaluates whether a model can locate decisive evidence in raw, long, and layout-complex professional PDFs and use that evidence to complete realistic work tasks. The tasks cover financial materials, clinical guidelines, contracts and insurance policies, engineering specifications, architectural plans, manufacturing instructions, real-estate reports, and HR benefits documents.

Each task described in the official paper can be summarized as:

```text
PDF + natural-language prompt + atomic rubric + domain label + capability labels
```

Tasks were written by practitioners in the relevant domains based on realistic workflows. A candidate task was retained only when at least two frontier multimodal models made substantive errors; wording differences alone did not count as failures. This filtering process makes GDP.pdf intentionally difficult and adversarial. Its distribution should not be treated as the natural difficulty distribution appropriate for everyday SFT data. [GDP.pdf paper](https://arxiv.org/html/2607.11192v3)

The public Hugging Face release contains only a `test` split with 100 rows and carries a `not-for-training` tag. [GDP.pdf dataset page](https://huggingface.co/datasets/surgeai/GDP.pdf)

## 2. Dataset Scale

### 2.1 Overall Scale

| Metric | Value |
|---|---:|
| Number of tasks | 100 |
| Number of unique PDFs | 100 |
| Dataset split | Test only |
| Total PDF pages | 4,592 |
| Total PDF size | 467.44 MB (decimal) / 445.79 MiB |
| Mean pages per PDF | 45.92 |
| Median pages per PDF | 26.5 |
| PDF page-count range | 1–200 |
| Total rubric criteria | 1,275 |
| Mean criteria per task | 12.75 |
| Median criteria per task | 11 |
| Criterion-count range per task | 3–30 |

### 2.2 Prompt Length

Using whitespace-delimited English words as an approximate counting method:

| Metric | Word count |
|---|---:|
| Mean | 118.22 |
| Median | 69 |
| Minimum | 12 |
| Maximum | 1,302 |

Prompt lengths vary substantially. Some tasks are short queries, while others include extensive business context, filtering conditions, output-format requirements, and exception rules. Task difficulty therefore comes not only from PDF length, but also from the number of user constraints that must be satisfied simultaneously.

## 3. Domain Distribution

The `domain` field across the 100 public rows is distributed as follows:

| Domain | Tasks | Share |
|---|---:|---:|
| STEM/Research | 15 | 15% |
| Healthcare | 11 | 11% |
| Construction | 10 | 10% |
| Engineering | 10 | 10% |
| Manufacturing/Supply Chains | 10 | 10% |
| Real Estate | 10 | 10% |
| Finance/Investing | 9 | 9% |
| HR | 9 | 9% |
| Insurance | 9 | 9% |
| Legal | 7 | 7% |
| Total | 100 | 100% |

The official paper characterizes the benchmark as covering 10 balanced domains, but the current public parquet contains between 7 and 15 tasks per domain. Reproduction work and internal comparison sets should therefore use counts calculated from the released fields rather than assume exact balance.

## 4. Rubric Structure and Metadata

Each task contains multiple atomic criteria. AA's judge makes a binary Pass/Fail decision for every criterion, with no partial credit within a criterion. The public data also provides criterion metadata for type, severity, implicitness, subjectiveness, and failure mode.

### 4.1 Criterion Type

| Type | Count | Share | Meaning |
|---|---:|---:|---|
| Primary Intent | 1,050 | 82.35% | A requirement the answer must include or complete correctly |
| Dodged Bullet | 225 | 17.65% | An error, misleading conclusion, or unsupported claim the answer must avoid |

`Dodged Bullet` is an important feature of GDP.pdf's design. The rubric rewards not only what an answer says correctly, but also checks whether it introduces an incorrect entity, page number, causal relationship, or unsupported conclusion when the evidence is insufficient.

### 4.2 Failure Mode

| Failure mode | Count | Share |
|---|---:|---:|
| Binary | 1,029 | 80.71% |
| Scalar | 246 | 19.29% |

Here, `Binary/Scalar` describes the semantic failure mode of a criterion. It does not change AA's final binary judgment for each criterion. Even when an error can vary by degree, the judge still outputs either Pass or Fail for that criterion.

### 4.3 Implicitness

| Implicitness | Count | Share |
|---|---:|---:|
| Explicit | 795 | 62.35% |
| Implicit | 276 | 21.65% |
| Unlabeled | 204 | 16.00% |

Explicit criteria usually correspond directly to requirements stated in the prompt. Implicit criteria may reflect the completeness, qualifications, or correct inferences expected from a professional answer. Unlabeled criteria should be interpreted together with criterion type rather than automatically removed as missing labels.

### 4.4 Severity

| Severity | Count | Share |
|---|---:|---:|
| Certain dealbreaker | 1,101 | 86.35% |
| Possible dealbreaker | 139 | 10.90% |
| Unlikely dealbreaker | 34 | 2.67% |
| Unlabeled | 1 | 0.08% |

Most criteria are marked as definite dealbreakers. This is consistent with the strictness of All-pass: even a seemingly minor omission may cause the entire task-attempt to fail.

### 4.5 Subjectiveness

| Subjectiveness | Count | Share |
|---|---:|---:|
| Objective | 1,177 | 92.31% |
| Subjective | 98 | 7.69% |

Most criteria concern objectively verifiable facts, values, entities, conditions, or exclusions. This atomic, predominantly objective structure is a useful reference for internal SFT-data acceptance checks and automated evaluation schemas.

## 5. Audit of Document Content Types

### 5.1 Classification Principles

The public data does not contain a ready-to-use, mutually exclusive field for “image/table/prose.” The official capability labels also allow a task to carry multiple labels. This report therefore combines manual review with parser inspection and classifies each task according to the primary evidence required for completion. The following priority order prevents double-counting:

```text
visual/spatial evidence required > layout-sensitive structured content > continuous prose
```

“Structured” describes how information is organized in the source PDF—for example, tables, forms, multi-column accounts, schedules, and checklists. It does not mean that parser output is necessarily unstable. Parser stability is a separate dimension.

### 5.2 Mutually Exclusive Primary Classification

| Primary evidence type | Tasks | Share | Implication for a text-only model |
|---|---:|---:|---|
| Images or spatial relationships required | 26 | 26% | Parsed text usually omits irreplaceable evidence |
| Structured, layout-sensitive text | 57 | 57% | Content can be represented as text, but structural damage is possible |
| Primarily continuous prose | 17 | 17% | Usually suitable for normal text-only processing |
| Total | 100 | 100% | — |

#### Images or Spatial Relationships Required: 26 Tasks

```text
2, 3, 5, 8, 13, 21, 24, 31, 33, 35,
38, 42, 43, 44, 46, 47, 48, 52, 59, 60,
70, 71, 73, 74, 78, 81
```

These tasks include maps, floor plans, engineering drawings, photographs, plotted curves, arrow-to-object relationships, and complex handwritten forms whose field associations cannot be recovered reliably through OCR. The decisive question is not whether a PDF contains images, but whether the answer depends on pixel-level content or two-dimensional spatial relationships.

Example 1—Task 35 (Engineering, centered features in a drawing): The prompt asks for every `centered feature` in an engineering drawing. The rubric's complete set is `p1175`, `P1022`, `a1085`, and `p1117`, and the answer must contain only those four items. This is not a simple search for four identifiers in OCR output. The model must interpret centerlines or drafting annotations such as `CTR'D`, determine which hole or feature each annotation points to, and exclude the drawing number, scale, revision information, and other title-block metadata. The PDF has no native text layer. Even if OCR recognizes the four identifiers and `CTR'D`, the two-dimensional associations among lines, arrows, and identifiers are generally absent from linear text. The task therefore requires visual/spatial evidence; a text-only model cannot reliably reconstruct the answer from OCR characters alone.

Example 2—Task 59 (Finance/Investing, Airbnb stock-performance graph): The prompt asks for comparisons among the cumulative returns of Airbnb, the S&P 500, and NASDAQ at the end of March 2021 and at the next three 12-month marks, as well as cost-related information. The rubric requires reading a hypothetical $100 investment graph to obtain approximate initial values of 130 for Airbnb and 110 for each index. It also requires determining that Airbnb led in March 2021, while both indices led Airbnb in March 2022, 2023, and 2024. A parser may extract axis labels, legend entries, and series names, but the vertical positions of the three curves at the target dates are graphical relationships that are not restated point-by-point in the prose. The second part—cost of revenue at 16%, down 1,000 bps, and general and administrative expense at 11%, down 900 bps—can be recovered from text. However, under a task-level classification based on the highest evidence requirement, the graph component makes the entire task visual. This example also shows that a mutually exclusive task-level label does not imply that every sub-question in that task requires image understanding.

#### Structured, Layout-Sensitive Text: 57 Tasks

```text
1, 4, 6, 7, 9, 10, 11, 12, 15, 16,
17, 18, 19, 20, 22, 25, 26, 27, 28, 29,
30, 32, 34, 36, 37, 39, 40, 41, 45, 49,
53, 54, 56, 57, 61, 62, 63, 66, 67, 68,
69, 72, 75, 79, 80, 85, 86, 87, 88, 90,
91, 92, 93, 94, 95, 96, 99
```

These tasks primarily involve tables, but also include forms, financial statements, rate schedules, timetables, checklists, and multi-column reports. Most of the content can be converted into text, but parsing may introduce row-column misalignment, lost merged headers, incorrect footnote attachment, disrupted multi-column reading order, or broken field-name-to-value relationships.

Example 1—Task 6 (STEM/Research, supersonic-flow table): The prompt asks for the total pressure ratios corresponding to Mach 2.02 and 2.03 in `Table II - Supersonic Flow`: `0.7115` and `0.7069`, respectively. It then asks for their percentage difference, approximately `0.65%`, and for the three variables that the prose following equation (86) says remain constant across a normal shock: total enthalpy, total temperature, and total speed of sound. The values and their meanings can all be expressed as characters; interpreting a photograph or curve is not inherently necessary. The task is therefore classified as structured text. However, the source PDF is scanned and has no native text layer. OCR extracts many numbers, but it may separate the Mach column from the total-pressure-ratio column. If a parser preserves the table title, headers, rows, and column relationships, a text-only model can answer. If the parser emits an unstructured stream of numbers, the model cannot determine which row owns `0.7115` even when every character has been recognized correctly. This illustrates the distinction between “content that can be represented as text” and “stable parser output.”

Example 2—Task 80 (Insurance, calculation across multiple rate tables): The prompt provides base loss costs of $2,000 for property and $500 for earthquake coverage, then asks the model to apply building-feature, persistency, and 6.5% expense-reduction credits. The model must bind relationships found across separate tables and instructions: the property and earthquake Loss Cost Multipliers are `1.100` and `2.000`; the building-feature and persistency credits are `10%` and `5%`; a `6.5%` Expense Reduction maps to a Credit Factor of `0.909`; and neither credit applies to the earthquake premium. The correct calculation is: property `2000×1.100=2200`; after the combined 15% credit, `1870`; after multiplying by `0.909`, `1699.83`. Earthquake coverage is `500×2.000=1000`, producing a total of `$2699.83`. The LiteParse text used by AA recovers these critical lines, so a text-only model can in principle complete the task. The risk is that damage to the three horizontal header groups, the percentage-to-factor mapping, or the “does not apply to Earthquake” footnote will cause the model to use the wrong factor or incorrectly discount the earthquake component.

#### Primarily Continuous Prose: 17 Tasks

```text
0, 14, 23, 50, 51, 55, 58, 64, 65,
76, 77, 82, 83, 84, 89, 97, 98
```

These tasks primarily draw evidence from contract clauses, regulations, paper body text, narrative inspection reports, and operating instructions. They may still require cross-page retrieval, exclusion handling, and multi-step reasoning, but they do not depend on unrecoverable two-dimensional visual relationships.

Example 1—Task 55 (Legal, cross-references between the majority and concurring opinions): The prompt asks for cases cited by both the majority and the concurrence, together with a comparison of the legal propositions supported by those citations. The only correct result is `Kokkonen v. Guardian Life Insurance Co. of America`. Both opinions use it to support the proposition that federal courts have limited jurisdiction, but the majority uses it to explain that an erroneous dismissal cannot create diversity jurisdiction where none existed, while the concurrence uses it to question whether improper joinder allows federal courts to expand their jurisdiction. Completing the task requires retrieving two continuous passages of legal reasoning, normalizing case names, taking their intersection, and comparing the propositions. It does not require table coordinates, arrows, or image content. This is a typical case where text extraction is stable but reasoning remains difficult: the text-only model's main challenges are long-context retrieval, entity alignment, and comparison of legal propositions rather than input modality.

Example 2—Task 76 (HR, employee-handbook leave policies): The prompt asks for an explanation of the leave types available to salaried and hourly employees, who qualifies for each, and the associated eligibility requirements. The answer must consolidate 12 policy categories, including vacation, sick leave, FMLA, VESSA, funeral leave, and jury duty, while preserving many qualifications. For example, full-time salaried employees become eligible for up to five vacation days after six months, while full-time hourly employees become eligible for vacation only after one year. FMLA requires at least 12 months of employment, 1,250 hours worked during the preceding 12 months, and a worksite with at least 50 employees within a 75-mile radius. The Chicago hourly sick-leave rule must not be incorrectly generalized to other employees. Although the evidence is distributed across a 57-page handbook, it primarily appears in paragraphs, lists, and conditional sentences under section headings. A parser does not need to reconstruct an irreplaceable two-dimensional relationship. Given complete prose in the correct order, a text-only model can theoretically answer; the difficulty lies in cross-section consolidation, preservation of qualifications, and avoidance of overgeneralization.

These six examples also clarify that “structured” does not mean the parser has already produced JSON, an HTML table, or a stable Markdown table. It means that the source PDF expresses meaning through rows, columns, fields, groups, or layout. Whether a text-only model can use that information depends separately on `parser_quality`: visual tasks are often `insufficient`, structured tasks can range from `stable` to `fragile`, and continuous prose is generally closer to `stable`, though scanning quality and multi-column reading order can still produce exceptions.

### 5.3 Representative Boundary Cases

- `CTR'D` in an engineering drawing: OCR may recognize the annotation, but not which hole or component its arrow identifies, so this is a visual/spatial task.
- A stock-performance curve: the page's text layer does not contain the curve values at the requested dates, so the graph must be read visually.
- A scanned rate table: if OCR preserves a relationship such as `6.5% → 0.909`, a text-only model may still answer, so this is structured text.
- An inspection report with many photographs: if the required conclusion is stated explicitly in the prose, the task does not necessarily require image understanding.
- A diagram accompanied by a complete textual explanation: even if the prompt mentions a figure, the task may be text-answerable when the figure's relationships are fully restated in prose and recovered by OCR.

## 6. Parser and OCR Risk

AA uses LiteParse 2.5.0 with English OCR enabled. Every model receives the complete page-by-page extracted text. Models whose endpoints support image input also receive rendered page images, while text-only models receive only the text. AA does not skip image-dependent tasks for text-only models. [AA Intelligence Benchmarking Methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)

Running LiteParse 2.5.0's complex-page/OCR routing logic across all documents produced the following results:

| Metric | Value |
|---|---:|
| Total pages | 4,592 |
| Pages routed to OCR | 2,444 |
| Share of pages routed to OCR | 53.22% |
| PDFs with at least one OCR-routed page | 99/100 |
| PDFs with every page routed to OCR | 34/100 |
| PDFs with at least half of their pages routed to OCR | 60/100 |

These figures describe LiteParse's conservative processing decisions. They do not mean that 99% of PDFs require visual understanding or that 53.22% of pages failed to parse. Routing may be triggered by scanned pages, sparse text, embedded images, vector text, or complex layouts; OCR may still recover sufficiently useful text.

A native PDF text-layer check found 12 documents containing fewer than 1,000 non-whitespace characters:

```text
2, 6, 8, 28, 35, 39, 49, 68, 71, 78, 80, 88
```

These documents depend heavily on OCR, but “requires OCR” is not the same as “requires a vision model.” A scanned table may remain usable by a text-only model after OCR. Conversely, even if OCR recognizes every label in an engineering drawing, the task may remain unsolvable because the spatial association between labels and graphical features is lost.

The source content type and parser quality should therefore be labeled separately:

```text
source_evidence_type:
  prose | structured_layout | visual_spatial

parser_quality:
  stable | fragile | insufficient
```

## 7. Artificial Analysis Input and Scoring

### 7.1 Input

AA uses the same 100 tasks for every model:

- LiteParse 2.5.0 parses each PDF with English OCR enabled.
- Every model receives the complete page-by-page text.
- If an endpoint supports image input, rendered page images are attached as well.
- A text-only endpoint receives text only.
- The model answers in a single turn with no browser or tools.

This differs from Surge's original implementation. Surge supplies the raw PDF through each provider's document-input interface and uses a different judge. Absolute scores from AA and Surge are therefore not directly interchangeable. [AA GDP.pdf evaluation page](https://artificialanalysis.ai/evaluations/gdp-pdf)

### 7.2 Five Repeats

Each model attempts every task independently five times:

```text
100 tasks × 5 repeats = 500 task-attempts
```

The five runs are not a vote, best-of-5 selection, or pass@5 calculation. Each is an independent first response, and all 500 attempts are aggregated into mean pass@1.

### 7.3 Criterion Judgment

AA currently uses GPT-5.6 Luna Medium to judge each criterion independently. For each judgment, the judge sees the task prompt, the evaluated model's answer, and one criterion. It does not see the source PDF or the evaluated model's identity. Every criterion receives a binary Pass/Fail result. Errors, missing attempts, and responses terminated because of input limits are scored as zero.

### 7.4 All-pass

Attempt `r` on task `t` receives a value of 1 only if every criterion passes:

```text
AllPass(t,r) = 1  if and only if every criterion for that response passes
             = 0  if at least one criterion fails
```

The overall headline score is:

```text
All-pass = number of fully passing task-attempts / 500
```

For example, a displayed score of 7.4% means that 37 of the 500 independent task-attempts passed every criterion:

```text
37 / 500 = 7.4%
```

This can be interpreted as an expected 7.4 fully completed tasks in a single 100-task run. It does not reveal how many distinct tasks succeeded at least once. The 37 successful attempts could be concentrated among as few as 8 distinct tasks or spread across as many as 37.

### 7.5 Mean Pass / Criterion Pass Rate

For each response, AA first calculates the fraction of that task's criteria that passed, then averages this value with equal weight across all 100 tasks and five repeats:

```text
Mean Pass = average(passed criteria / all criteria in that task-attempt)
```

For example, if a task has 11 criteria and the response passes 10:

```text
Criterion Pass Rate = 10/11 = 90.9%
All-pass = 0
```

Mean Pass measures partial capability, while All-pass measures complete execution of the professional task. Because each task is weighted equally, tasks with more criteria do not dominate overall Mean Pass merely because they contain more rubric items.

## 8. Answerable Range for Text-Only Models

The audit in Section 5 supports two estimates of the ceiling for a text-only model.

### 8.1 Optimistic Information Ceiling: 74%

Assume that:

- all 17 prose tasks are fully usable;
- all 57 structured tasks are perfectly recovered by the parser;
- the model perfectly handles long context, retrieval, calculation, and every rubric criterion; and
- none of the 26 visual tasks is solved through guessing or memorization.

The number of tasks for which sufficient evidence is theoretically present in the text input is then:

```text
17 + 57 = 74 tasks
```

Across five repeats, the theoretical All-pass information ceiling remains 74%. This is not an expected model score. It is an optimistic ceiling describing whether the necessary information reaches the text input.

### 8.2 Relatively Robust Text-Answerable Range: Approximately 57–62%

Of the 57 structured tasks, an estimated 40–45 retain their row-column or field relationships with reasonable stability; the remaining 12–17 fall into a parser-sensitive region. Adding the 17 prose tasks yields:

```text
17 + (40 to 45) = 57 to 62 tasks
```

Internal reports should therefore present the following metrics together:

| Metric | Meaning |
|---|---|
| GDP.pdf All-100 | Uses the same denominator of 100 tasks as AA and remains suitable for horizontal comparison |
| Text-addressable-74 | Excludes the 26 tasks audited as strongly visual and represents optimistic text coverage |
| Text-stable-57~62 | Further excludes parser-fragile tasks to better isolate the model's text-reasoning capability |

The 57–62 range is an audit estimate, not an official slice. A formally reproducible subset would require saving each task's classification, evidence pages, raw LiteParse output, and manual-review rationale while pinning the parser version.

## 9. Implications for Building Similar SFT Data

The most valuable aspects of GDP.pdf to emulate are its task structure and quality-control methods, not the benchmark content itself:

1. Bind every SFT sample to a clearly identified source document and evidence pages.
2. Decompose each answer into independently verifiable atomic criteria.
3. Record both required `Primary Intent` content and errors that must be avoided as `Dodged Bullet` criteria.
4. Label source content type separately from parser quality, rather than conflating “table” with “OCR failure.”
5. Include abstention and supersession scenarios involving missing evidence, obscured information, amended old clauses, or footnotes that change the main conclusion.
6. Preserve a natural difficulty distribution in training data rather than copy GDP.pdf's adversarial rule that at least two frontier models must fail a candidate task.
7. Place the benchmark and all 100 associated PDFs on a contamination denylist so that they are excluded from question generation, answer generation, retrieval corpora, and training mixtures.

For text-only SFT, collection and synthesis should prioritize `prose`, `structured_layout + stable parser`, and a controlled amount of `structured_layout + fragile parser` data. Tasks that can only be solved by inspecting photographs, maps, engineering drawings, or plotted pixels should be explicitly excluded.

## 10. Limitations and Definition Notes

- The `26/57/17` split is a mutually exclusive audit of the primary evidence required by the 100 public tasks. It is not an official Surge label; official tasks commonly carry multiple capability labels.
- The estimate of 57–62 robustly answerable tasks is an engineering estimate based on spot checks of parser output, not a strict mathematical ceiling.
- OCR-routing statistics describe only LiteParse 2.5.0's processing logic and do not directly measure OCR accuracy.
- Prompt word counts use simple whitespace tokenization to describe scale and do not correspond to the token count of any model tokenizer.
- The Hugging Face page currently displays an MIT license for the dataset, while the paper describes the public release as Apache 2.0 and explicitly notes that third-party PDFs retain their original rights. Any external PDFs considered for training-data construction must be checked individually for authorization; the license covering benchmark code or metadata must not automatically be extended to PDF content.
- AA continuously updates models, input adapters, and judges. Any citation of leaderboard results should record the date, model configuration, selected page metric, and methodology version.

## References

- [Surge AI: GDP.pdf Dataset](https://huggingface.co/datasets/surgeai/GDP.pdf)
- [GDP.pdf Paper (arXiv HTML)](https://arxiv.org/html/2607.11192v3)
- [Artificial Analysis: GDP.pdf Benchmark](https://artificialanalysis.ai/evaluations/gdp-pdf)
- [Artificial Analysis: Intelligence Benchmarking Methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)
