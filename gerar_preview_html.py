"""
Gera uma pagina HTML (Log/preview.html) com GRID de posters via TMDB.
Atua como ferramenta local de auditoria do catalogo (degradação segura se offline).

Uso:
    python gerar_preview_html.py
Depois abra: Log/preview.html
"""
import os
import html
import json
import time
import hashlib
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError
from collections import defaultdict

from gerar_playlist_final import carregar_catalogo, carregar_m3u_legado, ORDEM_CATEGORIAS

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(BASE_DIR, "log")
SAIDA_HTML = os.path.join(LOG_DIR, "preview.html")

TMDB_CACHE_PATH = os.path.join(LOG_DIR, "tmdb_cache.json")
CAPAS_DIR       = os.path.join(LOG_DIR, "capas")

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

_tmdb_cache_disco = {}


def hash_nome(nome):
    return hashlib.md5(nome.encode('utf-8')).hexdigest()


def montar_arvore():
    catalogo = carregar_catalogo()
    ja_vistos = set(catalogo.keys())

    todos = list(catalogo.values())
    for categoria in ORDEM_CATEGORIAS:
        todos.extend(carregar_m3u_legado(categoria, ja_vistos))

    arvore = defaultdict(lambda: defaultdict(list))
    for item in todos:
        categoria = item.get("categoria") or "Outros"
        grupo = item.get("grupo") or categoria
        arvore[categoria][grupo].append(item)

    return arvore, len(todos)


def carregar_cache():
    global _tmdb_cache_disco
    if os.path.exists(TMDB_CACHE_PATH):
        try:
            with open(TMDB_CACHE_PATH, "r", encoding="utf-8") as f:
                _tmdb_cache_disco = json.load(f)
        except Exception:
            _tmdb_cache_disco = {}
    else:
        _tmdb_cache_disco = {}
    os.makedirs(CAPAS_DIR, exist_ok=True)


