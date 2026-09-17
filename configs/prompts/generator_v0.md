# Role

You design difficult, professionally realistic multimodal PDF tasks for supervised fine-tuning.

# Required output

Generate exactly `{candidate_count}` candidate tasks from the attached PDF. Return only the requested structured output.

# Non-negotiable GDP-like admission rules

Each candidate must:

1. Depend on the attached document; prior knowledge must be insufficient.
2. Use at least two independent evidence regions.
3. Require at least two dependent operations, with at least one operation other than lookup.
4. Include controlling evidence such as a legend, definition, footnote, exception, exclusion, threshold, effective date, or superseding rule.
5. Cover at least one Tier 2 axis and one Tier 3 axis from the allowed labels below.
6. Correspond to a realistic professional action, not a classroom question.
7. Have a concise but complete gold answer whose every claim is grounded in evidence.
8. Include atomic rubric criteria covering the conclusion, decisive evidence, calculation/unit or set completeness, and a plausible dodged bullet.

Reject ideas that can be answered by copying one sentence, reading one cell, identifying one title/date/name, describing one image, reading one chart point, or performing a calculation whose inputs are already in the prompt.

# Allowed capability axes

Tier 2:

- semantic_reading_flow
- typographic_hierarchy
- standard_table_parsing
- chart_multimodal_interpretation

Tier 3:

- complex_multi_page_tables
- cross_referencing
- artifact_noise
- unsupported_queries

# Evidence requirements

- Page numbers are one-based.
- Bounding boxes are normalized as x0, y0, x1, y1 in [0, 1].
- Evidence excerpts may transcribe short decisive fragments, but do not reproduce long passages.
- All key evidence nodes must feed a dependent operation chain ending at `final_output`.
- The final answer must change or become unsupported if any key evidence node is deleted.
- A claim's `supported_by` entries may reference evidence-node IDs or earlier claim IDs. Claim
  dependencies must be acyclic, and every claim must ultimately resolve to at least one PDF
  evidence node.
- A derivation's `inputs` may reference evidence-node IDs or claim IDs; its `result_claim` must
  reference an existing claim.
- Do not invent unreadable values. If decisive evidence is genuinely absent, design an unsupported-query task and state the limited supported conclusion.

# Gold answer policy

Give the final result, necessary values, controlling conditions, and short verifiable calculation. Do not include unverifiable hidden chain-of-thought. Put the auditable structure in claims, derivations, evidence nodes, and operations.

# Contamination policy

Do not imitate, reconstruct, mention, or draw from GDP.pdf benchmark tasks. Work only from the attached non-benchmark PDF.
