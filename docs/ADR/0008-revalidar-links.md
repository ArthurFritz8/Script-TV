# ADR 0008: Revalidador de Links (Non-Destructive)

## Objetivo
Criar uma camada autônoma de qualidade (`revalidar_links.py`) capaz de iterar sobre o catálogo em _background_, marcando URLs mortas (quebradas) ou suspeitas para que o gerador de playlist possa expurgá-las. A camada é desenhada sob o princípio de "Nunca Deletar", operando um sidecar separado para garantir integridade.

## Contexto
O servidor de origem (CDN) muda frequentemente chaves, derruba vídeos ou desativa rotas velhas. Contudo, falsos negativos (exclusão de um filme bom só porque a API do app demorou para responder num dado minuto) frustram mais do que deixar um link morto na lista (que o usuário apenas pula na TV). Era imperativo um sistema _leniente_ de strikes.
Adicionalmente, canais ao-vivo sofrem rotatividade de token horária, não devendo ser medidos na mesma régua que VOD (Video On Demand).

## Solução
O script `revalidar_links.py` atua via requisições HTTP `Range: bytes=0-100` (economia de banda).
1. **Sidecar (Não-destrutivo):** O arquivo matriz `catalogo.jsonl` jamais é editado; todo o registro de mortalidade é gravado num mapa em cache `Log/links_mortos.jsonl`. O gerador de playlist intercede lendo esse arquivo para pular as linhas infectadas (caso a flag `--incluir-mortos` não seja passada).
2. **2-Strike Rule:** Exige-se que um link falhe em duas execuções separadas por >24h (TTL) para que atinja o status terminativo de `morto`. Apenas `morto` bloqueia a exibição.
3. **Resiliência a API/Geo:** Respostas como 429, 403 (Forbidden por troca de User-Agent), Timeout ou erro de OS geram um bloqueio temporário que acusa `suspeito`, **sem incrementar o strike count**, prevenindo aniquilações em massa provocadas por perda momentânea da internet local.

## Prevenção
- É estritamente proibido adicionar rotinas de `del` ou `remove` na estrutura que mantém ou gerencia o `catalogo.jsonl`.
- Categorias altamente voláteis como `Canais_AoVivo` são sempre ignoradas nativamente na rotina de ping (a menos que instadas sob a flag `--incluir-ao-vivo`).
