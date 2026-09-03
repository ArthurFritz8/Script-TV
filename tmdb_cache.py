import os
import json
import hashlib
import time
import urllib.request
import urllib.parse
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")
CAPAS_DIR = os.path.join(LOG_DIR, "capas")
CACHE_FILE = os.path.join(LOG_DIR, "tmdb_cache.json")

_API_EXHAUSTED = False
_CACHE_MEM = None

def _carregar_cache():
    global _CACHE_MEM
    if _CACHE_MEM is not None:
        return
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _CACHE_MEM = json.load(f)
        except Exception:
            _CACHE_MEM = {}
    else:
        _CACHE_MEM = {}

def _salvar_cache():
    if _CACHE_MEM is None:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_CACHE_MEM, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def obter_poster_local(nome_base, categoria):
    """
    Busca o poster no TMDB (se tiver API_KEY), baixa para Log/capas/<hash>.jpg 
    e retorna o caminho relativo "capas/<hash>.jpg".
    Retorna None se falhar ou se nao houver chave/rede.
    """
    global _API_EXHAUSTED
    
    if not nome_base or _API_EXHAUSTED:
        return None
        
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return None

    # Gerar hash unico
    hash_key = gerar_hash_chave(nome_base, categoria)
    if not hash_key:
        return None
    
    _carregar_cache()
    
    caminho_relativo = f"capas/{hash_key}.jpg"
    caminho_absoluto = os.path.join(LOG_DIR, "capas", f"{hash_key}.jpg")
    
    # Se ja tentamos buscar e registramos no cache
    if hash_key in _CACHE_MEM:
        if _CACHE_MEM[hash_key].get("poster_path") and os.path.exists(caminho_absoluto):
            return caminho_relativo
        # Se registramos que nao tem poster ou deu erro de imagem, nao tentar de novo
        if _CACHE_MEM[hash_key].get("tentou"):
            return None

    # Se chegou aqui, vamos fazer requisicao (respeitando rate limit visual)
    time.sleep(0.1) 
    
    tipo_busca = "tv" if categoria.lower() == "series" else "movie"
    query_encoded = urllib.parse.quote(nome_limpo)
    url_search = f"https://api.themoviedb.org/3/search/{tipo_busca}?api_key={api_key}&language=pt-BR&query={query_encoded}"
    
    try:
        req = urllib.request.Request(url_search, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
            
        resultados = dados.get("results", [])
        if not resultados:
            _CACHE_MEM[hash_key] = {"tentou": True, "poster_path": None}
            _salvar_cache()
            return None
            
        melhor = resultados[0]
        poster_path = melhor.get("poster_path")
        
        if not poster_path:
            _CACHE_MEM[hash_key] = {"tentou": True, "poster_path": None}
            _salvar_cache()
            return None
            
        # Baixar imagem
        url_imagem = f"https://image.tmdb.org/t/p/w342{poster_path}"
        os.makedirs(CAPAS_DIR, exist_ok=True)
        
        req_img = urllib.request.Request(url_imagem, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_img, timeout=10) as resp_img:
            img_data = resp_img.read()
            
        with open(caminho_absoluto, "wb") as f_img:
            f_img.write(img_data)
            
        # Salvar info do cache
        _CACHE_MEM[hash_key] = {
            "tentou": True, 
            "poster_path": poster_path,
            "id": melhor.get("id"),
            "title": melhor.get("title") or melhor.get("name")
        }
        _salvar_cache()
        return caminho_relativo
        
    except urllib.error.HTTPError as e:
        if e.code == 429: # Rate Limit
            _API_EXHAUSTED = True
        return None
    except Exception:
        # Qualquer outro erro de rede, apenas silenciar e voltar sem capa
        return None

def gerar_hash_chave(nome_base, categoria):
    nome_limpo = (nome_base or "").strip()
    if not nome_limpo:
        return None
    return hashlib.md5(f"{nome_limpo}_{categoria}".lower().encode()).hexdigest()

def resolver_poster_local(nome_base, categoria):
    """
    Funcao READ-ONLY. Resolve o poster apenas no disco/cache.
    Retorna uma tupla (caminho_relativo, title_oficial) ou (None, None).
    NUNCA toca na API.
    """
    hash_key = gerar_hash_chave(nome_base, categoria)
    if not hash_key:
        return None, None
    
    _carregar_cache()
    caminho_absoluto = os.path.join(LOG_DIR, "capas", f"{hash_key}.jpg")
    caminho_relativo = f"capas/{hash_key}.jpg"
    
    if hash_key in _CACHE_MEM:
        info = _CACHE_MEM[hash_key]
        if info.get("poster_path") and os.path.exists(caminho_absoluto):
            return caminho_relativo, info.get("title")
    return None, None
