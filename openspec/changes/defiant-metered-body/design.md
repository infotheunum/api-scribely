## Decision

`fetch_article` возвращает `ArticleFetch(withheld=True)`, когда в HTML есть
`contentAccess` `metered` или `pro` и пустой массив `content` (в том числе
в escaped Next.js payload).

Poller для Tier 1 с коротким RSS при `withheld` пропускает запись.
`fetch_full_text` для такого URL возвращает `None`.