def salvar_cache():
    try:
        with open(TMDB_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_tmdb_cache_disco, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Aviso: Erro ao salvar cache TMDB em disco: {e}")


def baixar_poster(poster_path, nome_hash):
    if not poster_path:
        return None
    caminho_local = os.path.join(CAPAS_DIR, f"{nome_hash}.jpg")
    if os.path.exists(caminho_local):
        return f"capas/{nome_hash}.jpg"
        
    url = f"https://image.tmdb.org/t/p/w342{poster_path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            conteudo = resp.read()
            with open(caminho_local, "wb") as f:
                f.write(conteudo)
        return f"capas/{nome_hash}.jpg"
    except Exception as e:
        print(f"  [TMDB] Falha ao baixar poster para {nome_hash}: {e}")
        return None


def consultar_tmdb(nome, tipo="filme"):
    """Consulta TMDB respeitando limites e retorna dict."""
    if not TMDB_API_KEY or not nome or nome == "Desconhecido":
        return None
        
    chave_cache = f"{tipo}_{nome.lower()}"
    if chave_cache in _tmdb_cache_disco:
        # Pula se já tentamos e falhou antes pra não bater toda vez (marcamos com NotFound)
        r = _tmdb_cache_disco[chave_cache]
        return None if r.get("not_found") else r

    endpoint = "tv" if tipo == "serie" else "movie"
    url = (f"https://api.themoviedb.org/3/search/{endpoint}"
           f"?api_key={TMDB_API_KEY}&query={urllib.parse.quote(nome)}&language=pt-BR")
           
    time.sleep(0.2) # Respeita rate limit localmente
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
            
        achados = dados.get("results") or []
        if achados:
            p = achados[0]
            titulo = p.get("title") or p.get("name")
            ano = (p.get("release_date") or p.get("first_air_date") or "")[:4]
            poster_path = p.get("poster_path")
            
            if titulo:
                n_hash = hash_nome(chave_cache)
                caminho_poster_local = baixar_poster(poster_path, n_hash) if poster_path else None
                
                res = {
                    "titulo": titulo,
                    "ano": ano,
                    "poster": caminho_poster_local
                }
                _tmdb_cache_disco[chave_cache] = res
                return res
                
        # Nao encontrou nada, marca pra nao tentar de novo
        _tmdb_cache_disco[chave_cache] = {"not_found": True}
        return None
        
    except HTTPError as e:
        if e.code == 429:
            print("  [TMDB] RATE LIMIT ATINGIDO (429). Interrompendo consultas de rede...")
            raise e
        print(f"  [TMDB] Erro HTTP {e.code}: {nome}")
        return None
    except (URLError, TimeoutError, OSError) as e:
        print("  [TMDB] FALHA DE REDE. Interrompendo novas consultas TMDB para usar apenas cache.")
        raise e
    except Exception as e:
        print(f"  [TMDB] Erro: {e}")
        return None


def get_info_item(item):
    """Extrai informações consolidadas do item do catalogo."""
    cat = item.get("categoria", "Outros")
    nome_cru = item.get("nome", "Desconhecido")
    
    # Extrai qualidade
    qualidade = item.get("qualidade", "")
    badge_q = ""
    if qualidade:
        q_cores = {"4K": "#e53935", "FHD": "#fdd835", "HD": "#43a047", "SD": "#757575"}
        cor = q_cores.get(qualidade, "#757575")
        text_cor = "#000" if qualidade == "FHD" else "#fff"
        badge_q = f"<span style='background:{cor};color:{text_cor};padding:2px 4px;border-radius:4px;font-size:10px;font-weight:bold'>{qualidade}</span>"
        
    # Extrai Temporada/Ep (para exibir)
    ep_info = ""
    temp = item.get("temporada")
    ep = item.get("episodio")
    if temp or ep:
        ep_info = f"<div style='font-size:11px;color:#aaa'>T{temp or '?'} E{ep or '?'}</div>"
        
    # Decide tipo de busca TMDB
    nome_pesquisa = item.get("nome_base") or item.get("serie") or nome_cru
    tipo = "serie" if (cat == "Series" or cat == "Infantil" and (temp or ep)) else "filme"
    
    return cat, nome_pesquisa, tipo, nome_cru, badge_q, ep_info


def gerar_preview_antigo():
    """Fallback literal se não tiver chave TMDB."""
    arvore, total = montar_arvore()
    partes = [
        "<!DOCTYPE html><html lang='pt-br'><head><meta charset='utf-8'>",
        "<title>Preview da Playlist</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;background:#111;color:#eee;padding:20px}",
        "h1{color:#4fc3f7} h2{color:#81c784;margin-bottom:2px}",
        "details{margin:4px 0 4px 12px} summary{cursor:pointer;font-weight:bold;padding:4px}",
        "summary:hover{color:#4fc3f7} ul{margin:4px 0} li{padding:2px 0}",
        ".contagem{color:#999;font-weight:normal}",
        "</style></head><body>",
        f"<h1>Playlist capturada — {total} itens (Modo Texto Clássico)</h1>",
    ]

    for categoria in ORDEM_CATEGORIAS:
        grupos = arvore.get(categoria)
        if not grupos:
            continue
        total_cat = sum(len(v) for v in grupos.values())
        partes.append(f"<h2>{html.escape(categoria)} <span class='contagem'>({total_cat})</span></h2>")
        for grupo in sorted(grupos.keys(), key=str.lower):
            itens = grupos[grupo]
            partes.append(
                f"<details><summary>{html.escape(grupo)} <span class='contagem'>({len(itens)})</span></summary><ul>"
            )
            for item in sorted(itens, key=lambda x: str.lower(x.get("nome", ""))):
                partes.append(f"<li>{html.escape(item.get('nome', ''))}</li>")
            partes.append("</ul></details>")

    partes.append("</body></html>")
    with open(SAIDA_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))
    print(f"Preview (texto) gerado: {SAIDA_HTML}")
    print(f"Total de itens: {total}")


