## ADDED Requirements

### Requirement: SEO review visibility in the admin interface

The admin draft-detail interface SHALL show the review status separately for
RU and EN. Each diagnostic SHALL show its field, severity, rule and concise
human-readable explanation. Blocking diagnostics SHALL be visually distinct
from warnings.

#### Scenario: RU-only metadata problem

- **WHEN** the Russian SEO title has a blocking language error and the English
  metadata is valid
- **THEN** the RU preview and status show the blocking issue
- **AND** the EN preview remains valid and independently editable.
