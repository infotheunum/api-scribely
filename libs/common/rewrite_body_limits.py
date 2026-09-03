"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is intentionally below the editorial target: gpt-4o-mini / free
models routinely emit ~1300–1800 chars on the first pass, and a 2000-floor
caused 2–3 full LLM calls per cluster (and dead-letters). Prompt still aims
for the target band; validation only rejects clearly short/long text.
"""

# Hard accept/reject (schemas + regenerate filter).
BODY_MIN_CHARS = 1300
BODY_MAX_CHARS = 2500

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 2000
BODY_TARGET_MAX = 2300
