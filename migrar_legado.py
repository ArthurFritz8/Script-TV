"""
Reprocessa entradas antigas (salvas ANTES do sistema de categorizacao por nome/qualidade)
pelo pipeline atual do robo_extrator.py -- corrige categoria (ex: serie salva como filme),
extrai temporada/episodio, aplica group-title e o controle de melhor-qualidade.

So mexe em arquivos SEM group-title (formato legado). Faz backup (.bak) antes de reescrever.

Uso:
    python migrar_legado.py
"""
import importlib.util
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR  = os.path.join(BASE_DIR, "log")

# Categorias candidatas a migracao (Canais_AoVivo ja usa o formato novo, fica de fora)
ARQUIVOS_LEGADOS = ["Filmes.m3u", "Series.m3u", "Infantil.m3u", "Outros.m3u"]

_RE_EXTINF = re.compile(r'^#EXTINF:-?\d+(?:\s+group-title="[^"]*")?\s*,(.*)$')


def carregar_modulo():
    spec = importlib.util.spec_from_file_location("robo", os.path.join(BASE_DIR, "robo_extrator.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["robo"] = mod
    spec.loader.exec_module(mod)
    return mod


def eh_formato_legado(linhas):
    """So migra se o arquivo NAO tiver nenhuma linha com group-title (ja e formato novo)."""
    return not any('group-title=' in l for l in linhas if l.startswith("#EXTINF"))


def extrair_entradas(caminho):
    with open(caminho, encoding="utf-8", errors="replace") as f:
        linhas = [l.rstrip("\n") for l in f]
    if not eh_formato_legado(linhas):
        return None
    entradas, nome_atual = [], None
    for linha in linhas:
        if linha.startswith("#EXTINF"):
            m = _RE_EXTINF.match(linha)
            nome_atual = m.group(1).strip() if m else linha.rsplit(",", 1)[-1].strip()
        elif linha.startswith("http"):
            entradas.append((nome_atual or "Desconhecido", linha.strip()))
    return entradas


def main():
    mod = carregar_modulo()
    total_lidas, total_salvas, total_recategorizadas = 0, 0, 0
    pendentes = []  # (arquivo_origem, [(nome, url), ...])

    for fname in ARQUIVOS_LEGADOS:
        caminho = os.path.join(LOG_DIR, fname)
        if not os.path.exists(caminho):
            continue
        entradas = extrair_entradas(caminho)
        if entradas is None:
            print(f"  {fname}: ja esta no formato novo, pulando.")
            continue
        if not entradas:
            continue
        pendentes.append((fname, entradas))
        total_lidas += len(entradas)

    if not pendentes:
        print("Nada para migrar (nenhum arquivo legado encontrado).")
        return

    # Backup + zera os arquivos de origem (serao regravados do zero pelo pipeline novo)
    for fname, _ in pendentes:
        caminho = os.path.join(LOG_DIR, fname)
        bak = caminho + ".bak_legado"
        if not os.path.exists(bak):
            os.replace(caminho, bak)
        else:
            os.remove(caminho)
        print(f"  Backup: {fname} -> {os.path.basename(bak)}")

    for fname, entradas in pendentes:
        categoria_origem = fname[:-4]
        for nome, url in entradas:
            categoria_nova = mod.categorizar(url, mod.extrair_nome(url, nome), "")
            if mod.salvar(url, nome_tela=nome, aba=""):
                total_salvas += 1
                if categoria_nova != categoria_origem:
                    total_recategorizadas += 1

    print()
    print(f"Migracao concluida: {total_lidas} entradas lidas, {total_salvas} salvas "
          f"({total_recategorizadas} recategorizadas / qualidade melhor substituiu alguma duplicata).")
    print("Arquivos antigos preservados como *.bak_legado (pode apagar depois de conferir).")


if __name__ == "__main__":
    main()
