# ADR 0013: Política de Atestado de Óbito e Arquivamento

## Objetivo
Implementar a política definitiva de expurgo de mídias que "caíram da grade" (remoção do catálogo da IPTV). Para impedir exclusões indevidas causadas por falso-negativos momentâneos (falha de rede, bug do LDPlayer), estabeleceu-se a regra de "3 strikes em sessões distintas". Mídias mortas recebem um atestado, são arquivadas num arquivo à parte e isoladas da geração de playlists, tudo acompanhado da possibilidade de rollback total e manual pelo usuário.

## Contexto
Durante o acompanhamento do Watchdog de validação (`revalidar_links.py`), percebeu-se que links com o status "morto" iriam ficar ali para sempre caso a IPTV decidisse apagar a mídia. A solução natural de apagar o registro é perigosa porque se ocorrer um falso-negativo por conta do PC do usuário ou do aplicativo instável, uma mídia viva seria apagada sem deixar rastro. 

## Solução
1. **Contabilização Rigorosa**: O `robo_extrator.py`, ao ser operado no `--focar-mortos`, puxa os suspeitos e mortos do `links_mortos.jsonl`. No desfecho da sessão, ele audita quem ele **não viu** (pela URL_KEY original interceptada ou pHash) e incrementa um contador `nao_encontrado_em_tela` (+1).
2. **Proteção de Infraestrutura**: Falhas como `AppCrashError` acionam uma flag de supressão (`_infra_falhou = True`). O robô simplesmente aborta o contador de ausência naquela execução, impedindo que bugs do ambiente punam as mídias injustamente.
3. **Mecânica do Arquivamento**: A flag `--assinar-obitos` foi injetada para que, na virada do strike 3 (NET=3), a entrada da URL saia permanentemente do `catalogo.jsonl` principal, e caia arquivada com todos os seus metadados para dentro de `mortos/catalogo_mortos.jsonl`, carimbada com `data_do_obito` e hash_único, recebendo log `[OBITO]`. O `revalidar_links.py` cessa as tentativas a partir desse momento (visto que parou de ler o arquivo de mortos).
4. **Canais Ao Vivo blindados**: Apesar de obedecerem à mesma regra, Canais_AoVivo jamais são mandados pro cemitério sozinhos. O robô emite o log alertando a necessidade da presença da flag de confirmação humana (`--confirmar-obitos`) para engatilhar o atestado do canal.
5. **Rollback 100% Nativo**: Criada a flag `--restaurar <hash/nome>` no `revalidar_links.py`. Ao usá-la, a mídia sai do cemitério, seus carimbos fúnebres são apagados, e ela é injetada intacta de volta ao `catalogo.jsonl`.

## Prevenção
- Nunca apagar o JSON em nenhum script, exceto se ele transitar atômicamente para uma cópia arquivada.
- Nunca contar uma queda de ADB / Crash do EveryCine como um "Não achei a URL na tela". 
- Não poluir a pasta de playlist (`gerar_playlist_final.py`), pois a extração dos mortos da fonte principal (`catalogo.jsonl`) cessa automaticamente o repasse pra M3U final.
