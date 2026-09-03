"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is a floor only: models that emit under BODY_MIN_CHARS are
regenerated. There is no hard upper reject — bodies longer than the soft
aspiration band are accepted (editor can trim). Prompt still aims at the
target band.
"""

# Hard accept/reject floor (schemas + regenerate filter).
BODY_MIN_CHARS = 1700

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 2000
BODY_TARGET_MAX = 2800

# Soft upper guidance in prompts only — over-length is NOT rejected.
BODY_SOFT_MAX_CHARS = 3000

# Back-compat alias (was a hard max; now soft). Prefer BODY_SOFT_MAX_CHARS.
BODY_MAX_CHARS = BODY_SOFT_MAX_CHARS
