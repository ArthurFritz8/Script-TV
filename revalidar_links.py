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
import hashlib
import subprocess


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


CACHE_SONDAGEM_PATH = os.path.join(LOG_DIR, "cache_sondagem.json")

def carregar_cache_sondagem():
    if not os.path.exists(CACHE_SONDAGEM_PATH):
        return {}
    try:
        with open(CACHE_SONDAGEM_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def salvar_cache_sondagem(cache):
    try:
        with open(CACHE_SONDAGEM_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except:
        pass

def arquivar_obito(reg_cat, motivo, mortos_cat, catalogo_path):
    TMP_CAT = catalogo_path + ".tmp"
    linhas_catalogo = []
    ukey_alvo = reg_cat.get("url_key")
    arquivados = []
    
    if os.path.exists(catalogo_path):
        with open(catalogo_path, "r", encoding="utf-8") as f:
            for linha in f:
                if not linha.strip(): continue
                try:
                    c = json.loads(linha)
                    if c.get("url_key") == ukey_alvo:
                        c["data_do_obito"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c["motivo"] = motivo
                        c["hash_entrada"] = hashlib.md5(f"{ukey_alvo}_{time.time()}".encode()).hexdigest()
                        arquivados.append(c)
                    else:
                        linhas_catalogo.append(linha)
                except:
                    linhas_catalogo.append(linha)
                    
        with open(TMP_CAT, "w", encoding="utf-8") as f:
            f.writelines(linhas_catalogo)
        os.replace(TMP_CAT, catalogo_path)
        
        with open(mortos_cat, "a", encoding="utf-8") as f:
            for arch in arquivados:
                f.write(json.dumps(arch, ensure_ascii=False) + "\\n")
        print(f"[OBITO] '{reg_cat.get('nome')}' arquivado por falha critica.")

def sondar_url(url, uk, cache_sondagem, do_ffprobe=False):
    """
    Retorna (codigo_logico, nivel_alcancado, detalhes)
    codigo_logico: "vivo", "suspeito", "morto_payload", "infra"
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    # Nivel 0 / 1: HEAD Enriquecido
    req = urllib.request.Request(url, method='HEAD', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            # 302s resolvidos pelo urllib. Pegamos url final
            final_url = resp.url
            status = resp.status
            c_type = resp.headers.get('Content-Type', '').lower()
            c_len = resp.headers.get('Content-Length')
            etag = resp.headers.get('ETag')
            last_mod = resp.headers.get('Last-Modified')
            
            # Se html em url de midia: falha de integridade
            if 'text/html' in c_type and not (url.endswith('.m3u8') or url.endswith('.ts')): 
                return ("morto_payload", 1, "text/html detectado no HEAD")
            
            # Nivel 2: Decisao de usar Range GET
            cache_velho = cache_sondagem.get(uk, {})
            # Se nao for HLS ou AoVivo (que n tem length fixo)
            eh_hls_live = ('/live/' in url.lower() or '.m3u8' in url.lower())
            
            mudou_assinatura = True
            if cache_velho:
                if etag and etag == cache_velho.get("etag"): mudou_assinatura = False
                elif last_mod and last_mod == cache_velho.get("last_mod"): mudou_assinatura = False
                elif c_len and c_len == cache_velho.get("c_len"): mudou_assinatura = False
            
            # Atualiza cache
            cache_sondagem[uk] = {"etag": etag, "last_mod": last_mod, "c_len": c_len}
            
            if not mudou_assinatura and c_len and int(c_len) > 0:
                # Tudo certo, ass. nao mudou
                pass
            else:
                # Nivel 2: Range GET + Sniffing
                req_get = urllib.request.Request(url, method='GET', headers={**headers, "Range": "bytes=0-4095"})
                with urllib.request.urlopen(req_get, timeout=8) as r_get:
                    chunck = r_get.read(4096) # CAP de 4KB rigoroso
                    
                    # Sniffing
                    header_str = chunck[:100].decode('utf-8', errors='ignore').lower()
                    if '<html' in header_str or '<!doctype' in header_str:
                        return ("morto_payload", 2, "HTML de erro no payload")
                        
                    if len(chunck) == 0 and not eh_hls_live:
                        return ("morto_payload", 2, "Zero bytes lidos")
            
            # Nivel 3: FFProbe (Opcional)
            if do_ffprobe:
                try:
                    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", url],
                                       capture_output=True, text=True, timeout=10)
                    if p.returncode != 0:
                        return ("morto_payload", 3, "ffprobe acusou midia invalida")
                except FileNotFoundError:
                    pass
                except subprocess.TimeoutExpired:
                    return ("infra", 3, "ffprobe timeout")
                    
            return ("vivo", 2 if mudou_assinatura else 1, "OK")
                
    except HTTPError as e:
        if e.code in [401, 403]: return ("suspeito", 1, str(e))
        if e.code >= 500: return ("infra", 1, str(e))
        return ("morto_payload", 1, str(e)) # 404
    except (URLError, TimeoutError, OSError) as e:
        return ("infra", 0, str(e))
    except Exception as e:
        return ("infra", 0, str(e))
def processar_item(item, db_entry_existente, cache_sondagem, args):
    url = item.get("url")
    url_key = item.get("url_key")
    cat = item.get("categoria", "Outros")
    
    agora = time.time()
    
    estado = db_entry_existente or {
        "url_key": url_key,
        "categoria": cat,
        "status": "vivo",
        "strikes": 0,
        "falha_integridade": 0,
        "ultima_checagem": 0
    }
    
    if (agora - estado.get("ultima_checagem", 0)) < TTL_SEGUNDOS:
        return (item, estado, False, None, None)
        
    do_ffprobe = False
    if args.verificar and args.verificar.lower() in item.get("nome", "").lower():
        do_ffprobe = True
        
    cod_logico, nivel, detalhe = sondar_url(url, url_key, cache_sondagem, do_ffprobe)
    estado["ultima_checagem"] = agora
    estado["categoria"] = cat
    
    if cod_logico == "vivo":
        estado["status"] = "vivo"
        estado["strikes"] = 0
        estado["falha_integridade"] = 0
    elif cod_logico == "infra" or cod_logico == "suspeito":
        estado["status"] = "suspeito" # mas sem dar strike real
    elif cod_logico == "morto_payload":
        estado["falha_integridade"] = estado.get("falha_integridade", 0) + 1
        estado["status"] = "suspeito" if estado["falha_integridade"] < 3 else "morto"
        
    return (item, estado, True, cod_logico, nivel)

def main():
    parser = argparse.ArgumentParser(description="Revalida links M3U8 do catalogo.")
    parser.add_argument("--incluir-ao-vivo", action="store_true", help="Revalidar Canais_AoVivo tambem (padrao: pular)")
    parser.add_argument("--loop-intervalo", type=int, default=0, help="Minutos para esperar e rodar de novo em loop (padrao: 0 = roda so uma vez)")
    parser.add_argument("--restaurar", type=str, help="Titulo (ou hash/url) da midia a ser restaurada do arquivo de mortos")
    parser.add_argument("--listar-mortos", action="store_true", help="Lista as midias atestadas como mortas")
    parser.add_argument("--verificar", type=str, help="Usa ffprobe na checagem do titulo especificado (Nivel 3)")
    parser.add_argument("--confirmar-obitos", action="store_true", help="Confirma obito pra AoVivo e HLS")
    args = parser.parse_args()
    
    if args.listar_mortos:
        MORTOS_CAT = os.path.join(LOG_DIR, "mortos", "catalogo_mortos.jsonl")
        if not os.path.exists(MORTOS_CAT):
            print("Nenhum obito registrado.")
            return
        print("=== LISTA DE OBITOS (ARQUIVADOS) ===")
        with open(MORTOS_CAT, "r", encoding="utf-8") as f:
            for l in f:
                if not l.strip(): continue
                r = json.loads(l)
                print(f"[{r.get('data_do_obito')}] {r.get('categoria')} - {r.get('nome')} | Motivo: {r.get('motivo')} | Hash: {r.get('hash_entrada')}")
        return
        
    if args.restaurar:
        MORTOS_CAT = os.path.join(LOG_DIR, "mortos", "catalogo_mortos.jsonl")
        TMP_MORTOS = os.path.join(LOG_DIR, "mortos", "catalogo_mortos.tmp.jsonl")
        if not os.path.exists(MORTOS_CAT):
            print("Arquivo de obitos nao encontrado.")
            return
            
        alvo = args.restaurar.lower()
        achou = False
        restantes = []
        restaurados = []
        
        with open(MORTOS_CAT, "r", encoding="utf-8") as f:
            for l in f:
                if not l.strip(): continue
                r = json.loads(l)
                if alvo in r.get("nome", "").lower() or alvo == r.get("hash_entrada"):
                    restaurados.append(r)
                    achou = True
                else:
                    restantes.append(r)
                    
        if achou:
            with open(CATALOGO_PATH, "a", encoding="utf-8") as f:
                for r in restaurados:
                    # Strip obito fields
                    r.pop("data_do_obito", None)
                    r.pop("motivo", None)
                    r.pop("hash_entrada", None)
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    print(f"[RESTAURACAO] '{r.get('nome')}' restaurado ao catalogo.")
            with open(TMP_MORTOS, "w", encoding="utf-8") as f:
                for r in restantes:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(TMP_MORTOS, MORTOS_CAT)
        else:
            print(f"Nenhum obito encontrado correspondente a '{args.restaurar}'.")
        return


    print("Carregando catalogo e base de mortos...")
    catalogo = carregar_catalogo()
    if not catalogo:
        print("Catalogo vazio ou inexistente.")
        return
        
    sidecar_db = carregar_sidecar()
    cache_sondagem = carregar_cache_sondagem()
    
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
