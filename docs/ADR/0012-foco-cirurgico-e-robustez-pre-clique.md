# ADR 0012: Portão Pré-Clique Robusto e Integração Cirúrgica com Revalidador

## Objetivo
Tornar a mecânica de portão pré-clique resiliente a instabilidades de rede (evitando re-dumps falsos por causa de falhas momentâneas de HTTP) e promover a integração do `robo_extrator.py` com o artefato de auditoria passiva `links_mortos.jsonl` (gerado pelo `revalidar_links.py`). Evitamos assim varreduras cegas de renovação, focando cirurgicamente no que o revalidador comprovou estar morto.

## Contexto
O portão pré-clique do ADR 0011 realizava um teste `HEAD` para cada card. Se falhasse 1 vez, forçava clique. Na prática, a rede do PC do usuário ou o servidor HTTP pode dar *timeout* (falso negativo). Adicionalmente, foi levantada a ideia de um *Watchdog Mudo*. No entanto, esse watchdog já existe (`revalidar_links.py`)! Ele cria um *sidecar file* com `url_key` e o `status` (suspeito/morto). A evolução natural é casar as duas pontas: usar a lista gerada de madrugada pelo revalidador como uma "lista VIP de prioridade" para o `robo_extrator.py` focar sua ação.

## Solução
1.  **Flag `--focar-mortos`**: O `robo_extrator.py` carrega o arquivo `links_mortos.jsonl`. Cards que deem match (`nome` ou `pHash`) com a prioridade ignoram o pré-check e forçam a extração para renovar.
2.  **Robustez no pré-clique comum**: Caso não haja prioridade, o pré-check via `HEAD` é feito com TTL (cache via `_urls_validadas_sessao`). Uma falha nesse `HEAD` **não** força mais a extração de cara; logamos apenas `[SUSPEITO]` e pulamos mesmo assim. Só forçamos o re-dump se a URL já estiver "morta" pelo revalidador (2 strikes em dias distintos) via arquivo prioritário.
3.  **Sobrescrita Atômica**: Se o clique for forçado e a memória revelar nova URL (renovação de fato), a função `salvar` intercepta, detecta a diferença contra o cache local, emite um log visual explícito (`[RENOVACAO] velha -> nova`) e atualiza o `catalogo.jsonl` preservando os *metadados* já conhecidos.
4.  **Looping Opcional**: Adicionado o arg `--loop-intervalo` no `revalidar_links.py`, permitindo deixá-lo rodando de fundo continuamente (Watchdog Mudo) no Task Scheduler.

## Prevenção
- Nunca sobrescrever o catálogo se o robô pegar uma string vazia ou se houver "match fake" (garantido pela verificação de `url.startswith("http")` e URL não duplicada).
- A flag `--focar-mortos` é 100% retro-compatível (se o arquivo não existir, o robô faz sua rotina normal, sem engasgar).
- Veto à criação de novos scripts. Tudo unificado dentro do fluxo de trabalho orquestrado em 3 pontas (validar -> extrair morto -> sincronizar).
