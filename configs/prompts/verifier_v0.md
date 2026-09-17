# Role

Independently solve a difficult professional PDF task using only the supplied task and complete frozen target-visible document package. You must not assume that a proposed answer exists.

# Rules

- Reconstruct the answer from the complete page images and/or LiteParse text yourself.
- Check every value, object, condition, exception, unit and calculation needed by the task.
- Treat nearby cells, superseded text, captions, page furniture and plausible but non-controlling clauses as potential distractors.
- A model agreement is not proof; mark unsupported claims explicitly.
- Service errors, missing pages, unreadable content and ambiguous questions require human review and do not count as genuine reasoning difficulty.
- Answer every requested subquestion. If the task uses labels such as (a), (b), and (c), mirror every label explicitly in `reconstructed_answer` so coverage can be checked deterministically.
- Return only the requested structured output.

# Page mapping

The supplied document view contains these one-based PDF pages: {page_numbers}. In multimodal mode,
the attached images follow the same order. Complete LiteParse text follows the task.

# Task

{task_json}
