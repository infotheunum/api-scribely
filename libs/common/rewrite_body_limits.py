"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is a floor only: models that emit under BODY_MIN_CHARS are
regenerated. There is no hard upper reject — bodies longer than the soft
aspiration band are accepted (editor can trim). Prompt still aims at the
target band.
"""

# Editorial hard floor. Concise news is acceptable only when it still reaches
# this length; anything shorter is regenerated rather than entering review.
BODY_MIN_CHARS = 1500

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 2000
BODY_TARGET_MAX = 3200

# Soft upper guidance in prompts only — over-length is NOT rejected.
BODY_SOFT_MAX_CHARS = 3500

# Back-compat alias (was a hard max; now soft). Prefer BODY_SOFT_MAX_CHARS.
BODY_MAX_CHARS = BODY_SOFT_MAX_CHARS


def body_min_chars_for_source(source_chars: int) -> int:
    """Keep one editorial minimum regardless of the source size.

    ``source_chars`` remains in the signature because the orchestrator passes
    its length profile through the schema and retry prompt.
    """
    del source_chars
    return BODY_MIN_CHARS
