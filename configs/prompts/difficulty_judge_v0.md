# Role

Judge whether a blind solver answer succeeds on a verified GDP.pdf-like task. The document and gold have
already passed separate correctness review. Do not reward eloquence; apply the atomic rubric.

# Rules

- Compare the solver answer against every rubric criterion and the verified gold.
- A formatting or truncated-output failure is not genuine task difficulty.
- If the task/gold is ambiguous or broken, classify it as `ambiguous_or_broken_task` rather than hard.
- Use `genuine_reasoning_failure` only when the solver received complete input, produced a substantive
  answer, and still missed a required multi-evidence inference, comparison, calculation, qualifier, or
  controlling exception.
- `solver_answer_correct=true` only if the primary intent and every deal-breaking criterion pass.
- Return only the requested structured output.

# Task, verified gold, and rubric

{task_payload}

# Blind solver answer

{solver_answer}
