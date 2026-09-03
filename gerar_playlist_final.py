"""
Junta tudo que ja foi capturado (catalogo.jsonl + arquivos .m3u por categoria,
incluindo os antigos sem group-title) numa UNICA playlist M3U pronta pra
importar num app de IPTV (TiviMate, IPTV Smarters, Perfect Player, VLC, etc).

Uso:
    python gerar_playlist_final.py
"""
import os
import re
import json
import argparse
import tmdb_cache
from servir_playlist import descobrir_ip_local
from collections import defaultdict

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
LOG_DIR       = os.path.join(BASE_DIR, "log")
CATALOGO_PATH = os.path.join(LOG_DIR, "catalogo.jsonl")
MORTOS_PATH   = os.path.join(LOG_DIR, "links_mortos.jsonl")
SAIDA_PATH    = os.path.join(LOG_DIR, "playlist_completa.m3u")
CONFLITOS_LOG = os.path.join(LOG_DIR, "conflitos_categorias.log")

ORDEM_CATEGORIAS = ["Canais_AoVivo", "Series", "Filmes", "Infantil", "Outros"]
_RANK_QUALIDADE  = {None: 0, "SD": 1, "HD": 2, "FHD": 3, "4K": 4}

# Prioridade especifica de deduplicação (quando a mesma URL aparece em categorias diferentes).
# Mantemos o de menor valor numérico.
PRIORIDADE_DEDUP = {"Filmes": 1, "Series": 2, "Infantil": 3, "Canais_AoVivo": 4, "Outros": 5}

_RE_EXTINF = re.compile(r'^#EXTINF:-?\d+(?:\s+group-title="([^"]*)")?\s*,(.*)$')
_RE_QUALIDADE_SUFIXO = re.compile(r'\s*\[(4K|FHD|HD|SD)\]$', re.I)


def chave_url(url):
    return url.split("?", 1)[0].split("#", 1)[0].lower()


def nome_normalizado_conflito(item):
    """Retorna o título base (sem marcações de qualidade) para detecção de conflitos de catálogo."""
    n = item.get("nome_base") or item.get("serie") or item.get("nome") or ""
    return _RE_QUALIDADE_SUFIXO.sub('', n).strip().lower()


def carregar_catalogo():
    """Le Log/catalogo.jsonl."""
    itens = {}
    if not os.path.exists(CATALOGO_PATH):
        return itens
    with open(CATALOGO_PATH, encoding="utf-8", errors="replace") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                reg = json.loads(linha)
            except ValueError:
                continue
            ukey = reg.get("url_key") or chave_url(reg["url"])
            reg["url_key"] = ukey
            itens[ukey] = reg
    return itens


def carregar_m3u_legado(categoria, ja_vistos):
    """Le um {Categoria}.m3u antigo e devolve entradas cuja url ainda nao esta no catalogo."""
    caminho = os.path.join(LOG_DIR, f"{categoria}.m3u")
    itens = []
    if not os.path.exists(caminho):
        return itens
    with open(caminho, encoding="utf-8", errors="replace") as f:
        linhas = [l.rstrip("\n") for l in f]
    grupo_atual, nome_atual = None, None
    for linha in linhas:
        if linha.startswith("#EXTINF"):
            m = _RE_EXTINF.match(linha)
            if m:
                grupo_atual = m.group(1)
                nome_atual  = m.group(2).strip()
            else:
                grupo_atual = None
                nome_atual  = linha.rsplit(",", 1)[-1].strip()
        elif linha.startswith("http"):
            chave = chave_url(linha)
            if chave in ja_vistos:
                continue
            itens.append({
                "url": linha, "url_key": chave, "categoria": categoria,
                "grupo": grupo_atual or categoria,
                "nome": nome_atual or "Desconhecido",
            })
            ja_vistos.add(chave)
    return itens


def carregar_mortos():
    """Lê o sidecar de revalidação e retorna um set de chaves (url_key) marcadas como 'morto'."""
    mortos = set()
    if not os.path.exists(MORTOS_PATH):
        return mortos
    with open(MORTOS_PATH, encoding="utf-8", errors="replace") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                reg = json.loads(linha)
                if reg.get("status") == "morto":
                    mortos.add(reg["url_key"])
            except (ValueError, KeyError):
                continue
    return mortos


def chave_ordenacao(item):
    cat_idx = ORDEM_CATEGORIAS.index(item["categoria"]) if item["categoria"] in ORDEM_CATEGORIAS else len(ORDEM_CATEGORIAS)
    grupo = item.get("grupo") or ""
    temporada = item.get("temporada")
    episodio = item.get("episodio")
    # Quando o mesmo titulo/episodio tem varias qualidades salvas, a melhor aparece primeiro.
    rank_q = -_RANK_QUALIDADE.get(item.get("qualidade"), 0)
    if temporada is not None or episodio is not None:
        return (cat_idx, grupo, 0, temporada or 0, episodio or 0, "", rank_q)
    titulo_base = item.get("nome_base") or item.get("nome") or ""
    return (cat_idx, grupo, 1, 0, 0, titulo_base, rank_q)


