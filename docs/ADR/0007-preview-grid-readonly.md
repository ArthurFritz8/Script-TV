# ADR 0007: Preview Grid Local Read-Only

## Objetivo
Estabelecer um layout de visualização estilo grade ("Netflix local") para o `gerar_preview_html.py`, capaz de exibir capas sem realizar o fetch na internet. Ele será inteiramente alimentado pelo cache do TMDB em disco, já construído para a m3u, servindo estritamente como ferramenta rápida de auditoria interna, não como uma dependência externa.

## Contexto
O usuário final desejava ter uma visualização clara para conseguir auditar facilmente os milhares de títulos extraídos e classificados pelo robô (detectando anomalias de qualidades, títulos esquisitos que não foram bem reconhecidos pelo aplicativo nativo ou OCR).
A implementação anterior pretendia integrar chamadas ativas à API do TMDB dentro desse processo de geração. Isso introduziu vulnerabilidades operacionais: tempo de resposta lentíssimo para milhares de instâncias, dependência de chaves, esgotamento da cota TMDB_API_KEY só para renderizar a página local, e a reconstrução dupla da lógica de hash da capa.
Além disso, se usassem-se os links quentes do TMDB (hotlinks) diretamente na renderização HTML, uma quebra na conectividade ou restrição corporativa derrubaria toda a renderização do preview.

## Solução
O módulo `gerar_preview_html.py` foi reescrito para utilizar a dependência `tmdb_cache.py` **em modo exclusivamente read-only (somente leitura)**.
1. O preview HTML incorpora a exata mesma função de ordenação (`chave_ordenacao`) e regras estabelecidas na playlist consolidada final (`gerar_playlist_final.py`). Isso garante que o preview é a representação fideis de como o conteúdo aparecerá para o player TiviMate.
2. Em `tmdb_cache.py`, a mesma função que gera o hash (`gerar_hash_chave(nome, categoria)`) foi exposta para reuso, juntamente com o leitor passivo de estado local `resolver_poster_local`.
3. Para as categorias atreladas (Filmes, Séries, Infantil), o HTML exibe a `<img>` da capa apenas se já estiver persistida de rodadas anteriores na subpasta `Log/capas/<hash>.jpg`. Nenhum processo adicional de HTTP Request ocorre caso contrário; uma div com a inicial do filme assume como _placeholder_.

## Prevenção
- **Isolamento de Consumidor:** A API do TMDB só deve ser consumida pela lógica responsável por renderizar a _playlist final_, sob estritas condições de backoff/rate-limit.
- **Nenhum Fetch na Interface:** Scripts voltados unicamente para interfaces de visualização/debug do catálogo, como o `gerar_preview_html`, ficam terminantemente vetados de instanciar sessões web diretas e devem degradar silenciosamente.