def main():
    if not TMDB_API_KEY:
        print("TMDB_API_KEY não configurada. Usando fallback textual antigo.")
        gerar_preview_antigo()
        return

    arvore, total = montar_arvore()
    carregar_cache()
    
    print(f"Processando TMDB para grid ({total} itens)...")
    
    # CSS para o novo grid de auditoria
    partes = [
        "<!DOCTYPE html><html lang='pt-br'><head><meta charset='utf-8'>",
        "<title>Auditoria de Catálogo</title>",
        "<style>",
        "body{font-family:'Segoe UI',Arial,sans-serif;background:#141414;color:#e5e5e5;padding:20px;margin:0}",
        "h1{color:#e50914} h2{color:#fff;margin:30px 0 10px 0}",
        "details{margin-bottom:20px} summary{cursor:pointer;font-size:18px;font-weight:bold;color:#aaa;outline:none}",
        "summary:hover{color:#fff}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:15px;margin-top:10px;padding:0 10px}",
        ".card{background:#222;border-radius:6px;overflow:hidden;position:relative;display:flex;flex-direction:column;transition:transform 0.2s}",
        ".card:hover{transform:scale(1.05);z-index:2;box-shadow:0 10px 20px rgba(0,0,0,0.5)}",
        ".poster-container{width:100%;aspect-ratio:2/3;background:#333;display:flex;align-items:center;justify-content:center;position:relative}",
        ".poster-container img{width:100%;height:100%;object-fit:cover;display:block}",
        ".placeholder{font-size:60px;font-weight:bold;color:#555}",
        ".info{padding:8px;font-size:13px}",
        ".titulo{font-weight:bold;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#fff}",
        ".ano{color:#999;font-size:11px}",
        ".badges{position:absolute;top:5px;right:5px;display:flex;flex-direction:column;gap:3px;align-items:flex-end}",
        ".badge-cat{position:absolute;top:5px;left:5px;background:rgba(0,0,0,0.7);color:#fff;padding:2px 4px;font-size:10px;border-radius:4px}",
        "</style></head><body>",
        f"<h1>Auditoria de Catálogo — {total} itens</h1>",
    ]

    rede_bloqueada = False

    for categoria in ORDEM_CATEGORIAS:
        grupos = arvore.get(categoria)
        if not grupos:
            continue
            
        total_cat = sum(len(v) for v in grupos.values())
        partes.append(f"<h2>{html.escape(categoria)} ({total_cat})</h2>")
        
        for grupo in sorted(grupos.keys(), key=str.lower):
            itens = grupos[grupo]
            partes.append(f"<details open><summary>{html.escape(grupo)} ({len(itens)})</summary>")
            partes.append("<div class='grid'>")
            
            # Ordena os itens do grupo pelo nome_cru
            for item in sorted(itens, key=lambda x: str.lower(x.get("nome", ""))):
                cat, nome_pesquisa, tipo, nome_cru, badge_q, ep_info = get_info_item(item)
                
                info_tmdb = None
                if cat != "Canais_AoVivo" and not rede_bloqueada:
                    try:
                        info_tmdb = consultar_tmdb(nome_pesquisa, tipo)
                    except (HTTPError, URLError, TimeoutError, OSError):
                        rede_bloqueada = True
                elif cat != "Canais_AoVivo" and rede_bloqueada:
                    # Se rede bloqueou no meio, ainda podemos tentar pegar do cache em disco!
                    chave_c = f"{tipo}_{nome_pesquisa.lower()}"
                    r = _tmdb_cache_disco.get(chave_c)
                    info_tmdb = None if (not r or r.get("not_found")) else r
                
                # Resolução do que exibir no HTML
                if info_tmdb:
                    titulo_exibir = info_tmdb["titulo"]
                    ano_exibir = info_tmdb["ano"]
                    poster = info_tmdb.get("poster")
                else:
                    titulo_exibir = nome_cru
                    ano_exibir = "?"
                    poster = None
                
                # Monta HTML do card
                partes.append("<div class='card'>")
                partes.append("<div class='poster-container'>")
                if poster:
                    partes.append(f"<img src='{poster}' loading='lazy' alt='Poster'>")
                else:
                    inicial = titulo_exibir[0].upper() if titulo_exibir else "?"
                    partes.append(f"<div class='placeholder'>{html.escape(inicial)}</div>")
                    
                # Badges flutuantes
                partes.append(f"<div class='badge-cat'>{html.escape(cat)}</div>")
                if badge_q:
                    partes.append(f"<div class='badges'>{badge_q}</div>")
                partes.append("</div>") # fecha poster-container
                
                # Info inferior
                partes.append("<div class='info'>")
                partes.append(f"<div class='titulo' title=\"{html.escape(titulo_exibir)}\">{html.escape(titulo_exibir)}</div>")
                partes.append(f"<div class='ano'>{ano_exibir}</div>")
                if ep_info:
                    partes.append(ep_info)
                partes.append("</div>") # fecha info
                
                partes.append("</div>") # fecha card
                
            partes.append("</div></details>") # fecha grid e details

    partes.append("</body></html>")
    
    with open(SAIDA_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))
        
    salvar_cache()
    print(f"Grid gerado com sucesso: {SAIDA_HTML}")


if __name__ == "__main__":
    main()
