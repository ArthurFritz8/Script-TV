#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Revalidador de Links (Camada de Qualidade Não-Destrutiva)
Verifica os links do catalogo.jsonl via HTTP e grava status em links_mortos.jsonl.
NUNCA deleta entradas do catalogo original.
"""

import sys, os, json, time, argparse, tempfile
from datetime import datetime, timedelta
import urllib.request
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
LOG_DIR       = os.path.join(BASE_DIR, "log")
CATALOGO_PATH = os.path.join(LOG_DIR, "catalogo.jsonl")
MORTOS_PATH   = os.path.join(LOG_DIR, "links_mortos.jsonl")

TTL_HORAS = 24
TIMEOUT = 5

CORES = {
    "INFO": "", "OK": "\033[92m", "WARN": "\033[93m",
    "ERR": "\033[91m", "NET": "\033[96m"
}

def log(msg, nivel="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    cor = CORES.get(nivel, "")
    reset = "\033[0m" if cor else ""
    print(f"{cor}[{ts}] [{nivel}] {msg}{reset}")

def carregar_catalogo(incluir_ao_vivo):
    """Lê todas as URLs do catalogo.jsonl, retornando dicionário por url_key."""
    itens = {}
    if not os.path.exists(CATALOGO_PATH):
        log("Catalogo não encontrado.", "ERR")
        return itens
    
    with open(CATALOGO_PATH, encoding="utf-8", errors="replace") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                reg = json.loads(linha)
                url_key = reg["url_key"]
                cat = reg.get("categoria", "")
                if cat == "Canais_AoVivo" and not incluir_ao_vivo:
                    continue
                itens[url_key] = reg
            except (ValueError, KeyError):
                continue
    return itens

def carregar_mortos():
    """Lê o estado atual do sidecar links_mortos.jsonl."""
    mortos = {}
    if not os.path.exists(MORTOS_PATH):
        return mortos
    with open(MORTOS_PATH, encoding="utf-8", errors="replace") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                reg = json.loads(linha)
                mortos[reg["url_key"]] = reg
            except (ValueError, KeyError):
                continue
    return mortos

def salvar_mortos_atomico(mortos_dict):
    """Grava de forma segura (tmp + rename) para evitar corrupção no Ctrl+C."""
    os.makedirs(LOG_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=LOG_DIR, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for key, reg in mortos_dict.items():
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    os.replace(tmp_path, MORTOS_PATH)

def testar_url(url, usar_fallback_ua=False):
    """Testa URL com requisição parcial. Captura status 403/401."""
    if usar_fallback_ua:
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    else:
        ua = 'ExoPlayerDemo/2.11.8 (Linux;Android 9) ExoPlayerLib/2.11.8'
        
    req = urllib.request.Request(url, headers={
        'User-Agent': ua,
        'Range': 'bytes=0-100'
    })
    
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            ct = res.info().get('Content-Type','')
            return True, ct, 200
    except HTTPError as e:
        if e.code == 206:
            return True, e.headers.get('Content-Type',''), 206
        return False, str(e.code), e.code
    except Exception as e:
        return False, str(e), 0

def processar_item(url_key, registro_catalogo, estado_anterior):
    url = registro_catalogo["url"]
    agora = datetime.now()
    agora_str = agora.strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Checagem de TTL
    status_ant = "vivo"
    falhas_ant = 0
    if estado_anterior:
        status_ant = estado_anterior.get("status", "vivo")
        falhas_ant = estado_anterior.get("falhas", 0)
        ult_cheq_str = estado_anterior.get("ultima_checagem")
        if ult_cheq_str:
            try:
                ult_cheq = datetime.strptime(ult_cheq_str, "%Y-%m-%d %H:%M:%S")
                if agora - ult_cheq < timedelta(hours=TTL_HORAS):
                    return "skip", estado_anterior
            except ValueError:
                pass
                
    # 2. Testa HTTP
    ok, erro_msg, code = testar_url(url)
    
    # Tentativa de fallback para 403/401
    if not ok and code in (401, 403):
        ok, erro_msg, code = testar_url(url, usar_fallback_ua=True)
        if ok:
            log(f"[FALLBACK OK] {url[:60]}...", "OK")
    
    # 3. Define novo status
    novo_estado = {
        "url_key": url_key,
        "ultima_checagem": agora_str,
        "categoria": registro_catalogo.get("categoria", "Outros")
    }
    
    if ok:
        novo_estado["status"] = "vivo"
        novo_estado["falhas"] = 0
        return "vivo", novo_estado
        
    if code in (401, 403):
        # Bloqueio provavel de User-Agent/Geo. Nunca vira "morto".
        novo_estado["status"] = "suspeito"
        novo_estado["falhas"] = falhas_ant  # Mantém contagem
        return "suspeito", novo_estado
        
    # Timeout / 404 / outros erros -> incrementa falha
    novas_falhas = falhas_ant + 1
    novo_estado["falhas"] = novas_falhas
    if novas_falhas >= 2:
        novo_estado["status"] = "morto"
        return "morto", novo_estado
    else:
        novo_estado["status"] = "suspeito"
        return "suspeito", novo_estado

def main():
    parser = argparse.ArgumentParser(description="Revalidador de Links do Catálogo (Sidecar)")
    parser.add_argument("--incluir-ao-vivo", action="store_true", help="Inclui canais ao vivo (costumam dar falso negativo alto)")
    parser.add_argument("--threads", type=int, default=12, help="Número de threads (default: 12)")
    args = parser.parse_args()

    catalogo = carregar_catalogo(args.incluir_ao_vivo)
    if not catalogo:
        return
        
    estado_atual = carregar_mortos()
    
    log(f"Iniciando revalidação de {len(catalogo)} links (Threads: {args.threads})", "INFO")
    
    estatisticas = defaultdict(lambda: {"vivo": 0, "suspeito": 0, "morto": 0, "skip": 0})
    novo_estado_global = dict(estado_atual) # Copia o estado atual
    
    processados = 0
    total_catalogo = len(catalogo)
    
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(processar_item, k, v, estado_atual.get(k)): (k, v) for k, v in catalogo.items()}
        
        for future in as_completed(futures):
            k, reg = futures[future]
            processados += 1
            if processados % 50 == 0:
                log(f"Progresso: {processados}/{total_catalogo}", "INFO")
                
            try:
                acao, estado_item = future.result()
                cat = estado_item.get("categoria", reg.get("categoria", "Outros"))
                estatisticas[cat][acao] += 1
                
                # Atualiza com o novo estado (vivo, morto ou suspeito)
                novo_estado_global[k] = estado_item
                
            except Exception as e:
                log(f"Erro inesperado no link {k[:30]}: {e}", "ERR")
                
    # Limpa do sidecar links que não existem mais no catálogo
    keys_no_catalogo = set(catalogo.keys())
    novo_estado_global = {k: v for k, v in novo_estado_global.items() if k in keys_no_catalogo}
    
    salvar_mortos_atomico(novo_estado_global)
    
    # ---------------- RELATORIO ----------------
    print("\n" + "="*50)
    print("RELATÓRIO DE REVALIDAÇÃO")
    print("="*50)
    
    for cat, stats in estatisticas.items():
        total_cat = sum(stats.values())
        print(f"\nCategoria: {cat} (Total Checado: {total_cat})")
        print(f"  Vivos     : {stats['vivo']} (Nesta checagem)")
        print(f"  Pulos(TTL): {stats['skip']} (Validados nas últimas 24h)")
        print(f"  Suspeitos : {stats['suspeito']} (1 falha ou bloqueio HTTP)")
        print(f"  Mortos    : {stats['morto']} (2 falhas - excluídos da playlist)")
        
        mortos = stats['morto']
        if total_cat > 0:
            taxa = mortos / total_cat
            if taxa > 0.3:
                log(f"  [ALERTA] >30% de links mortos ({taxa:.1%})! O app provavelmente mudou a CDN. Re-extraia o catálogo!", "WARN")

    print("\nConcluído. Sidecar salvo em:", MORTOS_PATH)

if __name__ == "__main__":
    main()
