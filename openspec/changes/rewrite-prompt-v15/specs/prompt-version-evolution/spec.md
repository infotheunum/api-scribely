## ADDED Requirements

### Requirement: New prompt candidates preserve active editorial rules

The system SHALL create v15 as a draft by copying the currently active prompt
template and appending the v15 fidelity appendix. It MUST NOT retire or replace
the active prompt while creating the candidate.

#### Scenario: Active v13 remains active while v15 is prepared

- **WHEN** an operator creates the v15 candidate
- **THEN** the candidate contains the full active template followed by the
  fidelity appendix
- **AND** the prior active prompt remains active until an administrator
  explicitly activates the candidate.

### Requirement: Missing years are never invented

The system SHALL reject a rewrite that adds a calendar year absent from the
original source, including 2023 when the surrounding context is 2026.

#### Scenario: Source contains a month and day but no year

- **WHEN** the rewrite says "12 сентября 2023 года" for an original that says
  only "12 сентября"
- **THEN** the factual quality gate rejects the rewrite.
