# ADR 0006: Cache de Pôsteres TMDB e Tvg-Logo Local

## Objetivo
Implementar a injeção da tag `tvg-logo` nas entradas de Filmes, Séries e Infantil da playlist consolidada IPTV, obtendo as capas do The Movie Database (TMDB) de forma assíncrona (apenas durante a consolidação) e servindo os pôsteres a partir do servidor HTTP local.

## Contexto
O player IPTV TiviMate e outros players dependem da tag `tvg-logo` no formato m3u para carregar visualmente a grade. As opções eram: usar hotlink para imagens na CDN do TMDB direto na m3u, ou hospedar na nossa máquina. 
O uso de hotlink é arriscado porque: (1) O IPTV pode ser penalizado ou bloqueado pela API do TMDB devido a requisições maciças a cada zapping, (2) Em caso de queda de rede ou da API, a interface inteira do usuário fica sem imagens.
Além disso, futuramente, teremos um "preview grid" de auditoria local que consumirá exatamente as mesmas capas. 

## Solução
Foi desenvolvido um módulo helper `tmdb_cache.py` compartilhado:
1. Faz o fetch via `urllib` limitando a categoria específica (`search/movie` vs `search/tv`), requisitando o pôster no tamanho ideal (`w342`).
2. Persiste em disco as imagens na pasta `Log/capas/<hash>.jpg`, utilizando um hash fixo e persistente de `nome_base + categoria` registrado em um banco JSON simples (`Log/tmdb_cache.json`).
3. Em caso de expiração da chave, ausência de chave (degradação silenciosa), ou erro HTTP 429 (rate limit), o processo desiste de contatar a API naquela execução específica e pula a injeção de `tvg-logo` ou serve o que já tinha em cache, nunca travando o gerador.
4. O `gerar_playlist_final.py` injeta o endereço base na flag `tvg-logo`, formatando-o para `http://<IP_LOCAL>:8765/capas/<hash>.jpg`, que é servido pelo nosso `servir_playlist.py` sem modificações adicionais.

## Prevenção
- **Sem hotlinks:** Proibido embutir qualquer URL do domínio `tmdb.org` em arquivos finais m3u. Toda capa listada na m3u final aponta inexoravelmente para `http://<IP_LOCAL>:8765/capas/...`.
- **Fusão de domínios:** Nenhuma feature futura (como preview grids de auditoria) deverá criar uma lógica separada de fetch de capas, devendo consumir este mesmo módulo cache.