def gerar_log_conflitos(todos):
    """
    Rastreia se o mesmo titulo (limpo) tem URLs diferentes espalhadas em categorias diferentes.
    Não altera os dados, apenas grava o log de alerta.
    """
    agrupado = defaultdict(list)
    for idx, item in enumerate(todos):
        nome_norm = nome_normalizado_conflito(item)
        if not nome_norm:
            continue
        agrupado[nome_norm].append(item)
        
    com_conflito = 0
    linhas_log = []
    
    for nome_norm, itens in agrupado.items():
        if len(itens) < 2:
            continue
            
        categorias_vistas = set(i.get("categoria", "Outros") for i in itens)
        url_keys_vistas = set(i.get("url_key", "") for i in itens)
        
        # Tem que aparecer em categorias diferentes E com URLs diferentes para ser um "conflito".
        # Se for na mesma categoria, ou se a URL for a mesma, é tratado por outras regras (qualidade ou dedup).
        if len(categorias_vistas) > 1 and len(url_keys_vistas) > 1:
            com_conflito += 1
            linhas_log.append(f"CONFLITO: {itens[0].get('nome_base') or itens[0].get('nome')}")
            for i in itens:
                linhas_log.append(f"  [{i.get('categoria', 'Outros')}] {i.get('url')}")
            linhas_log.append("")
            
    if com_conflito > 0:
        with open(CONFLITOS_LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas_log))
        return com_conflito
    return 0


def main():
    parser = argparse.ArgumentParser(description="Gera playlist consolidada.")
    parser.add_argument("--incluir-mortos", action="store_true", help="Não exclui links marcados como 'morto' pelo revalidador.")
    parser.add_argument("--sincronizar", action="store_true", help="Sincroniza automaticamente a playlist para a nuvem via GitHub Gists.")
    args = parser.parse_args()
    base_url_img = args.base_url.rstrip("/") if args.base_url else f"http://{descobrir_ip_local()}:8765"

    catalogo = carregar_catalogo()
    ja_vistos = set(catalogo.keys())
    mortos = set() if args.incluir_mortos else carregar_mortos()
    
    todos = []
    excluidos_mortos_por_cat = defaultdict(int)

    # 1. Carregar base principal
    for url_key, item in catalogo.items():
        if url_key in mortos:
            excluidos_mortos_por_cat[item.get("categoria", "Outros")] += 1
            continue
        todos.append(item)

    # 2. Carregar legado
    for categoria in ORDEM_CATEGORIAS:
        for item in carregar_m3u_legado(categoria, ja_vistos):
            if item["url_key"] in mortos:
                excluidos_mortos_por_cat[item.get("categoria", "Outros")] += 1
                continue
            todos.append(item)

    # 3. Registrar conflitos cruzados de catálogo ANTES do deduplicador
    conflitos_qnt = gerar_log_conflitos(todos)

    # 4. Deduplicação Transversal (mesma URL em múltiplas categorias)
    agrupado_por_url = defaultdict(list)
    for item in todos:
        agrupado_por_url[item.get("url_key")].append(item)
        
    todos_dedup = []
    dedup_removidos = defaultdict(lambda: defaultdict(int))
    
    for ukey, itens in agrupado_por_url.items():
        # Canais ao vivo não são deduplicados (variantes legítimas podem compartilhar a mesma url base/tokenless)
        if any(i.get("categoria") == "Canais_AoVivo" for i in itens):
            todos_dedup.extend(itens)
            continue
            
        if len(itens) == 1:
            todos_dedup.append(itens[0])
            continue
            
        # Ordena a lista de duplicatas para manter a de melhor ranking.
        # Regra 1: Prioridade da Categoria (Filmes > Series > Infantil > Outros)
        # Regra 2: Melhor qualidade (Rank Qualidade Negativo, pois sorteia crescente)
        itens.sort(key=lambda x: (
            PRIORIDADE_DEDUP.get(x.get("categoria"), 99),
            -_RANK_QUALIDADE.get(x.get("qualidade"), 0)
        ))
        
        # Mantém o vencedor
        vencedor = itens[0]
        todos_dedup.append(vencedor)
        
        # Loga os perdedores
        cat_vencedora = vencedor.get("categoria", "Outros")
        for perdedor in itens[1:]:
            cat_perdedora = perdedor.get("categoria", "Outros")
            dedup_removidos[cat_vencedora][cat_perdedora] += 1

    # 5. Ordenação final para exibição
    todos_dedup.sort(key=chave_ordenacao)

    # 6. Gravar playlist
    with open(SAIDA_PATH, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in todos_dedup:
            grupo = item.get("grupo") or item.get("categoria") or "Outros"
            nome  = item.get("nome") or "Desconhecido"
            categoria = item.get("categoria", "")
            
            extinf = f'#EXTINF:-1 group-title="{grupo}"'
            
            if categoria in ["Filmes", "Series", "Infantil"]:
                caminho_img = tmdb_cache.obter_poster_local(item.get("nome_base") or nome, categoria)
                if caminho_img:
                    extinf += f' tvg-logo="{base_url_img}/{caminho_img}"'
            
            extinf += f',{nome}\n{item["url"]}\n'
            f.write(extinf)

    # 7. Relatórios
    print(f"Playlist final gerada: {SAIDA_PATH}")
    print(f"Total de itens válidos: {len(todos_dedup)}")
    
    if excluidos_mortos_por_cat:
        print("\n[+] Itens MORTOS excluídos (via revalidador):")
        for cat, qtd in excluidos_mortos_por_cat.items():
            print(f"  {cat}: {qtd} itens")
            
    if dedup_removidos:
        print("\n[+] Duplicatas de URL EXATA removidas:")
        for cat_win, perdedoras in dedup_removidos.items():
            for cat_lose, qtd in perdedoras.items():
                print(f"  {qtd} itens (Mantido: {cat_win} / Descartado: {cat_lose})")
                
    if conflitos_qnt > 0:
        print(f"\n[!] Encontrados {conflitos_qnt} títulos em categorias cruzadas com URLs distintas.")
        print(f"    Consulte: {CONFLITOS_LOG}")


    if args.sincronizar:
        import subprocess
        print("\n[+] Sincronizando playlist com a nuvem (GitHub Gists)...")
        subprocess.run(["python", "sincronizar_nuvem.py"], check=False)

if __name__ == "__main__":
    main()
