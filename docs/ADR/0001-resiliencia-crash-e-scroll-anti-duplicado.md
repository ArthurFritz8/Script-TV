# ADR 0001 — Resiliência a crash do app + scroll preciso/anti-clique-duplicado

Data: 2026-09-02
Status: Aceito

## Objetivo

Eliminar duas falhas observadas em produção:
1. O robô para de vez quando o app "Every Cine" crasha/trava no meio da execução
   (perde a sessão inteira, sem retomar do ponto certo).
2. O scroll clica repetidamente no mesmo item, especialmente em cards sem nome
   legível (numerais, banners) e em carrosséis horizontais que "dão a volta".

## Contexto

`robo_extrator.py` navega 100% via ADB (`uiautomator dump` + `input tap/swipe`) e
extrai links por memory dump (`am dumpheap`). Antes desta mudança:
- `estado_visitados.jsonl` marcava um item como visitado **antes** de processá-lo
  (`marcar_visitado`), então um crash no meio do processamento perdia esse item
  para sempre (ele nunca mais seria tentado, mas também nunca foi extraído).
- A chave de dedupe de um card sem nome era `(scroll_n, bounds)` — instável entre
  rolagens, porque o mesmo card físico aparece em `scroll_n` e `bounds` diferentes
  a cada leitura.
- `_explorar_carrosseis_horizontais` só comparava o frame atual com o **imediatamente
  anterior**; um carrossel que dá a volta completa nunca era detectado.
- Não havia verificação de que o app ainda estava vivo/em foco, nem recuperação
  automática após uma queda.

## Solução

### Frente 1 — Resiliência a crash
- **Ciclo de vida de 3 estados** em `estado_visitados.jsonl`: cada linha agora é
  `{"chave": [...], "status": "em_processo"|"concluido"}` (append-only; a última
  ocorrência de cada chave manda). Linhas do formato antigo (lista simples) continuam
  sendo lidas e equivalem a `"concluido"` — **compatibilidade total com dados já
  gravados**. `foi_visitado()` só retorna `True` para `"concluido"`; um item que ficou
  `"em_processo"` num crash é automaticamente re-tentado na próxima execução.
- **Watchdog de saúde** (`app_esta_saudavel`): `pidof` + `dumpsys window | grep
  mCurrentFocus`. Chamado nos 2 pontos de maior risco real (não em todo `tap()`, ver
  veto abaixo): antes de abrir um item/episódio novo, e logo após cada `dumpheap`.
- **Detecção de diálogo de erro/ANR** (`detectar_dialogo_erro` /
  `tentar_lidar_com_dialogo`): antes de declarar crash de vez, tenta identificar e
  fechar um diálogo comum (erro de reprodução do app, ou ANR "isn't responding" do
  Android) tocando em "Esperar"/"Fechar"/"Tentar novamente".
- **Checkpoint de posição** (`Log/estado_posicao.json`, sobrescrito): guarda
  `{aba, sub_aba, scroll_n}`. Usado (a) como contexto no log de crash, e (b) no boot
  de uma execução nova (processo inteiro reiniciado) para reordenar as abas e começar
  direto pela que estava em andamento, em vez do zero — só quando o usuário não
  escolheu abas específicas via `--abas`.
- **Recuperação de crash + proteção contra crash-loop**: `AppCrashError` é levantada
  nos pontos de watchdog e propagada explicitamente através dos `except Exception`
  intermediários (`processar_item`, `processar_aba_com_subabas`) — nunca é engolida no
  meio do caminho. `_rodar_aba_resiliente` captura qualquer exceção, aplica backoff
  progressivo (30s/60s/120s numa janela de 10 min) via `registrar_crash`, chama
  `recuperar_de_crash` (reinicia o app) e tenta a função da aba de novo. Acima de 3
  crashes na janela, desiste da aba (evita loop infinito).

### Frente 2 — Scroll preciso e anti-clique-duplicado
- **pHash (aHash simples, só Pillow)** para cards **sem nome confiável**: reduz o
  recorte do card a 8x8 em escala de cinza e gera um hash de 64 bits. A chave de
  dedupe passa a ser `("card","phash",label,hash)` — estável entre rolagens porque
  depende do conteúdo visual, não de `bounds`/`scroll_n`. Distância de Hamming ≤ 5
  (`_LIMIAR_PHASH`, ajustável) agrupa recortes "visualmente iguais". Persiste no
  **mesmo** `estado_visitados.jsonl` (a chave é só mais uma tupla) — sem novo arquivo
  nem formato novo.
- **Fim/loop de carrossel horizontal**: trocado o comparador de "frame anterior" por
  um `set` de todos os frames já vistos naquela fileira — resolve tanto o fim normal
  quanto um carrossel que dá a volta completa.
- **Pré-checagem por nome-base** (`nomes_base_salvos`, populado em `salvar()` a partir
  de `meta["nome_base"]`): pula o clique (sem nunca clicar) se o título normalizado do
  card já foi salvo antes — **só** para Filme/Infantil/Outros (nunca Série, que pode
  ganhar episódios novos; nunca Canal, que usa variantes de propósito).
- **Screenshot único por leitura de tela**, compartilhado entre OCR e pHash de todos
  os cards daquela leitura (antes: 1 screencap por card sem nome).
- **Cache de `get_ui_xml()` com TTL de 1.5s**, invalidado automaticamente em qualquer
  `tap()`/`back()`/`swipe_up()`/`swipe_left()` — nenhum call-site precisou mudar.

### Correção estrutural (não pedida, mas necessária)
- Import do `PIL.Image` separado do `pytesseract`: antes, faltar o binário do
  Tesseract também derrubava a disponibilidade do Pillow (usado só pelo pHash), sem
  necessidade.

## Vetos aplicados (com justificativa)

1. **"Watchdog antes de CADA tap"** — recusado ao pé da letra: custaria 2 round-trips
   ADB em dezenas de taps por item (delays de navegação, back, etc.), sem ganho real.
   Aplicado só nos 2 pontos onde um crash de fato importa (abrir item novo / pós-dump).
2. **"pHash para detectar fim de carrossel"** — recusado: a causa raiz ali (R4) é um
   bug de comparação (só olha o frame anterior), resolvido com um `set` de bounds já
   vistos, sem precisar de imagem nenhuma. Mais barato e igualmente eficaz.
3. **"Pré-checagem por nome aplicada geral"** — restrita a Filme/Infantil/Outros. Uma
   Série pode ganhar episódios novos com o tempo, e o dedupe por episódio já evita
   duplicata real ali; aplicar geral quebraria a cobertura de novos episódios.
4. **Nenhuma mudança no formato de `catalogo.jsonl`/`.m3u`, na lógica de memory dump
   (`extrair_link_memoria`) nem na decisão de manter todas as qualidades** — nenhum
   veto do usuário foi violado.

## Prevenção

- Testes offline (sem ADB/emulador) cobrindo: ciclo de vida em_processo→concluido com
  compatibilidade do formato legado, checkpoint de posição, backoff/limite de
  crash-loop, e poder discriminativo do pHash (mesmo card com ruído vs. cards
  diferentes) — todos passaram.
- `chave_fingerprint_card` cai no fallback antigo (`scroll_n`+`bounds`) se o Pillow
  não estiver disponível ou der qualquer erro — **zero regressão** nesse cenário.
- `_LIMIAR_PHASH=5` é uma constante nomeada isolada; se, em uso real, cards diferentes
  forem agrupados por engano (ou o mesmo card não for reconhecido), é o primeiro
  parâmetro a ajustar.
