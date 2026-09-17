## ADDED Requirements

### Requirement: Human-neutral Russian rewrite style

The Russian rewrite SHALL use direct, neutral information style. It SHALL not
add the transition «Так,» or mechanically replace it with «Таким образом»,
«Следовательно» or a similar filler. It SHALL express a confirmed fact through
the actor and action when possible, avoid avoidable short adjectives and verbal
nouns, and preserve fixed technical terms when changing them would alter the
meaning.

#### Scenario: Avoidable bureaucratic construction

- **WHEN** the source-supported draft contains «этого движения было
  достаточно, чтобы цена вернулась...»
- **THEN** the rewrite uses a natural action-based construction
- **AND** it does not introduce a conclusion about the market that is absent
  from the source.

### Requirement: Sentence and terminology clarity

The Russian rewrite SHALL keep one main thought per sentence and SHALL split a
sentence that combines a term definition, an evaluation and historic context.
It SHALL use established market terminology and SHALL not coin a literal
translation when the term is ambiguous.

#### Scenario: Ambiguous technical term

- **WHEN** the source uses a term whose accepted Russian equivalent cannot be
  determined from the source and editorial glossary
- **THEN** the rewrite does not invent a translation
- **AND** the review report contains an editorial-review flag for that term.

### Requirement: Familiar abbreviations and headline meaning

The Russian rewrite SHALL not automatically expand familiar abbreviations such
as `ИИ`, `EMA`, `BTC` and `ETH`. Its headline SHALL use natural Russian word
order, preserve the source's certainty, and distinguish a movement in a pair
from a dollar-price movement.

#### Scenario: Relative price movement in a headline

- **WHEN** the source says that ETH may decline by 10 percent relative to BTC
- **THEN** the headline states that it concerns the ETH/BTC rate, for example
  «Курс эфириума к биткоину может упасть на 10%»
- **AND** it does not state that the dollar price will fall.

### Requirement: Russian proofread pass

The quality gate SHALL reject a Russian rewrite with a material spelling,
punctuation, agreement, governance or established-terminology error. It SHALL
not insert a comma after «тем не менее» solely because of that phrase.

#### Scenario: Incorrect comma after phrase

- **WHEN** a rewrite says «Тем не менее, цена продолжила снижаться» without
  another grammatical basis for the comma
- **THEN** the quality gate returns a language issue
- **AND** the rewrite is not approved.
