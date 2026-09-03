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

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
LOG_DIR       = os.path.join(BASE_DIR, "log")
CATALOGO_PATH = os.path.join(LOG_DIR, "catalogo.jsonl")
SAIDA_PATH    = os.path.join(LOG_DIR, "playlist_completa.m3u")

ORDEM_CATEGORIAS = ["Canais_AoVivo", "Series", "Filmes", "Infantil", "Outros"]
_RANK_QUALIDADE  = {None: 0, "SD": 1, "HD": 2, "FHD": 3, "4K": 4}

_RE_EXTINF = re.compile(r'^#EXTINF:-?\d+(?:\s+group-title="([^"]*)")?\s*,(.*)$')


def chave_url(url):
    return url.split("?", 1)[0].split("#", 1)[0].lower()


def carregar_catalogo():
    """Le Log/catalogo.jsonl (formato novo, ja tem grupo/tipo/temporada/episodio)."""
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
            itens[chave_url(reg["url"])] = reg
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
                "url": linha, "categoria": categoria,
                "grupo": grupo_atual or categoria,
                "nome": nome_atual or "Desconhecido",
            })
            ja_vistos.add(chave)
    return itens


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


def main():
    catalogo = carregar_catalogo()
    ja_vistos = set(catalogo.keys())

    todos = list(catalogo.values())
    for categoria in ORDEM_CATEGORIAS:
        todos.extend(carregar_m3u_legado(categoria, ja_vistos))

    todos.sort(key=chave_ordenacao)

    with open(SAIDA_PATH, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in todos:
            grupo = item.get("grupo") or item.get("categoria") or "Outros"
            nome  = item.get("nome") or "Desconhecido"
            f.write(f'#EXTINF:-1 group-title="{grupo}",{nome}\n{item["url"]}\n')

    print(f"Playlist final gerada: {SAIDA_PATH}")
    print(f"Total de itens: {len(todos)}")


if __name__ == "__main__":
    main()
