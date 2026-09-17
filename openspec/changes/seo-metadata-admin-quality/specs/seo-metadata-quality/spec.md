## ADDED Requirements

### Requirement: Source-grounded SEO metadata

For each active language, the system SHALL generate and validate SEO title,
description and focus keyphrase against that language's H1, body and source
facts. The metadata SHALL identify the primary entity and event, preserve
certainty and numbers from the source, and SHALL not add a fact, date, year or
claim absent from the article.

#### Scenario: Meaningful but non-identical SEO title

- **WHEN** a Russian H1 describes a financial regulator's specific blockchain
  priority for 2026
- **THEN** the SEO title identifies the regulator, the blockchain priority and
  the year in natural Russian
- **AND** it need not duplicate the H1 word for word.

### Requirement: SEO language and length diagnostics

The system SHALL validate spelling and punctuation in SEO metadata and SHALL
record title and description lengths. A factual or language error SHALL be a
blocking diagnostic. A recommended-length deviation SHALL be a warning.

#### Scenario: Misspelled SEO title

- **WHEN** a Russian SEO title contains «приоритизерует»
- **THEN** the SEO review report identifies the title field and spelling error
- **AND** publishing is blocked until it is corrected.

### Requirement: Revalidated editor-facing SEO review

The draft detail page SHALL expose editable SEO and OG fields, per-language
SERP previews, field-length counters and the latest SEO diagnostics. Saving
SEO fields SHALL revalidate them without regenerating the article.

#### Scenario: Editor fixes a Russian title

- **WHEN** an editor corrects a blocking Russian SEO-title error and saves the
  draft
- **THEN** the system stores the corrected metadata and replaces the related
  diagnostic
- **AND** the draft can be published if no other blocking checks remain.
