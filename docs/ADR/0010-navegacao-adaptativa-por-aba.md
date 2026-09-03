# ADR 0010: Navegação Adaptativa por Perfil de Aba

## Objetivo
Implementar navegação inteligente baseada em perfil de aba (config declarativa) para evitar a leitura redundante da Home e otimizar as capturas acessando diretamente as telas em Grade ("Ver mais") das seções "Todas"/"Todos", pulando seções desnecessárias da mesma aba para evitar desperdício de tempo e cliques.

## Contexto
Anteriormente, o robô operava varrendo de forma idêntica todas as abas. Ele lia a Home (que continha conteúdo já disponível em outras abas, gerando processamento inútil) e lia seções das abas Filmes/Séries arrastando carrosséis horizontais limitados. A interface do Every Cine possui um botão "Ver mais" para cada categoria (seção) que expande os cards em uma Grade vertical infinita, e algumas abas possuem a categoria "Todas", que engloba o acervo completo da aba.

## Solução
- **Perfil Declarativo (`ABAS_NAV`):** Cada aba recebeu uma configuração de estratégia (ex: `inicio: skip`, `ao_vivo: chip Todos`, `series: secao Todas`, `filmes: todas_secoes`).
- **Pulo por Cobertura:** Nas abas onde a estratégia aponta para a seção "Todas" (Séries e Infantil), o script encontra essa seção, clica em "Ver mais", processa a grade, e ignora as demais seções da tela (pois "Todas" já engloba o conteúdo delas).
- **Distinção Chip vs Seção:** Criamos a função `_descobrir_secoes_e_chips` que diferencia os filtros do topo (`y < 400`) das categorias contendo botões "Ver mais" (`y > 400`), mapeando o texto da seção pela proximidade das coordenadas horizontais e verticais.
- **Grades Verticais:** Alteração no fluxo para substituir a exploração horizontal lenta pela abertura de Grades e rolagem exclusivamente vertical (`processar_grade_vertical`).

## Prevenção
- Inserido suporte a granularidade extra no checkpoint (adicionando a chave `secao`), permitindo ao watchdog retomar o processamento exatamente na categoria em que o robô parou caso ocorra um crash na grade expandida.
- O sistema mantém o dedupe por pHash + título, garantindo que a execução na aba "Filmes" (que varre todas as categorias sequencialmente) não adicione duplicatas se um filme aparecer tanto em "2026" quanto em "Ação".
