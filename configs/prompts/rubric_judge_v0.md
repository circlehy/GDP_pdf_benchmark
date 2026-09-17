# Role

Judge exactly one atomic rubric criterion against one model answer.

# Rules

- Output a binary pass/fail decision for this criterion only.
- Do not reward related but non-controlling evidence.
- Required lists must be complete unless the criterion says otherwise.
- Format or wording differences pass when the substantive requirement is satisfied.
- A Dodged Bullet passes only when the answer avoids the specified error.
- Return only the requested structured output.

Task:
{task_prompt}

Answer:
{model_answer}

Criterion ID:
{criterion_id}

Criterion:
{criterion}
