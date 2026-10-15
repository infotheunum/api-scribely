## Decision

`embed_texts` отмечает время использования. Конец cluster-тика вызывает
`release_embedding_model_if_idle` (180 с). Вне окна генерации по-прежнему
сразу `release_embedding_model`.

Оба пути делают `gc.collect()` и `malloc_trim(0)` (glibc; на macOS нет
символа — пропуск).
