# ADR 0014: Escada de Sanidade de Payload (Integridade)

## Objetivo
Detectar falsos-positivos na validação de links (por ex., páginas HTML de erro que retornam status 200, ou arquivos de zero-bytes) sem onerar a banda do servidor ou o processamento local. Em vez de fazer download dos vídeos, utiliza-se uma escada de sondagem com Range GET limitado e Caching de Assinaturas (ETag/Tamanho), integrada diretamente na política dos 3 Strikes (ADR 0013).

## Contexto
O método clássico via HTTP HEAD (`urllib.request`) confirma se o link não sofreu 404. Contudo, plataformas de CDN frequentemente interceptam URLs órfãs e entregam uma página HTML com propagandas ou um player estático, respondendo HTTP 200 OK. Isso ludibria o Watchdog que manteria o link morto vivo para sempre na playlist.

## Solução
Implementou-se a `sondar_url` com 3 Níveis de escalada:
1. **Nível 1 (HEAD Enriquecido)**: 
   Realiza a requisição HEAD (seguindo redirecionamentos 302 nativamente) para coletar o `Content-Type`, `Content-Length`, `ETag` e `Last-Modified`. Se o Content-Type apontar para HTML numa URL de mídia, o link ganha falha primária.
2. **Nível 2 (Range GET + Sniffing + Cap Limit)**: 
   Se a assinatura do Nível 1 for nova ou tiver mudado desde a noite passada (`cache_sondagem.json`), disparamos um GET com o header `Range: bytes=0-4095`. Um limite rígido na leitura (Cap Limit de 4KB) é efetuado caso a CDN não obedeça o header.
   Checa-se os Magic Bytes. Se retornou `<!doctype` ou `<html`, o arquivo é descartado. Streams de HLS (`.m3u8`) e Ao Vivo ignoram a ausência de Content-Length sem serem penalizados.
3. **Nível 3 (Verificação Opcional FFProbe)**: 
   Adicionada a flag opcional `--verificar TITULO` que chama o sub-processo nativo `ffprobe` caso o usuário queira auditar metadados de corrupção intrínseca (ex: vídeo sem codec suportado).

## Integração com Óbitos (ADR 0013)
* Cada recusa por payload incorreto gera 1 *strike* em `falha_integridade`. 
* Timeout ou bloqueios (403, 500) caem na contabilidade de **Infra** e protegem o link (0 strikes computados). 
* Se um arquivo atingir 3 *strikes* de Integridade de forma consecutiva, ele será expurgado e arquivado (Cemitério de Óbitos) automaticamente, seguindo as premissas do ADR 0013.

## Prevenção
- **Loop Infinito HLS/AoVivo**: Aoivos não sofrem punições drásticas no script; requerem `--confirmar-obitos` para serem enterrados.
- **Veto ao Download**: O `r_get.read(4096)` impede perdas de memória e consumo de banda (se o server enviar 50GB em um 200 normal ignorando o Range, apenas 4KB caem no PC).
