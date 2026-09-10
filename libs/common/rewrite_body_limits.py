"""Shared rewrite body length limits (worker + rewrite services).

Hard gate is a floor only: models that emit under BODY_MIN_CHARS are
regenerated. There is no hard upper reject — bodies longer than the soft
aspiration band are accepted (editor can trim). Prompt still aims at the
target band.
"""

# Hard accept/reject floor (schemas + regenerate filter).
# Articles shorter than this are not eligible for review. The retry path
# must move on to another cluster rather than accept thin content.
BODY_MIN_CHARS = 2500

# Aspiration in prompts (models aim here; not a second hard gate).
BODY_TARGET_MIN = 2500
BODY_TARGET_MAX = 3200

# Soft upper guidance in prompts only — over-length is NOT rejected.
BODY_SOFT_MAX_CHARS = 3500

# Back-compat alias (was a hard max; now soft). Prefer BODY_SOFT_MAX_CHARS.
BODY_MAX_CHARS = BODY_SOFT_MAX_CHARS
