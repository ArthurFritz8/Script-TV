"""
Gera uma pagina HTML (Log/preview.html) mostrando tudo que foi capturado
JA SEPARADO em pastas/subpastas, so pra visualizar no navegador sem precisar
de um app de IPTV. Usa os mesmos dados do gerar_playlist_final.py.

Uso:
    python gerar_preview_html.py
Depois abra: Log/preview.html
"""
import os
import html
from collections import defaultdict

from gerar_playlist_final import carregar_catalogo, carregar_m3u_legado, ORDEM_CATEGORIAS

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(BASE_DIR, "log")
SAIDA_HTML = os.path.join(LOG_DIR, "preview.html")


def montar_arvore():
    catalogo = carregar_catalogo()
    ja_vistos = set(catalogo.keys())

    todos = list(catalogo.values())
    for categoria in ORDEM_CATEGORIAS:
        todos.extend(carregar_m3u_legado(categoria, ja_vistos))

    # categoria -> grupo -> lista de nomes
    arvore = defaultdict(lambda: defaultdict(list))
    for item in todos:
        categoria = item.get("categoria") or "Outros"
        grupo = item.get("grupo") or categoria
        nome = item.get("nome") or "Desconhecido"
        arvore[categoria][grupo].append(nome)

    return arvore, len(todos)


def main():
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
        f"<h1>Playlist capturada — {total} itens</h1>",
    ]

    for categoria in ORDEM_CATEGORIAS:
        grupos = arvore.get(categoria)
        if not grupos:
            continue
        total_cat = sum(len(v) for v in grupos.values())
        partes.append(f"<h2>{html.escape(categoria)} <span class='contagem'>({total_cat})</span></h2>")
        for grupo in sorted(grupos.keys(), key=str.lower):
            nomes = grupos[grupo]
            partes.append(
                f"<details><summary>{html.escape(grupo)} <span class='contagem'>({len(nomes)})</span></summary><ul>"
            )
            for nome in sorted(nomes, key=str.lower):
                partes.append(f"<li>{html.escape(nome)}</li>")
            partes.append("</ul></details>")

    partes.append("</body></html>")

    with open(SAIDA_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))

    print(f"Preview gerado: {SAIDA_HTML}")
    print(f"Total de itens: {total}")


if __name__ == "__main__":
    main()
