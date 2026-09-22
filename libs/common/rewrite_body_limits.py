"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is a floor only: models that emit under BODY_MIN_CHARS are
regenerated. There is no hard upper reject — bodies longer than the soft
aspiration band are accepted (editor can trim). Prompt still aims at the
target band.
"""

# Technical floor only. Editorial length follows source density; a sparse
# title/excerpt must not be padded with invented prose.
BODY_MIN_CHARS = 300

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 800
BODY_TARGET_MAX = 2500

# Soft upper guidance in prompts only — over-length is NOT rejected.
BODY_SOFT_MAX_CHARS = 4000

# Back-compat alias (was a hard max; now soft). Prefer BODY_SOFT_MAX_CHARS.
BODY_MAX_CHARS = BODY_SOFT_MAX_CHARS


def body_min_chars_for_source(source_chars: int) -> int:
    """Keep one editorial minimum regardless of the source size.

    ``source_chars`` remains in the signature because the orchestrator passes
    its length profile through the schema and retry prompt.
    """
    del source_chars
    return BODY_MIN_CHARS
