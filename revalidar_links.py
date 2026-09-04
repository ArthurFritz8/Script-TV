import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")
CATALOGO_PATH = os.path.join(LOG_DIR, "catalogo.jsonl")
MORTOS_PATH = os.path.join(LOG_DIR, "links_mortos.jsonl")
MORTOS_TMP_PATH = os.path.join(LOG_DIR, "links_mortos.tmp.jsonl")

TTL_SEGUNDOS = 24 * 3600  # 24 horas

def carregar_catalogo():
    if not os.path.exists(CATALOGO_PATH):
        return []
    itens = []
    with open(CATALOGO_PATH, "r", encoding="utf-8", errors="replace") as f:
        for linha in f:
            if not linha.strip():
                continue
            try:
                itens.append(json.loads(linha))
            except Exception:
                pass
    return itens

def carregar_sidecar():
    db = {}
    if not os.path.exists(MORTOS_PATH):
        return db
    with open(MORTOS_PATH, "r", encoding="utf-8", errors="replace") as f:
        for linha in f:
            if not linha.strip():
                continue
            try:
                reg = json.loads(linha)
                if "url_key" in reg:
                    db[reg["url_key"]] = reg
            except Exception:
                pass
    return db

def salvar_sidecar_atomico(db):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(MORTOS_TMP_PATH, "w", encoding="utf-8") as f:
        for v in db.values():
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    os.replace(MORTOS_TMP_PATH, MORTOS_PATH)

def checar_url(url):
    """
    Retorna uma tupla (codigo, erro_msg)
    codigo = 200/206 (sucesso), 403/401 (geo/ua), 429/0 (timeout/net), 404 (erro final).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36",
        "Range": "bytes=0-100"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in [200, 206]:
                return (200, "OK")
            return (resp.status, "OK")
    except HTTPError as e:
        return (e.code, str(e))
    except (URLError, TimeoutError, OSError) as e:
        return (0, str(e)) # Erro de rede ou timeout (instabilidade)
    except Exception as e:
        return (0, str(e))

def processar_item(item, db_entry_existente):
    url = item.get("url")
    url_key = item.get("url_key")
    cat = item.get("categoria", "Outros")
    
    agora = time.time()
    
    # Reusa DB se existir
    estado = db_entry_existente or {
        "url_key": url_key,
        "categoria": cat,
        "status": "vivo",
        "strikes": 0,
        "ultima_checagem": 0
    }
    
    # Verifica TTL
    if (agora - estado.get("ultima_checagem", 0)) < TTL_SEGUNDOS:
        # Pula checagem, retorna o estado cacheado
        return (url_key, estado, False) # False = nao checou
        
    codigo, msg = checar_url(url)
    estado["ultima_checagem"] = agora
    estado["categoria"] = cat
    
    if codigo in [200, 206]:
        estado["status"] = "vivo"
        estado["strikes"] = 0
    elif codigo in [401, 403]:
        estado["status"] = "suspeito"
        # Nao incrementa strikes para nao matar por bloqueio regional
    elif codigo == 0 or codigo == 429:
        estado["status"] = "suspeito"
        # Nao incrementa strikes para nao matar por timeout de internet do PC
    else:
        # Outros erros HTTP (404, 500, etc)
        estado["strikes"] += 1
        if estado["strikes"] >= 2:
            estado["status"] = "morto"
        else:
            estado["status"] = "suspeito"
            
    return (url_key, estado, True) # True = checou

def main():
    parser = argparse.ArgumentParser(description="Revalida links M3U8 do catalogo.")
    parser.add_argument("--incluir-ao-vivo", action="store_true", help="Revalidar Canais_AoVivo tambem (padrao: pular)")
    parser.add_argument("--loop-intervalo", type=int, default=0, help="Minutos para esperar e rodar de novo em loop (padrao: 0 = roda so uma vez)")
    args = parser.parse_args()

    print("Carregando catalogo e base de mortos...")
    catalogo = carregar_catalogo()
    if not catalogo:
        print("Catalogo vazio ou inexistente.")
        return
        
    sidecar_db = carregar_sidecar()
    
    itens_para_checar = []
    estatisticas = defaultdict(lambda: {"total": 0, "vivos": 0, "suspeitos": 0, "mortos": 0, "ignorados": 0})
    
    for item in catalogo:
        cat = item.get("categoria", "Outros")
        
        if cat == "Canais_AoVivo" and not args.incluir_ao_vivo:
            estatisticas[cat]["total"] += 1
            estatisticas[cat]["ignorados"] += 1
            continue
            
        itens_para_checar.append(item)
        estatisticas[cat]["total"] += 1
        
    print(f"Total de itens elegiveis para checagem: {len(itens_para_checar)}")
    if not itens_para_checar:
        return

    while True:

        # Execucao multi-thread
        futuros = {}
        novo_sidecar = {}
        checados_agora = 0
    
        print("Iniciando validacao HTTP (isso pode demorar varios minutos)...")
        with ThreadPoolExecutor(max_workers=12) as executor:
            for item in itens_para_checar:
                uk = item.get("url_key")
                f = executor.submit(processar_item, item, sidecar_db.get(uk))
                futuros[f] = item
            
            for f in as_completed(futuros):
                uk, estado, checou_realmente = f.result()
            
                # Se ainda estiver "vivo", nao precisamos manter no sidecar (pra economizar espaco)
                # MAS se quisermos preservar a ultima_checagem, temos que salvar. Vamos salvar todos.
                novo_sidecar[uk] = estado
            
                cat = estado["categoria"]
                if estado["status"] == "vivo":
                    estatisticas[cat]["vivos"] += 1
                elif estado["status"] == "suspeito":
                    estatisticas[cat]["suspeitos"] += 1
                elif estado["status"] == "morto":
                    estatisticas[cat]["mortos"] += 1
                
                if checou_realmente:
                    checados_agora += 1
                    if checados_agora % 50 == 0:
                        print(f"  ... progresso: {checados_agora} requests efetuados")

        print("Salvando sidecar de forma atomica...")
        salvar_sidecar_atomico(novo_sidecar)
    
        print("\n" + "="*50)
        print(" RELATORIO DE REVALIDACAO ")
        print("="*50)
    
        for cat, stats in estatisticas.items():
            print(f"[{cat}] Total: {stats['total']} | Vivos: {stats['vivos']} | Suspeitos: {stats['suspeitos']} | Mortos: {stats['mortos']} | Ignorados: {stats['ignorados']}")
        
            checa_valido = stats['total'] - stats['ignorados']
            if checa_valido > 10 and stats['mortos'] > (checa_valido * 0.3):
                print(f"  -> [ALERTA] Mais de 30% dos links de {cat} confirmados como MORTOS!")
                print(f"  -> [ALERTA] Forte indicio de que o APP trocou de servidor/CDN.")
                print(f"  -> [ALERTA] RECOMENDACAO: Re-extrair este catalogo pelo emulador.")

        print("\nExecucao finalizada com sucesso.")
        if args.loop_intervalo > 0:
            import datetime
            proxima = datetime.datetime.now() + datetime.timedelta(minutes=args.loop_intervalo)
            print(f"\nProxima varredura em {args.loop_intervalo} min ({proxima.strftime('%H:%M')}). Aguardando...")
            time.sleep(args.loop_intervalo * 60)
            
            # Recarregar sidecar para ter certeza que pegamos alteracoes
            sidecar_db = carregar_sidecar()
        else:
            break


if __name__ == "__main__":
    main()
