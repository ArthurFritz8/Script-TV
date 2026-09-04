# ADR 0011: Navegação por Fila de Categorias e Portão Pré-Clique com Verificação de Link Vivo

## Objetivo
Abandonar a falsa premissa de que a seção "Todas" possui o catálogo completo. O robô deve varrer categoria por categoria (via "Ver mais"), mas utilizando um "Portão de Identidade Pré-Clique" para evitar cliques e extrações de memória desnecessárias em conteúdos já salvos. Adicionalmente, resolver o problema de links rotativos (IPTV) verificando a validade do link salvo antes de decidir pular.

## Contexto
No plano anterior (ADR 0010), implementamos a estratégia de navegar até a seção "Todas/Todos" e pular as outras categorias, imaginando que aquela seção englobava o catálogo completo da aba. No entanto, após análise aprofundada, foi constatado que a grade "Todas" omite conteúdos. Além disso, simplesmente pular cliques utilizando deduplicação no Memory Dump gerava um problema grave: se a IPTV trocar a URL do vídeo no backend, o robô não baixaria a nova URL, pois consideraria o filme já processado e pularia a extração.

## Solução
- **Fila de Categorias**: O robô agora percorre as abas listando todos os *Chips* no topo da tela (ex: "Ação", "Terror", etc). Ele clica em cada chip, clica no respectivo botão "Ver mais", carrega a Grade Expandida, varre ela completamente, e depois volta para a próxima categoria da fila.
- **Portão de Identidade Pré-Clique**: Antes de tocar em qualquer card, o robô calcula a identidade do conteúdo (nome normalizado + pHash da imagem do card).
- **Validação Rápida de Sinal (HTTP HEAD)**: Se a identidade do card bater com o banco de dados do `catalogo.jsonl`, o robô resgata a URL salva e faz um request HTTP Rápido (`HEAD`) com timeout curto.
  - Se a URL antiga retornar OK (200), o robô pula o clique.
  - Se a URL antiga retornar Erro/Morto, o robô aborta o pulo e força o clique, recuperando a nova URL no Memory Dump para manter o banco atualizado.
- **Persistência de Fila**: A categoria que está sendo processada é salva no `estado_posicao.json`, impedindo o robô de re-processar grades gigantes caso a aplicação sofra um crash no meio.

## Prevenção
- Canais Ao Vivo e Séries têm lógicas de exceção para não pular cliques cegamente apenas pelo título base, uma vez que Séries possuem episódios novos frequentemente e Canais têm instabilidades de servidor contínuas (exigindo verificação profunda).
- O portão é conservador: qualquer dúvida (falta de pHash com título cortado) força o clique para evitar perder um conteúdo legítimo (falso positivo).
