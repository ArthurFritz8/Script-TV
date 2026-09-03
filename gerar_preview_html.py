import os
import html
from collections import defaultdict
from gerar_playlist_final import carregar_catalogo, carregar_m3u_legado, ORDEM_CATEGORIAS, chave_ordenacao
import tmdb_cache

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")
SAIDA_HTML = os.path.join(LOG_DIR, "preview.html")

def montar_arvore():
    catalogo = carregar_catalogo()
    ja_vistos = set(catalogo.keys())
    
    todos = []
    for url_key, item in catalogo.items():
        todos.append(item)

    for categoria in ORDEM_CATEGORIAS:
        for item in carregar_m3u_legado(categoria, ja_vistos):
            todos.append(item)

    # Ordenacao rigorosa da playlist final
    todos.sort(key=chave_ordenacao)

    # Agrupa: Categoria -> Grupo -> Lista de itens (ja ordenados)
    arvore = defaultdict(lambda: defaultdict(list))
    for item in todos:
        cat = item.get("categoria", "Outros")
        if cat not in ORDEM_CATEGORIAS:
            cat = "Outros"
        grupo = item.get("grupo") or cat
        arvore[cat][grupo].append(item)

    return arvore, len(todos)


def main():
    try:
        arvore, total = montar_arvore()
    except Exception as e:
        print(f"Erro ao carregar catalogo: {e}")
        return

    print(f"Processando grid de auditoria ({total} itens)...")
    
    # HTML base com CSS "Netflix" read-only
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
        ".info{padding:8px;font-size:13px;flex-grow:1;display:flex;flex-direction:column;justify-content:space-between;}",
        ".titulo{font-weight:bold;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#fff}",
        ".subtitulo{color:#4fc3f7;font-size:11px;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
        ".ano{color:#999;font-size:11px}",
        ".badges{position:absolute;top:5px;right:5px;display:flex;flex-direction:column;gap:3px;align-items:flex-end}",
        ".badge-cat{position:absolute;top:5px;left:5px;background:rgba(0,0,0,0.7);color:#fff;padding:2px 4px;font-size:10px;border-radius:4px}",
        "</style></head><body>",
        f"<h1>Auditoria de Catálogo - {total} itens</h1>",
    ]

    for categoria in ORDEM_CATEGORIAS:
        grupos = arvore.get(categoria)
        if not grupos:
            continue
            
        total_cat = sum(len(v) for v in grupos.values())
        partes.append(f"<h2>{html.escape(categoria)} ({total_cat})</h2>")
        
        for grupo in grupos.keys():
            itens = grupos[grupo]
            partes.append(f"<details open><summary>{html.escape(grupo)} ({len(itens)})</summary>")
            partes.append("<div class='grid'>")
            
            for item in itens:
                nome_cru = item.get("nome", "Desconhecido")
                nome_pesquisa = item.get("nome_base") or item.get("serie") or nome_cru
                qualidade = item.get("qualidade")
                
                # Resolucao READ-ONLY via tmdb_cache (nunca toca API)
                poster_relativo = None
                titulo_oficial = None
                if categoria in ["Filmes", "Series", "Infantil"]:
                    poster_relativo, titulo_oficial = tmdb_cache.resolver_poster_local(nome_pesquisa, categoria)
                
                # Monta HTML do card
                partes.append("<div class='card'>")
                partes.append("<div class='poster-container'>")
                if poster_relativo:
                    # usa URL relativa pra Log/capas/... (como o html ta dentro de Log/, precisamos ajustar)
                    # O SAIDA_HTML e Log/preview.html, e as capas estao em Log/capas/
                    # Entao, 'capas/xyz.jpg' resolve certinho!
                    partes.append(f"<img src='{html.escape(poster_relativo)}' loading='lazy' alt='Poster'>")
                else:
                    inicial = (titulo_oficial or nome_cru)[0].upper() if (titulo_oficial or nome_cru) else "?"
                    partes.append(f"<div class='placeholder'>{html.escape(inicial)}</div>")
                    
                # Badges flutuantes
                partes.append(f"<div class='badge-cat'>{html.escape(categoria)}</div>")
                
                # Badge de qualidade
                if qualidade:
                    cor = {"4K":"#e50914", "FHD":"#f5c518", "HD":"#007bff", "SD":"#6c757d"}.get(qualidade, "#444")
                    text_cor = "#000" if qualidade == "FHD" else "#fff"
                    badge_html = f"<span style='background:{cor};color:{text_cor};padding:2px 4px;border-radius:4px;font-size:10px;font-weight:bold'>{html.escape(qualidade)}</span>"
                    partes.append(f"<div class='badges'>{badge_html}</div>")
                
                partes.append("</div>") # fecha poster-container
                
                # Info inferior
                partes.append("<div class='info'>")
                partes.append(f"<div class='titulo' title=\"{html.escape(nome_cru)}\">{html.escape(nome_cru)}</div>")
                
                if titulo_oficial and titulo_oficial.lower() not in nome_cru.lower():
                    partes.append(f"<div class='subtitulo' title=\"Oficial TMDB: {html.escape(titulo_oficial)}\">TMDB: {html.escape(titulo_oficial)}</div>")
                
                # Temporada e Episodio
                temp = item.get("temporada")
                ep = item.get("episodio")
                if temp or ep:
                    partes.append(f"<div class='ano'>T{temp or '?'} E{ep or '?'}</div>")
                elif item.get("ano"):
                    partes.append(f"<div class='ano'>{item.get('ano')}</div>")
                    
                partes.append("</div>") # fecha info
                partes.append("</div>") # fecha card
                
            partes.append("</div></details>") # fecha grid e details

    partes.append("</body></html>")
    
    with open(SAIDA_HTML, "w", encoding="utf-8") as f:
        f.write("\\n".join(partes))
        
    print(f"Grid gerado com sucesso: {SAIDA_HTML}")

if __name__ == "__main__":
    main()
