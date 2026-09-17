"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is a floor only: models that emit under BODY_MIN_CHARS are
regenerated. There is no hard upper reject — bodies longer than the soft
aspiration band are accepted (editor can trim). Prompt still aims at the
target band.
"""

# Absolute hard floor for a short, factually complete news item.  A higher
# floor is calculated from the supplied source corpus below.  This prevents a
# thin source from being padded with invented context merely to reach 1,700
# characters, while still rejecting one-line output.
BODY_MIN_CHARS = 900

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 2000
BODY_TARGET_MAX = 3200

# Soft upper guidance in prompts only — over-length is NOT rejected.
BODY_SOFT_MAX_CHARS = 3500

# Back-compat alias (was a hard max; now soft). Prefer BODY_SOFT_MAX_CHARS.
BODY_MAX_CHARS = BODY_SOFT_MAX_CHARS


def body_min_chars_for_source(source_chars: int) -> int:
    """Return the hard body floor appropriate for the source material.

    The model receives the full source corpus, not a fixed article template.
    Requiring every short wire item to reach a long-form floor was the primary
    cause of retry/defer loops in production.  Larger source packs retain a
    stricter minimum; factual and language quality gates still apply at every
    length.
    """
    if source_chars <= 2200:
        return BODY_MIN_CHARS
    if source_chars <= 5000:
        return 1200
    return 1700
