#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        ROBO EXTRATOR IPTV  ·  Versão GENIUS 7.1  (Memory Dump Edition)    ║
║                                                                              ║
║  NOVIDADES vs 7.0:                                                          ║
║  ► Navega episodios de series (scroll vertical + horizontal)               ║
║  ► Scroll horizontal em carrosseis de categorias                           ║
║  ► Filtro de nome duplicado corrigido (nao bloqueia series)                ║
║  ► Output profissional com progresso em tempo real                         ║
║  ► Retomada de sessao automatica (carrega .m3u existentes)                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys, io, os, re, json, time, threading, subprocess, urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# PIL (opcional): usado pelo OCR E pelo fingerprint visual (pHash) de cards sem nome.
# Separado do import do pytesseract de proposito -- o pHash so precisa do Pillow (leve,
# instalado via pip), enquanto o OCR precisa TAMBEM do binario externo do Tesseract; sem
# essa separacao, faltar so o Tesseract derrubava os dois recursos a toa.
try:
    from PIL import Image
    PIL_DISPONIVEL = True
except ImportError:
    PIL_DISPONIVEL = False

# OCR (opcional): fallback de leitura de nome quando a acessibilidade nao retorna texto
try:
    import pytesseract
    _TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_TESSERACT_EXE):
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_EXE
    OCR_DISPONIVEL = PIL_DISPONIVEL
except ImportError:
    OCR_DISPONIVEL = False
OCR_METRICAS = {"tentativas": 0, "sucessos": 0}
_TIMEOUTS_AUDIO_SEGUIDOS = 0

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACOES
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
LOG_DIR       = os.path.join(BASE_DIR, "log")
SESSAO_ID     = datetime.now().strftime('%Y%m%d_%H%M%S')
SESSION_LOG   = os.path.join(LOG_DIR, f"sessao_{SESSAO_ID}.txt")
APP_PACKAGE   = "com.android.everycine.mob"
WAIT_PLAY     = 10
WAIT_BACK     = 2
WAIT_NAV      = 1
MAX_SCROLL    = 60
MAX_EP_SCROLL = 30
MAX_SWIPE_LINHA = 8
TELA_W        = 1080
TELA_H        = 1920

MENU_INICIO  = (135,  1840)
MENU_AOVIVO  = (405,  1840)

# API de metadados (opcional): defina a variavel de ambiente TMDB_API_KEY para habilitar
TMDB_API_KEY   = os.environ.get("TMDB_API_KEY", "").strip()
TMDB_DISPONIVEL = bool(TMDB_API_KEY)

os.makedirs(LOG_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════
urls_salvas           = set()
urls_canonicas_salvas = set()
nomes_salvos          = set()
nomes_base_salvos     = set()              # nome BASE (sem qualidade) normalizado -- so p/ pular clique (nunca bloqueia salvar())
qualidades_salvas     = defaultdict(set)   # chave_versao -> {"SD", "HD", ...} ja salvas p/ esse titulo/episodio
lock                  = threading.Lock()
stats                 = defaultdict(int)
_aba_atual            = [""]
_erros_sessao         = []
_tmdb_cache           = {}
_visitados_status     = {}                 # chave (tuple) -> "em_processo" | "concluido"
_phash_registro       = defaultdict(list)  # label -> [hash, hash, ...] ja conhecidos (fingerprint de cards sem nome)
ESTADO_PATH           = os.path.join(LOG_DIR, "estado_visitados.jsonl")
CATALOGO_PATH         = os.path.join(LOG_DIR, "catalogo.jsonl")
CHECKPOINT_PATH       = os.path.join(LOG_DIR, "estado_posicao.json")

_LIMIAR_PHASH     = 5      # distancia de Hamming maxima p/ considerar 2 recortes "o mesmo card"
_CRASH_JANELA_SEG = 600    # janela deslizante p/ contar crashes (10 min)
_CRASH_LIMITE     = 3      # acima disso na janela -> desiste da aba em vez de insistir
_crash_timestamps = []
_checkpoint_atual = {"aba": None, "sub_aba": None, "scroll_n": None, "ts": None}

class AppCrashError(Exception):
    """Sinaliza que o app parece ter caido/travado (watchdog ou dialogo irrecuperavel).
    Nunca deve ser 'engolido' por um except Exception generico no meio do caminho --
    tem que subir ate o loop de retomada (_rodar_aba_resiliente)."""

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════
CORES = {
    "INFO": "", "OK": "\033[92m", "WARN": "\033[93m",
    "ERR": "\033[91m", "NET": "\033[96m", "NAV": "\033[94m", "EP": "\033[95m",
}

def log(msg, nivel="INFO"):
    ts    = datetime.now().strftime("%H:%M:%S")
    linha = f"[{ts}] [{nivel}] {msg}"
    cor   = CORES.get(nivel, "")
    reset = "\033[0m" if cor else ""
    print(f"{cor}{linha}{reset}", flush=True)
    try:
        with open(SESSION_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass
    if nivel == "ERR":
        _erros_sessao.append(f"[{ts}] {msg}")

def progresso():
    total = sum(stats.values())
    partes = [f"{cat}={qtd}" for cat, qtd in sorted(stats.items())]
    return f"Total={total} | {' | '.join(partes)}" if partes else "Total=0"

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORIZACAO E SALVAMENTO
# ══════════════════════════════════════════════════════════════════════════════
def extrair_nome(url, nome_tela=None):
    if nome_tela and nome_tela.strip() not in ("???", "", "Live", "Todos"):
        return nome_tela.strip().title()
    try:
        dec   = urllib.parse.unquote(url).split("?")[0]
        parts = [p for p in dec.split("/") if p]
        ult   = re.sub(r'\.(m3u8|ts|mp4|mkv|avi|flv)$', '', parts[-1], flags=re.I)
        if re.fullmatch(r'[\da-f\-]{6,}', ult.lower()):
            ult = parts[-2] if len(parts) > 1 else ult
        if "index" in ult.lower() and len(parts) > 1:
            ult = parts[-2]
        m = re.search(r's(\d+)e(\d+)', ult, re.I)
        if m and len(parts) > 1:
            serie = parts[-2].replace("_"," ").replace("-"," ").title()
            ep    = m.group(0).upper()
            return f"{serie} - {ep}"
        nome = ult.replace("_"," ").replace("-"," ").strip().title()
        return nome or "Desconhecido"
    except Exception:
        return "Desconhecido"

def categorizar(url, nome="", aba=""):
    u = url.lower()
    a = aba.lower()
    if "ao vivo" in a or any(k in u for k in ["/live/","/hls/","index.m3u8","livefeed"]):
        return "Canais_AoVivo"
    if (re.search(r's\d+e\d+', u) or any(k in u for k in ["series","serie","season","episode"])
            or "series" in a or parece_serie_pelo_nome(nome)):
        return "Series"
    if (any(k in u for k in ["movie","filme","filmes",".mp4",".mkv",".ts"]) or "filme" in a
            or _RE_ANO_FILME.search(nome or "")):
        return "Filmes"
    if "infantil" in a or any(k in u for k in ["kids","child","infantil"]):
        return "Infantil"
    return "Outros"

def chave_url(url):
    return urllib.parse.unquote(url).split("?",1)[0].split("#",1)[0].lower()

def chave_nome_normalizada(nome):
    return re.sub(r'[^a-z0-9]', '', nome.lower())

TIPO_POR_CATEGORIA = {
    "Canais_AoVivo": "canal",
    "Series":        "serie",
    "Filmes":        "filme",
    "Infantil":      "infantil",
    "Outros":        "outro",
}

# ─── Series: extrai temporada/episodio de varios formatos de nome ───
_RE_SXXEXX  = re.compile(r'\bS(\d{1,2})\s*E(\d{1,3})\b', re.I)
_RE_NXM     = re.compile(r'\b(\d{1,2})x(\d{1,3})\b')
_RE_TEMP_EP     = re.compile(r'\bT(?:emporada)?\.?\s*(\d{1,2})\b.{0,15}?\b(?:E|Ep(?:is[oó]dio)?)\.?\s*(\d{1,3})\b', re.I)
_RE_EP          = re.compile(r'\bEp(?:is[oó]dio)?\.?\s*(\d{1,3})\b', re.I)
_RE_NUM_FIM     = re.compile(r'-\s*(\d{1,3})\s*$')
_RE_TEMP_SOZINHA = re.compile(r'\bT(?:emp(?:orada)?)\.?\s*(\d{1,2})\b', re.I)
# Ano entre parenteses no fim do titulo ("Nome do Filme (2026)") -> forte indicio de FILME
_RE_ANO_FILME   = re.compile(r'\((?:19|20)\d{2}\)\s*$')
# Marcador de temporada/episodio em qualquer lugar do nome -> usado p/ achar onde comeca o "lixo" e isolar o titulo puro
_RE_SERIE_TAG   = re.compile(
    r'\b(?:S\d{1,2}\s*E\d{1,3}|\d{1,2}x\d{1,3}|T(?:emp(?:orada)?)\.?\s*\d{1,2}(?:\b.{0,15}?\b(?:E|Ep(?:is[oó]dio)?)\.?\s*\d{1,3})?|Ep(?:is[oó]dio)?\.?\s*\d{1,3})\b',
    re.I,
)

def detectar_temporada_episodio(nome):
    """Suporta S01E02, 1x02, 'Temporada 1 Episodio 2', 'Ep 2', numero solto no fim
    e 'Temporada 4' sozinha (sem episodio, ex: card de selecao de temporada)."""
    for padrao in (_RE_SXXEXX, _RE_NXM, _RE_TEMP_EP):
        m = padrao.search(nome)
        if m:
            return int(m.group(1)), int(m.group(2))
    for padrao in (_RE_EP, _RE_NUM_FIM):
        m = padrao.search(nome)
        if m:
            return None, int(m.group(1))
    m = _RE_TEMP_SOZINHA.search(nome)
    if m:
        return int(m.group(1)), None
    return None, None

def parece_serie_pelo_nome(nome):
    """Sinais fortes de serie no proprio titulo (S01E02, 1x02, 'Temporada N', 'Ep N').
    Nao usa o fallback de 'numero solto no fim' (_RE_NUM_FIM), que e ambiguo demais
    pra decidir categoria sozinho (filmes tambem podem terminar com numero)."""
    if not nome:
        return False
    return any(p.search(nome) for p in (_RE_SXXEXX, _RE_NXM, _RE_TEMP_EP, _RE_EP, _RE_TEMP_SOZINHA))

def nome_base_serie(nome):
    """'Reacher Temp.4' -> 'Reacher' | 'Nome da Serie - Ep 3' -> 'Nome da Serie'
    (remove o marcador de temporada/episodio pra agrupar os episodios da mesma serie)."""
    m = _RE_SERIE_TAG.search(nome)
    if not m:
        return nome.strip()
    base = nome[:m.start()].strip(" -–:")
    return base or nome.strip()

def dividir_serie_episodio(nome):
    """'Nome da Serie - Ep 3' -> ('Nome da Serie', 'Ep 3')."""
    if " - " in nome:
        serie, resto = nome.split(" - ", 1)
        return serie.strip(), resto.strip()
    return nome.strip(), ""

# ─── Canais ao vivo: agrupa praças regionais (Globo SP/RJ/MG...) num so grupo ───
_UFS = ("AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE",
        "PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO")
_RE_UF_SUFIXO = re.compile(r'\s*[-–/]?\s*\(?\b(' + "|".join(_UFS) + r')\)?\.?$', re.I)

def nome_base_canal(nome):
    """'Globo SP' / 'Globo - RJ' -> 'Globo' (agrupa as pracas regionais do mesmo canal)."""
    base = _RE_UF_SUFIXO.sub('', nome).strip()
    return base or nome

# ─── Qualidade: so aparece no nome/URL se o app/CDN informar (nao inventamos nada) ───
_RE_QUALIDADE = re.compile(r'\b(4k|2160p|uhd|1080p|full\s?-?hd|fhd|720p|hd|480p|sd)\b', re.I)
_MAPA_QUALIDADE = {
    "4k": "4K", "2160p": "4K", "uhd": "4K",
    "1080p": "FHD", "fullhd": "FHD", "full-hd": "FHD", "fhd": "FHD",
    "720p": "HD", "hd": "HD",
    "480p": "SD", "sd": "SD",
}

def detectar_qualidade(*textos):
    """Procura marcador de qualidade (4K/HD/SD etc.) no nome ou na URL do item.
    So retorna algo se o proprio app/CDN expuser essa informacao — nao adivinhamos."""
    for texto in textos:
        if not texto:
            continue
        m = _RE_QUALIDADE.search(texto)
        if m:
            return _MAPA_QUALIDADE.get(m.group(1).lower().replace(" ", "").replace("-", ""), m.group(1).upper())
    return None

def limpar_nome_sem_qualidade(nome):
    """Remove a marca de qualidade do titulo (ex: 'Filme X HD' -> 'Filme X') pra que o
    MESMO titulo em qualidades diferentes seja reconhecido como o mesmo item -- a
    qualidade e sempre re-adicionada depois de forma padronizada como sufixo '[HD]'."""
    limpo = _RE_QUALIDADE.sub(' ', nome)
    limpo = re.sub(r'\s{2,}', ' ', limpo).strip(" -–:()")
    return limpo or nome.strip()

def montar_entrada(tipo, cat, nome, url):
    """Decide grupo (equivalente a 'pasta' no M3U) e nome de exibicao final da entrada."""
    qualidade = detectar_qualidade(nome, url)
    sufixo_q  = f" [{qualidade}]" if qualidade else ""

    if tipo == "canal":
        # Canais mantem o nome original: a qualidade normalmente ja faz parte do nome
        # OFICIAL do canal (ex: "HBO POP HD+"), entao so completamos o sufixo se ainda
        # nao estiver visivel — e nao existe "upgrade"/merge de qualidade pra canal
        # (pracas/variantes sao entradas distintas de proposito, ver chave_versao_item).
        ja_no_nome   = bool(qualidade) and qualidade in nome.upper()
        sufixo_canal = "" if ja_no_nome else sufixo_q
        canal_base   = nome_base_canal(nome)
        return canal_base, f"{nome}{sufixo_canal}", {"canal_base": canal_base, "qualidade": qualidade}

    # Para serie/filme/infantil/outro: tira a marca de qualidade do titulo ANTES de
    # comparar/exibir, e sempre re-adiciona ela de forma padronizada como "[HD]" no final.
    # Isso garante que "Filme X HD" e "Filme X SD" sejam reconhecidos como O MESMO titulo
    # (so a qualidade muda) -- essencial pro sistema de upgrade automatico funcionar.
    nome_limpo = limpar_nome_sem_qualidade(nome) if qualidade else nome

    if tipo == "serie":
        temporada, episodio = detectar_temporada_episodio(nome_limpo)
        if episodio is not None and temporada is None:
            temporada = 1
        serie_nome  = nome_base_serie(nome_limpo)
        serie_final = consultar_tmdb(serie_nome, "serie") or serie_nome
        if temporada is not None and episodio is not None:
            nome_exibicao = f"{serie_final} S{temporada:02d}E{episodio:02d}{sufixo_q}"
        elif temporada is not None:
            nome_exibicao = f"{serie_final} T{temporada:02d}{sufixo_q}"
        else:
            _, rotulo_ep = dividir_serie_episodio(nome_limpo)
            nome_exibicao = f"{serie_final} - {rotulo_ep}{sufixo_q}" if rotulo_ep else f"{serie_final}{sufixo_q}"
        meta = {"serie": serie_final, "temporada": temporada, "episodio": episodio, "qualidade": qualidade}
        return serie_final, nome_exibicao, meta

    nome_base     = consultar_tmdb(nome_limpo, "filme") or nome_limpo
    nome_exibicao = nome_base + sufixo_q
    grupo = {"filme": "Filmes", "infantil": "Infantil", "outro": "Outros"}.get(tipo, cat)
    return grupo, nome_exibicao, {"qualidade": qualidade, "nome_base": nome_base}

def consultar_tmdb(nome, tipo="filme"):
    """Normaliza o titulo via TMDB (cache em memoria); retorna None se indisponivel ou sem match."""
    if not TMDB_DISPONIVEL or not nome or nome == "Desconhecido":
        return None
    chave_cache = (tipo, nome.lower())
    if chave_cache in _tmdb_cache:
        return _tmdb_cache[chave_cache]
    endpoint = "tv" if tipo == "serie" else "movie"
    url = (f"https://api.themoviedb.org/3/search/{endpoint}"
           f"?api_key={TMDB_API_KEY}&query={urllib.parse.quote(nome)}&language=pt-BR")
    resultado = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        achados = dados.get("results") or []
        if achados:
            titulo = achados[0].get("title") or achados[0].get("name")
            ano = (achados[0].get("release_date") or achados[0].get("first_air_date") or "")[:4]
            if titulo:
                resultado = f"{titulo} ({ano})" if ano else titulo
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        log(f"  [TMDB] Falha na consulta: {e}", "WARN")
        resultado = None
    _tmdb_cache[chave_cache] = resultado
    return resultado

def gravar_m3u(cat, grupo, nome_exibicao, url):
    arq  = os.path.join(LOG_DIR, f"{cat}.m3u")
    novo = not os.path.exists(arq)
    with open(arq, "a", encoding="utf-8") as f:
        if novo:
            f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 group-title="{grupo}",{nome_exibicao}\n{url}\n')

def gravar_catalogo(url, url_key, tipo, cat, grupo, nome_exibicao, meta, aba):
    """Registro estruturado (fonte da verdade) usado para gerar/remontar playlists depois."""
    registro = {
        "url": url, "url_key": url_key, "tipo": tipo, "categoria": cat,
        "grupo": grupo, "nome": nome_exibicao, "aba": aba,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    registro.update(meta)
    with open(CATALOGO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")

def chave_versao_item(tipo, meta, nome_exibicao):
    """Identidade de um titulo/episodio SEM a qualidade -- usada pra saber se duas capturas
    sao 'a mesma coisa' independente da qualidade (ex: mesmo filme em SD e em HD).
    Canais nao entram nesse controle: pracas/variantes de canal sao entradas distintas de proposito."""
    if tipo == "canal":
        return None
    if tipo == "serie":
        return ("serie", chave_nome_normalizada(meta.get("serie") or ""), meta.get("temporada"), meta.get("episodio"))
    return (tipo, chave_nome_normalizada(meta.get("nome_base") or nome_exibicao))

def salvar(url, nome_tela=None, aba=""):
    with lock:
        url_key = chave_url(url)
        if url in urls_salvas or url_key in urls_canonicas_salvas:
            return False
        nome = extrair_nome(url, nome_tela)
        cat  = categorizar(url, nome, aba)
        tipo = TIPO_POR_CATEGORIA.get(cat, "outro")

        grupo, nome_exibicao, meta = montar_entrada(tipo, cat, nome, url)

        # --- Controle de qualidade: guarda TODAS as qualidades distintas de cada titulo/episodio
        # (nem todo mundo consegue assistir em HD/4K) -- so bloqueia se essa MESMA qualidade
        # do MESMO titulo ja tiver sido salva antes (duplicata de verdade).
        chave_versao = chave_versao_item(tipo, meta, nome_exibicao)
        qualidade    = meta.get("qualidade")
        if chave_versao is not None and qualidade in qualidades_salvas.get(chave_versao, ()):
            log(f"  [QUALIDADE] Essa qualidade ja foi salva antes: {nome_exibicao}", "WARN")
            return False

        chave_nome = chave_nome_normalizada(nome_exibicao)
        # Apenas bloqueia por nome se for nome longo e especifico (evita bloquear series)
        if len(chave_nome) >= 8 and chave_nome in nomes_salvos:
            log(f"  [DUP] Nome ja salvo: {nome_exibicao}", "WARN")
            return False

        gravar_m3u(cat, grupo, nome_exibicao, url)
        gravar_catalogo(url, url_key, tipo, cat, grupo, nome_exibicao, meta, aba)

        urls_salvas.add(url)
        urls_canonicas_salvas.add(url_key)
        if len(chave_nome) >= 3:
            nomes_salvos.add(chave_nome)
        if chave_versao is not None:
            qualidades_salvas[chave_versao].add(qualidade)
        # Nome BASE (sem qualidade) -- permite pular clique em cards repetidos entre
        # sub-abas da mesma categoria (ex: mesmo filme em "Acao" e "Lancamentos"). So
        # p/ Filme/Infantil/Outro (series podem ganhar episodios novos, canais sao
        # sempre entradas distintas de proposito) e NUNCA usado p/ bloquear salvar().
        if tipo in ("filme", "infantil", "outro"):
            base_key = chave_nome_normalizada(meta.get("nome_base") or nome_exibicao)
            if len(base_key) >= 8:
                nomes_base_salvos.add(base_key)
        stats[cat] += 1
        total = sum(stats.values())
        log(f"  SALVO [{cat}] [{total:>4}] {nome_exibicao}", "OK")
        return True

def carregar_playlists_existentes():
    carregados = 0
    for fname in os.listdir(LOG_DIR):
        if not fname.endswith(".m3u"):
            continue
        fpath = os.path.join(LOG_DIR, fname)
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                linhas = [linha.strip() for linha in f]
        except OSError:
            continue
        for linha in linhas:
            if linha.startswith("#EXTINF"):
                nome = linha.rsplit(",",1)[-1].strip()
                chave_nome = chave_nome_normalizada(nome)
                if len(chave_nome) >= 8:
                    nomes_salvos.add(chave_nome)
            elif linha.startswith("http"):
                urls_salvas.add(linha)
                urls_canonicas_salvas.add(chave_url(linha))
                carregados += 1
    if carregados:
        log(f"  Retomando sessao: {carregados} URLs ja capturadas", "INFO")

def carregar_qualidades_salvas():
    """Reconstroi, a partir do catalogo.jsonl (fonte da verdade), quais qualidades ja
    foram salvas de cada titulo/episodio -- necessario pra nao duplicar a mesma
    qualidade de novo em sessoes futuras (mas continuar aceitando qualidades novas)."""
    if not os.path.exists(CATALOGO_PATH):
        return
    try:
        with open(CATALOGO_PATH, encoding="utf-8", errors="replace") as f:
            linhas = f.readlines()
    except OSError:
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except ValueError:
            continue
        chave_versao = chave_versao_item(reg.get("tipo"), reg, reg.get("nome") or "")
        if chave_versao is None:
            continue
        qualidades_salvas[chave_versao].add(reg.get("qualidade"))
    if qualidades_salvas:
        log(f"  Qualidade: {len(qualidades_salvas)} titulos/episodios com versao(oes) registrada(s)", "INFO")

def carregar_estado_visitados():
    """Carrega o ciclo de vida dos itens de sessoes anteriores (resume real, sobrevive a
    reinicios/crash). Cada linha pode ser uma lista simples (formato antigo, sempre
    equivale a 'concluido') ou um objeto {"chave":[...], "status":...} (formato novo);
    o arquivo e append-only, entao a ULTIMA ocorrencia de cada chave manda no status."""
    if not os.path.exists(ESTADO_PATH):
        return
    try:
        with open(ESTADO_PATH, encoding="utf-8", errors="replace") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    dado = json.loads(linha)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if isinstance(dado, list):
                    chave, status = tuple(dado), "concluido"
                elif isinstance(dado, dict) and "chave" in dado:
                    chave, status = tuple(dado["chave"]), dado.get("status", "concluido")
                else:
                    continue
                _visitados_status[chave] = status
    except OSError as e:
        log(f"  Falha ao carregar estado de visitados: {e}", "WARN")
        return
    pendentes = 0
    for chave, status in _visitados_status.items():
        if status == "em_processo":
            pendentes += 1
        if len(chave) == 4 and chave[0] == "card" and chave[1] == "phash":
            _phash_registro[chave[2]].append(chave[3])
    if _visitados_status:
        log(f"  Estado anterior: {len(_visitados_status)} itens registrados", "INFO")
    if pendentes:
        log(f"  {pendentes} item(ns) ficaram 'em_processo' num crash anterior -- serao re-processados.", "WARN")

def foi_visitado(chave):
    return _visitados_status.get(chave) == "concluido"

def _gravar_estado(chave, status):
    _visitados_status[chave] = status
    try:
        with open(ESTADO_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"chave": list(chave), "status": status}, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"  Falha ao gravar estado de visitados: {e}", "WARN")

def marcar_em_processo(chave):
    """Grava ANTES de clicar/abrir o item -- se o app crashar no meio, na retomada esse
    item NAO fica marcado como concluido, entao volta a ser tentado (nunca perde link)."""
    _gravar_estado(chave, "em_processo")

def marcar_concluido(chave):
    """Grava DEPOIS que o item terminou de ser processado -- so a partir daqui ele e
    pulado nas proximas sessoes/tentativas."""
    _gravar_estado(chave, "concluido")

# ══════════════════════════════════════════════════════════════════════════════
#  ADB HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def adb_run(args, timeout=15):
    try:
        r = subprocess.run(["adb","shell"]+args, capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        if r.returncode != 0 and r.stderr.strip():
            log(f"  [ADB] '{' '.join(args)}' -> {r.stderr.strip()[:120]}", "WARN")
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        log(f"  [ADB] Timeout em '{' '.join(args)}'", "WARN")
        return ""
    except Exception as e:
        log(f"  [ADB] Falha: {e}", "WARN")
        return ""

def adb_su(command, timeout=15):
    cmd = f'su -c "{command}"'
    try:
        return subprocess.run(["adb","shell",cmd], capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        class R:
            returncode=1; stdout=""; stderr="timeout"
        return R()

def tap(x, y, delay=WAIT_NAV):
    adb_run(["input","tap",str(int(x)),str(int(y))])
    _invalidar_cache_tela()
    time.sleep(delay)

def back(delay=WAIT_BACK):
    adb_run(["input","keyevent","4"])
    _invalidar_cache_tela()
    time.sleep(delay)

def swipe_up(dist=700, dur=350):
    cx = TELA_W // 2; cy = TELA_H // 2
    adb_run(["input","swipe",str(cx),str(cy+dist//2),str(cx),str(cy-dist//2),str(dur)])
    _invalidar_cache_tela()
    time.sleep(0.9)

def swipe_left(dist=600, dur=300, y=None):
    if y is None: y = TELA_H // 3
    x_ini = TELA_W * 3 // 4; x_fim = TELA_W // 4
    adb_run(["input","swipe",str(x_ini),str(y),str(x_fim),str(y),str(dur)])
    _invalidar_cache_tela()
    time.sleep(0.8)

_ui_cache     = {"xml": "", "ts": 0.0}
_UI_CACHE_TTL = 1.5

def _invalidar_cache_tela():
    _ui_cache["ts"] = 0.0

def get_ui_xml(forcar=False):
    """Dump da arvore de UI, com cache curto (TTL) pra nao re-dumpar a MESMA tela varias
    vezes seguidas (cada dump custa 2 idas ao ADB: uiautomator dump + cat). Qualquer
    tap/swipe invalida o cache na hora, entao nunca ha risco de ler uma tela desatualizada."""
    agora = time.time()
    if not forcar and _ui_cache["xml"] and (agora - _ui_cache["ts"]) < _UI_CACHE_TTL:
        return _ui_cache["xml"]
    adb_run(["uiautomator","dump","/sdcard/ui.xml"])
    try:
        r = subprocess.run(["adb","shell","cat","/sdcard/ui.xml"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=12)
        xml = r.stdout
    except subprocess.TimeoutExpired:
        log("  [ADB] Timeout lendo ui.xml", "WARN")
        xml = ""
    _ui_cache["xml"], _ui_cache["ts"] = xml, agora
    return xml

def app_esta_saudavel():
    """Checagem barata (2 comandos ADB curtos) de que o app ainda esta vivo e em
    primeiro plano. Chamada nos pontos de maior risco: antes de abrir um item novo e
    logo apos cada memory dump (o dumpheap pode derrubar o app por pressao de memoria)."""
    pid = adb_run(["pidof", APP_PACKAGE])
    if not pid.strip():
        return False
    foco = adb_run(["dumpsys", "window", "|", "grep", "mCurrentFocus"])
    return APP_PACKAGE in foco

def app_saudavel_ou_recuperado():
    """Antes de declarar crash de vez: confirma que o app esta vivo/em foco; se nao
    estiver, tenta primeiro fechar um dialogo de erro/ANR (nem sempre e crash de verdade)."""
    if app_esta_saudavel():
        return True
    if tentar_lidar_com_dialogo() and app_esta_saudavel():
        return True
    return False

def parse_xml(xml_str):
    try:
        return ET.fromstring(xml_str)
    except ET.ParseError:
        return None

def bounds_coords(bounds_str):
    try:
        return list(map(int, re.findall(r'\d+', bounds_str)))
    except Exception:
        return []

def bounds_centro(bounds_str):
    n = bounds_coords(bounds_str)
    if len(n) < 4:
        return None, None
    return (n[0]+n[2])//2, (n[1]+n[3])//2

def bounds_area(coords):
    if len(coords) < 4:
        return 0
    return (coords[2]-coords[0]) * (coords[3]-coords[1])

def capturar_screenshot_recorte(bounds_str, img_tela=None):
    """Recorta a area do node a partir de um screenshot ja capturado (compartilhado entre
    varios cards da mesma leitura de tela); se nenhum for passado, tira um novo sozinho
    (comportamento antigo, mantido p/ quem ainda chama isolado)."""
    if img_tela is None:
        img_tela = tirar_screenshot()
    return _recortar(img_tela, bounds_str)

def tirar_screenshot():
    """Um unico screencap da tela atual -- compartilhado entre OCR e fingerprint visual
    (pHash) de TODOS os cards dessa leitura, em vez de um screencap por card."""
    if not PIL_DISPONIVEL:
        return None
    try:
        r = subprocess.run(["adb","exec-out","screencap","-p"], capture_output=True, timeout=15)
        if r.returncode != 0 or not r.stdout:
            return None
        return Image.open(io.BytesIO(r.stdout))
    except Exception:
        return None

def _recortar(img, bounds_str):
    if img is None:
        return None
    coords = bounds_coords(bounds_str)
    if len(coords) < 4:
        return None
    try:
        return img.crop((coords[0], coords[1], coords[2], coords[3]))
    except Exception:
        return None

def ler_nome_por_ocr(bounds_str, img_tela=None):
    """Fallback: le o nome via OCR na imagem quando a acessibilidade nao retorna texto."""
    if not OCR_DISPONIVEL or not bounds_str:
        return ""
    img = capturar_screenshot_recorte(bounds_str, img_tela)
    if img is None:
        return ""
    try:
        texto = pytesseract.image_to_string(img, lang="por+eng").strip()
        texto = re.sub(r'\s+', ' ', texto)
        return texto[:80]
    except Exception as e:
        log(f"  [OCR] Falha ao ler imagem: {e}", "WARN")
        return ""

def _phash_imagem(img, tamanho=8):
    """Hash perceptual simples (aHash): reduz o recorte a tamanho x tamanho em escala de
    cinza e marca 1 bit por pixel (acima/abaixo da media) -- suficiente pra saber se dois
    recortes de tela sao 'visualmente o mesmo card' sem precisar de nada alem do Pillow."""
    resample = getattr(Image, "Resampling", Image).LANCZOS
    pequena  = img.convert("L").resize((tamanho, tamanho), resample)
    pixels   = list(pequena.getdata())
    media   = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= media else 0)
    return bits

def _hamming(a, b):
    return bin(a ^ b).count("1")

def _phash_equivalente(label, novo_hash):
    for h in _phash_registro[label]:
        if _hamming(novo_hash, h) <= _LIMIAR_PHASH:
            return h
    return None

def chave_fingerprint_card(label, card, img_tela, scroll_n):
    """Chave estavel pra cards SEM nome confiavel: usa hash perceptual do recorte visual
    (estavel entre posicoes de scroll) em vez de bounds+scroll_n (que mudam a cada rolagem
    e faziam o mesmo card sem texto 'reaparecer como novo' -- causa raiz de clique
    duplicado em cards sem nome). Cai pro fallback antigo se o Pillow nao estiver
    disponivel ou der qualquer erro (sem regressao nesse caso)."""
    try:
        recorte = _recortar(img_tela, card["bounds"])
        if recorte is not None:
            novo_hash  = _phash_imagem(recorte)
            existente  = _phash_equivalente(label, novo_hash)
            hash_final = existente if existente is not None else novo_hash
            if existente is None:
                _phash_registro[label].append(novo_hash)
            return ("card", "phash", label, hash_final)
    except Exception as e:
        log(f"  [PHASH] Falha ao gerar fingerprint: {e}", "WARN")
    return ("card", label, scroll_n, card["bounds"])

def encontrar_no(root, texto=None, res_id=None):
    if root is None:
        return None
    for node in root.iter("node"):
        if node.get("clickable") != "true":
            continue
        if texto and texto.lower() not in (node.get("text") or "").lower():
            continue
        if res_id and res_id not in (node.get("resource-id") or ""):
            continue
        return node
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  MEMORY DUMP
# ══════════════════════════════════════════════════════════════════════════════
def test_url(url):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'ExoPlayerDemo/2.11.8 (Linux;Android 9) ExoPlayerLib/2.11.8',
            'Range': 'bytes=0-100'
        })
        with urllib.request.urlopen(req, timeout=5) as res:
            ct = res.info().get('Content-Type','')
            if any(k in ct.lower() for k in ['video','mpegurl','mp2t','octet-stream']):
                return True, ct
    except HTTPError as e:
        if e.code == 206:
            return True, e.headers.get('Content-Type','')
    except Exception:
        pass
    return False, ""

RE_PROXY_LOCAL = re.compile(r'^https?://127\.0\.0\.1:\d+/(.+)$', re.IGNORECASE)

def desembrulhar_proxy_local(url):
    m = RE_PROXY_LOCAL.match(url)
    if not m:
        return url
    interno = m.group(1)
    if interno.lower().startswith(('http%3a','https%3a')):
        interno = urllib.parse.unquote(interno)
    if interno.lower().startswith(('http://','https://')):
        return interno
    return url

def normalizar_url_heap(decoded):
    decoded = decoded.split('!',1)[0]
    decoded = desembrulhar_proxy_local(decoded)
    if any(x in decoded for x in ['.png','.jpg','.xml','facebook','umeng','api','crash','.css','.js','analytics']):
        return None
    if decoded.lower().startswith('http://127.0.0.1'):
        return None
    clean_url = decoded.rstrip("!#',)")
    if len(clean_url) < 30:
        return None
    lower = clean_url.lower()
    is_cdn    = any(k in lower for k in ['cdn','xhuui','media','cloudfront','.m3u8','.mp4','.ts','.mkv'])
    is_google = 'google' in lower and any(k in lower for k in ['video','picasa','drive','googlevideo'])
    if not (is_cdn or is_google):
        return None
    return clean_url

def score_url_candidata(url):
    lower = url.lower()
    score = 0
    if 'google' in lower:  score += 100
    if '.m3u8' in lower:   score += 90
    elif '.mp4' in lower:  score += 80
    elif '.mkv' in lower:  score += 70
    elif '.ts' in lower:   score += 10
    if any(k in lower for k in ['cdn','xhuui','media','cloudfront']): score += 10
    return score

def ordenar_urls_candidatas(urls):
    return sorted(urls, key=lambda u: (score_url_candidata(u), len(u)), reverse=True)

def candidato_duplicado(url, nome_tela=None):
    nome = extrair_nome(url, nome_tela)
    nome_key = chave_nome_normalizada(nome)
    return (
        url in urls_salvas
        or chave_url(url) in urls_canonicas_salvas
        or (len(nome_key) >= 8 and nome_key in nomes_salvos)
    )

def iter_urls_heap(path, chunk_size=4*1024*1024, overlap=8192):
    pattern = re.compile(rb"http[s]?://[^\s\x00\"'<>]+")
    tail = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                for match in pattern.findall(tail):
                    yield match
                break
            data = tail + chunk
            cutoff = max(0, len(data) - overlap)
            for match in pattern.finditer(data):
                if match.end() <= cutoff:
                    yield match.group(0)
            tail = data[cutoff:]

def tamanho_arquivo_remoto(path):
    try:
        r = adb_su(f"stat -c %s {path} 2>/dev/null || echo 0", timeout=10)
        return int((r.stdout.strip().splitlines() or ["0"])[-1])
    except Exception:
        return 0

def aguardar_dump_pronto(path, timeout=45, intervalo=1.0):
    deadline = time.time() + timeout
    ultimo = -1; repeticoes = 0
    while time.time() < deadline:
        tam = tamanho_arquivo_remoto(path)
        if tam > 0 and tam == ultimo:
            repeticoes += 1
            if repeticoes >= 2:
                return tam
        else:
            repeticoes = 0
        ultimo = tam
        time.sleep(intervalo)
    return max(ultimo, 0)

def _snapshot_audio():
    try:
        r = subprocess.run(["adb","shell","dumpsys","audio"], capture_output=True, text=True, timeout=8)
        return r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""

def aguardar_audio_iniciar(pid, timeout, intervalo=0.6):
    baseline = set(_snapshot_audio().splitlines())
    padrao_novo = re.compile(rf'new player piid:(\d+) uid/pid:\d+/{pid}\b')
    deadline = time.time() + timeout
    while time.time() < deadline:
        atual = _snapshot_audio()
        novas = "\n".join(l for l in atual.splitlines() if l not in baseline)
        for piid in padrao_novo.findall(novas):
            if re.search(rf'player piid:{piid} state:started', novas):
                return True
        time.sleep(intervalo)
    return False

def extrair_link_memoria(nome_tela, aba="", _tentativa=1):
    try:
        r = subprocess.run(["adb","shell","pidof",APP_PACKAGE],
                           capture_output=True, text=True, timeout=10)
        pid = r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"  [ERRO] Falha PID: {e}", "ERR")
        return False
    if not pid:
        log("  [ERRO] App nao esta rodando!", "ERR")
        return False

    limite = WAIT_PLAY if _tentativa == 1 else 6
    t0 = time.time()
    if aguardar_audio_iniciar(pid, timeout=limite):
        log(f"  [MEM] Audio detectado em {time.time()-t0:.1f}s", "NET")
        time.sleep(1.5)
    else:
        log(f"  [MEM] Sem audio em {limite}s, prosseguindo...", "WARN")

    remoto = "/data/local/tmp/heap.prof"
    adb_su(f"rm -f {remoto}")
    r_dump = adb_su(f"am dumpheap {pid} {remoto}", timeout=35)
    dump_msg = (r_dump.stdout + r_dump.stderr).strip()
    if r_dump.returncode != 0 or any(k in dump_msg.lower() for k in ["denied","not allowed","error"]):
        log(f"  [ERRO] dumpheap falhou: {dump_msg[:180]}", "ERR")
        return False

    # dumpheap pode derrubar o app por pressao de memoria -- checagem barata logo apos,
    # ANTES de gastar tempo puxando/varrendo um dump de um app que ja caiu.
    if not app_saudavel_ou_recuperado():
        raise AppCrashError(f"App nao respondia logo apos o memory dump (item: {nome_tela})")

    tam_remoto = aguardar_dump_pronto(remoto)
    if tam_remoto <= 0:
        log("  [ERRO] dumpheap arquivo vazio", "ERR")
        return False

    adb_su(f"chmod 777 {remoto}")
    dump_local = os.path.join(LOG_DIR, "heap.prof")
    try:
        r_pull = subprocess.run(["adb","pull",remoto,dump_local],
                                capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"  [ERRO] adb pull travou: {e}", "ERR")
        return False
    if r_pull.returncode != 0:
        log(f"  [ERRO] adb pull falhou: {r_pull.stderr.strip()[:150]}", "ERR")
        return False

    if not os.path.exists(dump_local) or os.path.getsize(dump_local) <= 0:
        log("  [ERRO] Dump local vazio", "ERR")
        return False

    tam_mb = os.path.getsize(dump_local) / (1024*1024)
    log(f"  [MEM] Varrendo {tam_mb:.1f}MB de RAM...", "NET")
    urls_encontradas = set()
    try:
        for match in iter_urls_heap(dump_local):
            try:
                clean = normalizar_url_heap(match.decode('utf-8'))
                if clean:
                    urls_encontradas.add(clean)
            except UnicodeDecodeError:
                pass
    except Exception as e:
        log(f"  [ERRO] Leitura dump: {e}", "ERR")

    try:
        os.remove(dump_local)
        adb_su(f"rm -f {remoto}")
    except OSError:
        pass

    if not urls_encontradas:
        if _tentativa < 2:
            log("  [MEM] Nenhum link ainda, re-tentando...", "WARN")
            return extrair_link_memoria(nome_tela, aba, _tentativa=2)
        log("  [MEM] Nenhum link de video encontrado.", "WARN")
        return False

    urls_ordenadas = ordenar_urls_candidatas(urls_encontradas)
    log(f"  [MEM] {len(urls_ordenadas)} candidatos. Validando...", "INFO")

    for url in urls_ordenadas:
        if 'google' in url.lower():
            log("  [GOOGLE] Link web detectado!", "OK")
            if salvar(url, nome_tela, aba):
                return True

    for url in urls_ordenadas:
        if candidato_duplicado(url, nome_tela):
            continue
        is_media, ctype = test_url(url)
        if is_media:
            log(f"  [OK] Validado! Tipo: {ctype}", "NET")
            if salvar(url, nome_tela, aba):
                return True

    for url in urls_ordenadas:
        if candidato_duplicado(url, nome_tela):
            continue
        log("  [FALLBACK] Salvando sem validacao HTTP", "WARN")
        if salvar(url, nome_tela, aba):
            return True

    log("  [MEM] Todos candidatos duplicados ou rejeitados.", "WARN")
    return False

# ══════════════════════════════════════════════════════════════════════════════
#  DETECCAO DE TELA
# ══════════════════════════════════════════════════════════════════════════════
RID_IGNORAR = {
    "vod_header_container","vod_logo_text","vod_search_entry","vod_section_see_all",
    "reach_banner_image","navigation_bar_item_content_container",
    "navigation_bar_item_icon_view","menu_project","menu_system","menu_me","menu_home",
    "baseRootView","baseContentView","host_fragment","mainViewPager","vod_pager","action_bar_root",
}

IGNORAR_TEXTOS = {
    "inicio","home","ao vivo","filmes","series","séries","infantil","jogos","perfil",
    "ver mais","buscar","anime","live","todos","tv aberta","uhd","esportes","futebol",
    "noticias","news","music","musica","nacional","internacional","dublado","legendado",
    "action","drama","comedy","horror","romance","sci-fi","thriller","documentary",
    "animation","family","western","all","featured","popular","new","trending","top",
}

def detectar_tela(root):
    if root is None:
        return "desconhecida"
    for node in root.iter("node"):
        n = bounds_coords(node.get("bounds",""))
        if len(n) >= 4 and (n[2]-n[0]) > (n[3]-n[1]) and (n[2]-n[0]) >= 1600:
            return "player"
        break
    for node in root.iter("node"):
        rid = (node.get("resource-id") or "").lower()
        cls = (node.get("class") or "")
        if any(k in rid for k in ["player","exo","media_controller","vod_playing"]):
            return "player"
        if "SeekBar" in cls:
            return "player"
        if "vod_detail_play_button" in rid or "vod_detail_info" in rid:
            return "detalhe"
    for node in root.iter("node"):
        txt = (node.get("text") or "").lower()
        if any(p in txt for p in ["assistir","watch","ver agora","play now"]):
            return "detalhe"
    return "lista"

_TEXTOS_DIALOGO_SISTEMA = ("isn't responding", "não está respondendo", "nao esta respondendo",
                           "wait", "esperar", "close app", "fechar app")
_TEXTOS_DIALOGO_APP     = ("falha na reprodução", "falha na reproducao", "erro ao reproduzir",
                           "playback error", "erro de reprodução", "tente novamente",
                           "não foi possível", "nao foi possivel")

def detectar_dialogo_erro(root):
    """Distingue dialogo de ERRO DO APP (ex: 'Falha na reproducao') de ANR/crash do
    SISTEMA Android (ex: '"Every Cine" isn't responding'). So retorna algo se achar texto
    tipico de um dos dois -- nao interfere em telas normais. Retorna (tipo, botoes) onde
    tipo e 'sistema'|'app'|None e botoes e um dict com coords de 'esperar'/'fechar'."""
    if root is None:
        return None, {}
    textos = []
    for node in root.iter("node"):
        txt = (node.get("text") or "").strip()
        if txt:
            textos.append((txt.lower(), node))
    corpo = " ".join(t for t, _ in textos)
    if any(p in corpo for p in _TEXTOS_DIALOGO_SISTEMA):
        tipo = "sistema"
    elif any(p in corpo for p in _TEXTOS_DIALOGO_APP):
        tipo = "app"
    else:
        return None, {}
    botoes = {}
    for txt, node in textos:
        if node.get("clickable") != "true":
            continue
        if any(k in txt for k in ("esperar", "wait")):
            botoes["esperar"] = bounds_centro(node.get("bounds", ""))
        elif any(k in txt for k in ("fechar", "close", "ok", "tente novamente")):
            botoes["fechar"] = bounds_centro(node.get("bounds", ""))
    return tipo, botoes

def tentar_lidar_com_dialogo():
    """Antes de declarar crash: verifica se e so um dialogo (erro do app ou ANR do
    sistema) que da pra fechar sozinho. Retorna True se achou e tentou lidar com algo."""
    root = parse_xml(get_ui_xml(forcar=True))
    tipo, botoes = detectar_dialogo_erro(root)
    if tipo is None:
        return False
    if tipo == "sistema":
        alvo = botoes.get("esperar") or botoes.get("fechar")
        log("  [DIALOGO] ANR do sistema detectado, tentando 'Esperar/Fechar'...", "WARN")
    else:
        alvo = botoes.get("fechar")
        log("  [DIALOGO] Dialogo de erro do app detectado, fechando...", "WARN")
    if alvo and alvo[0] is not None:
        tap(*alvo, delay=1.5)
    else:
        back(delay=1.5)
    return True

RID_RECOMENDACAO = ("recommend","similar","related","you_may","see_also","relacionado","see_all")

def tem_lista_episodios(root):
    """Verifica se a tela de detalhe possui episodios (evita confundir com carrossel de recomendados)."""
    if root is None:
        return False
    for node in root.iter("node"):
        rid = (node.get("resource-id") or "").lower()
        txt = (node.get("text") or "").lower()
        cls = (node.get("class") or "")
        if any(k in rid for k in ["episode","episodio","ep_list","season"]):
            return True
        if any(k in txt for k in ["episodio","episode","ep ","ep.","temporada","season"]):
            return True
        if ("RecyclerView" in cls or "ListView" in cls) and not any(k in rid for k in RID_RECOMENDACAO):
            filhos = list(node)
            if len(filhos) < 3:
                continue
            textos_filhos = []
            for f in filhos:
                for sub in f.iter("node"):
                    t = (sub.get("text") or "").strip()
                    if t:
                        textos_filhos.append(t.lower())
            # so confirma se os filhos parecem episodios (numero solto ou ep/temporada), nao titulos de filme
            marcados = sum(1 for t in textos_filhos if re.search(r'\bep[\.\s]?\d+|\bepis[oo]dio\b|s\d+e\d+|^\d+$', t))
            if marcados >= 2:
                return True
    return False

def coletar_episodios(root):
    """Coleta botoes de episodios na tela de detalhe. Suporta lista e carrossel."""
    episodios = []
    vistos    = set()
    if root is None:
        return episodios

    for node in root.iter("node"):
        if node.get("clickable") != "true":
            continue
        bounds = node.get("bounds","")
        if not bounds or bounds in vistos:
            continue

        rid  = (node.get("resource-id") or "").lower()
        txt  = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls  = (node.get("class") or "")

        if rid in RID_IGNORAR:
            continue

        coords = bounds_coords(bounds)
        if len(coords) < 4:
            continue
        if coords[1] > 1750 or coords[3] < 80:
            continue

        area = bounds_area(coords)
        if area < 3000 or area > TELA_W * TELA_H * 0.7:
            continue

        nome_lower = (txt or desc).lower()
        is_ep = (
            any(k in rid for k in ["episode","ep_item","vod_ep"])
            or re.search(r'\bep[\.\s]?\d+|\bepis[oo]dio\b|s\d+e\d+', nome_lower)
            or (re.search(r'^\d+$', txt) and area < 50000)
        )

        classes_validas = ["LinearLayout","FrameLayout","RelativeLayout","CardView"]
        if not is_ep and not any(c in cls for c in classes_validas):
            continue

        cx, cy = bounds_centro(bounds)
        if cx is None:
            continue

        nome_filho = ""
        for filho in node.iter("node"):
            if filho is node:
                continue
            ft = (filho.get("text") or "").strip()
            if ft and ft.lower() not in IGNORAR_TEXTOS:
                nome_filho = ft
                break

        nome_final = txt or nome_filho or desc or "???"
        rid_curto  = (node.get("resource-id") or "").split("/")[-1]
        vistos.add(bounds)
        episodios.append({"nome": nome_final, "cx": cx, "cy": cy, "bounds": bounds, "rid": rid_curto})

    episodios.sort(key=lambda e: (e["cy"]//100, e["cx"]))
    return episodios

# ══════════════════════════════════════════════════════════════════════════════
#  NAVEGACAO
# ══════════════════════════════════════════════════════════════════════════════
def esperar_tela_carregar(tela_esperada=None, max_tentativas=7, intervalo=1.5):
    xml_ant = None
    root    = None
    tela    = "desconhecida"
    for _ in range(max_tentativas):
        time.sleep(intervalo)
        xml  = get_ui_xml()
        root = parse_xml(xml)
        tela = detectar_tela(root)
        if tela_esperada and tela == tela_esperada:
            return root, tela
        if xml_ant is not None and xml == xml_ant:
            return root, tela
        if tela in ("detalhe","player"):
            return root, tela
        xml_ant = xml
    return root, tela

def achar_botao_play(root):
    if root is None:
        return None, None
    for node in root.iter("node"):
        if "vod_detail_play_button" in (node.get("resource-id") or "").lower():
            return bounds_centro(node.get("bounds",""))
    pmap = {c: p for p in root.iter() for c in p}
    for node in root.iter("node"):
        txt = (node.get("text") or "").lower()
        if any(p in txt for p in ["assistir","play","watch","ver agora","comecar"]):
            alvo = node if node.get("clickable") == "true" else pmap.get(node)
            if alvo is not None and alvo.get("clickable") == "true":
                return bounds_centro(alvo.get("bounds",""))
    return None, None

def clicar_play_confirmado(root, nome, max_tentativas=3):
    for tentativa in range(1, max_tentativas+1):
        if tentativa > 1 or root is None:
            root = parse_xml(get_ui_xml())
            tela = detectar_tela(root)
            if tela == "player":
                log("     [PLAY] Player abriu!", "OK")
                return True
            if tela == "lista":
                log("     [PLAY] Saiu da tela.", "WARN")
                return False

        bx, by = achar_botao_play(root)
        if bx:
            log(f"     [PLAY] Tentativa {tentativa}/{max_tentativas} @ ({bx},{by})", "NAV")
        else:
            if tentativa < max_tentativas:
                log(f"     [PLAY] Botao nao renderizou ({tentativa}), aguardando...", "WARN")
                time.sleep(1.5)
                root = None
                continue
            bx, by = 540, 1226
            log(f"     [PLAY] Fallback @ ({bx},{by})", "WARN")

        tap(bx, by, delay=2.0)
        _, tela = esperar_tela_carregar(tela_esperada="player", max_tentativas=4, intervalo=1.5)
        if tela == "player":
            return True
        log(f"     [PLAY] Player nao abriu (tela: {tela}), re-tentando...", "WARN")
        root = None

    log("     [PLAY] Desisti.", "ERR")
    return False

def voltar_para_tela(alvo="lista", max_tentativas=6, intervalo=1.0):
    for _ in range(max_tentativas):
        root = parse_xml(get_ui_xml())
        if detectar_tela(root) == alvo:
            return True
        back(delay=intervalo)
    log(f"     [NAV] Nao confirmei volta para '{alvo}'.", "WARN")
    return False

def extrair_titulo_detalhe(root):
    if root is None:
        return ""
    for node in root.iter("node"):
        rid = (node.get("resource-id") or "").lower()
        if "vod_detail_title" in rid:
            txt = (node.get("text") or "").strip()
            if txt:
                return txt
            ocr_txt = ler_nome_por_ocr(node.get("bounds",""))
            if ocr_txt:
                log(f"  [OCR] Titulo lido por imagem: {ocr_txt}", "INFO")
            return ocr_txt
    for node in root.iter("node"):
        rid = (node.get("resource-id") or "").lower()
        txt = (node.get("text") or "").strip()
        if not txt or txt.lower() in IGNORAR_TEXTOS:
            continue
        if any(k in rid for k in ["meta","summary","recommendation","score","play","desc"]):
            continue
        if " | " in txt or len(txt) > 80:
            continue
        return txt
    return ""

# ══════════════════════════════════════════════════════════════════════════════
#  SERIES: percorre todos os episodios
# ══════════════════════════════════════════════════════════════════════════════
def processar_episodios(root_detalhe, nome_serie):
    log(f"  [SERIE] Coletando episodios de: {nome_serie}", "EP")
    sem_novos_ep   = 0

    for scroll_ep in range(MAX_EP_SCROLL):
        root = parse_xml(get_ui_xml()) if scroll_ep > 0 else root_detalhe
        episodios = coletar_episodios(root)

        novos_ep = 0
        for ep in episodios:
            if ep["nome"] == "???":
                ocr_nome = ler_nome_por_ocr(ep["bounds"])
                if ocr_nome:
                    log(f"    [OCR] Episodio lido por imagem: {ocr_nome}", "EP")
                    ep["nome"] = ocr_nome

            nome_key = ep["nome"].strip().lower()
            chave_ep = ("ep", nome_serie, nome_key, ep["rid"]) if nome_key and nome_key != "???" else ("ep", nome_serie, scroll_ep, ep["bounds"])
            if foi_visitado(chave_ep):
                continue

            if not app_saudavel_ou_recuperado():
                raise AppCrashError(f"App nao respondia antes do episodio '{ep['nome']}' de '{nome_serie}'")

            marcar_em_processo(chave_ep)
            novos_ep += 1

            nome_ep = f"{nome_serie} - {ep['nome']}" if ep['nome'] not in ("???","") else nome_serie
            log(f"    [EP] {nome_ep} @ ({ep['cx']},{ep['cy']})", "EP")

            tap(ep["cx"], ep["cy"], delay=1.5)
            root_ep, tela = esperar_tela_carregar(max_tentativas=6, intervalo=1.5)

            if tela == "player":
                extrair_link_memoria(nome_ep, _aba_atual[0])
                voltar_para_tela("detalhe")
            elif tela == "detalhe":
                if clicar_play_confirmado(root_ep, nome_ep):
                    extrair_link_memoria(nome_ep, _aba_atual[0])
                voltar_para_tela("detalhe")
            else:
                log(f"    [EP] Tela inesperada '{tela}', voltando...", "WARN")
                voltar_para_tela("detalhe", max_tentativas=3)

            marcar_concluido(chave_ep)

        if novos_ep == 0:
            sem_novos_ep += 1
            log(f"  [EP] Sem novos ({sem_novos_ep}/3) | {progresso()}", "EP")
            if sem_novos_ep >= 3:
                log(f"  [SERIE] Todos episodios de '{nome_serie}' coletados.", "EP")
                break
        else:
            sem_novos_ep = 0
            log(f"  [EP] {novos_ep} nesta passagem | {progresso()}", "EP")

        swipe_up(dist=500)

# ══════════════════════════════════════════════════════════════════════════════
#  COLETA DE CARDS
# ══════════════════════════════════════════════════════════════════════════════
def coletar_cards(root):
    cards  = []
    vistos = set()
    if root is None:
        return cards

    for node in root.iter("node"):
        if node.get("clickable") != "true":
            continue
        bounds = node.get("bounds","")
        if not bounds or bounds in vistos:
            continue

        rid  = (node.get("resource-id") or "").split("/")[-1]
        cls  = (node.get("class") or "")
        txt  = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()

        if rid in RID_IGNORAR:
            continue
        nome = (txt or desc).lower()
        if nome in IGNORAR_TEXTOS:
            continue

        area = bounds_area(coords := bounds_coords(bounds))
        if len(coords) < 4:
            continue
        if coords[1] > 1750 or coords[3] < 80:
            continue
        if area > TELA_W * TELA_H * 0.7 or area < 5000:
            continue

        classes_validas = ["LinearLayout","FrameLayout","CardView","ImageView","RelativeLayout"]
        if not any(c in cls for c in classes_validas):
            continue

        cx, cy = bounds_centro(bounds)
        if cx is None or cy < 100:
            continue

        nome_filho = ""
        nome_prioritario = ""
        for filho in node.iter("node"):
            if filho is node:
                continue
            ft = (filho.get("text") or "").strip()
            if not ft or ft.lower() in IGNORAR_TEXTOS:
                continue
            frid = (filho.get("resource-id") or "").lower()
            # Em canais ao vivo o card tem 2 textos: numero do canal e nome do canal.
            # Prioriza o resource-id que contenha "name" (ex: live_channel_name) sobre
            # o primeiro texto encontrado na ordem do DOM (que costuma ser o numero).
            if "name" in frid and not nome_prioritario:
                nome_prioritario = ft
            if not nome_filho:
                nome_filho = ft

        nome_final = nome_prioritario or nome_filho or txt or desc or "???"
        vistos.add(bounds)
        cards.append({"nome": nome_final, "cx": cx, "cy": cy, "bounds": bounds, "rid": rid})

    cards.sort(key=lambda c: (c["cy"]//150, c["cx"]))
    return cards

# ══════════════════════════════════════════════════════════════════════════════
#  PROCESSAR ITEM (FILME OU SERIE)
# ══════════════════════════════════════════════════════════════════════════════
def processar_item(card, profundidade=0):
    if profundidade > 2:
        return

    nome = card["nome"]
    log(f"[>>] {nome} @ ({card['cx']},{card['cy']}) [prof={profundidade}]", "NAV")

    try:
        tap(card["cx"], card["cy"], delay=1.0)
        root, tela = esperar_tela_carregar(max_tentativas=7, intervalo=1.5)

        if tela == "player":
            extrair_link_memoria(nome, _aba_atual[0])
            voltar_para_tela("lista")

        elif tela == "detalhe":
            titulo = extrair_titulo_detalhe(root)
            if titulo:
                nome = titulo
                log(f"     [DETALHE] {nome}", "NAV")

            # Serie com episodios?
            if tem_lista_episodios(root):
                log(f"     [SERIE] Lista de episodios detectada!", "EP")
                processar_episodios(root, nome)
                voltar_para_tela("lista")
            else:
                # Filme: abre player e extrai
                log(f"     [FILME] Abrindo player...", "NAV")
                if clicar_play_confirmado(root, nome):
                    extrair_link_memoria(nome, _aba_atual[0])
                voltar_para_tela("lista")

        else:
            cards2 = coletar_cards(root)
            cards2 = [c for c in cards2 if c["cy"] >= 300]
            if cards2 and cards2[0]["nome"] != nome:
                log(f"     [SUBCAT] Entrando em subcategoria...", "NAV")
                processar_item(cards2[0], profundidade=profundidade+1)
            else:
                log(f"     [SKIP] Sem subcard valido.", "WARN")
            voltar_para_tela("lista")

    except AppCrashError:
        raise
    except Exception as e:
        log(f"     [ERRO] Falha em '{nome}': {e}", "ERR")
        voltar_para_tela("lista", max_tentativas=3)

# ══════════════════════════════════════════════════════════════════════════════
#  PROCESSAMENTO DE ABAS
# ══════════════════════════════════════════════════════════════════════════════
def _label_permite_precheck_titulo(label):
    """So pula clique por 'nome-ja-salvo' pra Filmes/Infantil/Outros -- Series precisa
    abrir o card pra ver a lista de episodios (o mesmo nome pode ter episodios novos), e
    canais nunca usam esse atalho (cada praca/variante e uma entrada de proposito)."""
    l = label.lower()
    return not (l.startswith("ao vivo") or l.startswith("series") or l.startswith("séries"))

def _processar_lista_cards(cards, label, tap_x, tap_y, scroll_n):
    """Processa os cards ainda nao visitados dessa leva. Em vez de confiar numa lista de
    coordenadas 'congelada' no momento da captura, RELE a tela ao vivo antes de cada
    clique -- se o scroll mudar de posicao por qualquer motivo entre um card e outro
    (ex: voltar da tela de detalhe nao preservou o lugar certo), o proximo alvo e
    recalculado certinho, em vez de clicar as cegas em coordenadas que agora apontam
    pra outra coisa (era isso que fazia o robo clicar varias vezes no mesmo item).
    Cards sem nome confiavel usam fingerprint visual (pHash) em vez de bounds+scroll_n
    (que mudam a cada rolagem -- causa raiz do clique duplicado em cards sem texto)."""
    novos     = 0
    ys_regiao = {c["cy"] for c in cards}
    while True:
        root_atual = parse_xml(get_ui_xml())
        candidatos = [c for c in coletar_cards(root_atual) if any(abs(c["cy"] - y) <= 90 for y in ys_regiao)]
        img_tela   = tirar_screenshot() if any(c["nome"] == "???" for c in candidatos) else None

        card_alvo, chave_alvo = None, None
        for card in candidatos:
            if card["nome"] == "???":
                ocr_nome = ler_nome_por_ocr(card["bounds"], img_tela)
                if ocr_nome:
                    log(f"  [OCR] Card lido por imagem: {ocr_nome}", "NAV")
                    card["nome"] = ocr_nome

            nome_key = card["nome"].strip().lower()
            if nome_key and nome_key != "???":
                if _label_permite_precheck_titulo(label):
                    base_key = chave_nome_normalizada(nome_key)
                    if len(base_key) >= 8 and base_key in nomes_base_salvos:
                        continue  # titulo ja capturado antes (em outra sub-aba/carrossel) -- pula sem clicar
                chave = ("card", label, nome_key, card["rid"])
            else:
                chave = chave_fingerprint_card(label, card, img_tela, scroll_n)

            if foi_visitado(chave):
                continue
            card_alvo, chave_alvo = card, chave
            break

        if card_alvo is None:
            break  # nenhum card novo nessa faixa de tela -- acabou

        if not app_saudavel_ou_recuperado():
            raise AppCrashError(f"App nao respondia antes de abrir '{card_alvo['nome']}' (aba '{label}')")

        marcar_em_processo(chave_alvo)
        novos += 1
        processar_item(card_alvo)
        # processar_item ja tenta voltar pra lista via BOTAO BACK (preserva o scroll).
        # So tateia a aba como ultimo recurso se realmente ficou preso em outra tela.
        if detectar_tela(parse_xml(get_ui_xml())) != "lista":
            tap(tap_x, tap_y, delay=1.5)
        marcar_concluido(chave_alvo)
    return novos

def _linhas_do_snapshot(cards, tolerancia=90):
    """Agrupa os cards visiveis por fileira (carrossel), retornando o Y de cada uma."""
    ys = sorted({c["cy"] for c in cards})
    linhas = []
    for y in ys:
        if not linhas or y - linhas[-1] > tolerancia:
            linhas.append(y)
    return linhas

def _explorar_carrosseis_horizontais(label, tap_x, tap_y, scroll_n):
    """Cada fileira da tela pode ter seu proprio carrossel horizontal (ex: 'Filmes em Alta').
    Arrasta cada fileira para o lado ate o carrossel parar de se mover (fim da lista) OU
    ate reaparecer um estado ja visto (carrossel em loop/infinito, volta ao inicio) --
    antes so comparava com o frame IMEDIATAMENTE anterior, entao um carrossel que da a
    volta completa nunca era detectado (o novo frame so repetia o PRIMEIRO, nao o ultimo)."""
    root   = parse_xml(get_ui_xml())
    linhas = _linhas_do_snapshot(coletar_cards(root))

    total = 0
    for y_linha in linhas:
        vistos_frames = set()
        for _ in range(MAX_SWIPE_LINHA):
            swipe_left(y=y_linha)
            root_h  = parse_xml(get_ui_xml())
            cards_h = [c for c in coletar_cards(root_h) if abs(c["cy"] - y_linha) <= 90]
            atual   = tuple(c["bounds"] for c in cards_h)
            if atual in vistos_frames:
                break  # fim do carrossel OU deu a volta (loop) -- para de arrastar
            vistos_frames.add(atual)
            total += _processar_lista_cards(cards_h, label, tap_x, tap_y, scroll_n)
    return total

def processar_aba(label, tap_x, tap_y):
    _aba_atual[0] = label
    log(f"\n{'='*62}", "INFO")
    log(f"  ABA: {label.upper()}", "INFO")
    log(f"{'='*62}", "INFO")

    tap(tap_x, tap_y, delay=2.5)

    sem_novo    = 0

    for scroll_n in range(MAX_SCROLL):
        if scroll_n % 3 == 0:
            _atualizar_checkpoint(scroll_n=scroll_n)
        xml   = get_ui_xml()
        root  = parse_xml(xml)
        cards = coletar_cards(root)

        novos  = _processar_lista_cards(cards, label, tap_x, tap_y, scroll_n)
        novos += _explorar_carrosseis_horizontais(label, tap_x, tap_y, scroll_n)

        if novos == 0:
            sem_novo += 1
            log(f"  [SCROLL {scroll_n+1}] Sem novos ({sem_novo}/4) | {progresso()}", "NAV")
            if sem_novo >= 4:
                log(f"  Aba '{label}' concluida!", "OK")
                break
        else:
            sem_novo = 0
            log(f"  [SCROLL {scroll_n+1}] {novos} itens processados | {progresso()}", "NAV")

        swipe_up()

def processar_aba_com_subabas(label, tap_x, tap_y):
    """Processa aba com sub-abas horizontais (Filmes > Acao, Drama...)."""
    _aba_atual[0] = label
    tap(tap_x, tap_y, delay=2.5)
    time.sleep(1)

    sub_abas   = []
    vistos_sub = set()

    # Coleta sub-abas iniciais + scroll horizontal para descobrir mais
    for swipe_n in range(5):
        xml  = get_ui_xml()
        root = parse_xml(xml)
        if root:
            for node in root.iter("node"):
                if node.get("clickable") != "true":
                    continue
                bounds = node.get("bounds","")
                txt    = (node.get("text") or "").strip()
                coords = bounds_coords(bounds)
                if len(coords) < 4:
                    continue
                # Sub-abas ficam no topo (y < 400)
                if 80 < coords[1] < 400 and txt and txt not in vistos_sub:
                    if txt.lower() in IGNORAR_TEXTOS or txt in ["Filmes","Series","Séries","Infantil","Home","Início","inicio"]:
                        continue
                    cx, cy = bounds_centro(bounds)
                    if cx:
                        sub_abas.append({"label": txt, "cx": cx, "cy": cy})
                        vistos_sub.add(txt)
        if swipe_n < 4:
            swipe_left(y=200)

    if sub_abas:
        log(f"  Sub-abas em '{label}': {[s['label'] for s in sub_abas]}", "INFO")
        for sub in sub_abas:
            try:
                _atualizar_checkpoint(sub_aba=sub['label'])
                processar_aba(f"{label}/{sub['label']}", sub["cx"], sub["cy"])
            except AppCrashError:
                raise
            except Exception as e:
                log(f"  [ERRO] Sub-aba '{sub['label']}': {e}", "ERR")
    else:
        log(f"  Sem sub-abas em '{label}', processando direto.", "INFO")
        processar_aba(label, tap_x, tap_y)

def iniciar_app_limpo():
    log("  Reiniciando app...", "NAV")
    adb_run(["am","force-stop",APP_PACKAGE])
    time.sleep(2)
    adb_run(["monkey","-p",APP_PACKAGE,"-c","android.intent.category.LAUNCHER","1"])
    time.sleep(6)
    for _ in range(5):
        root = parse_xml(get_ui_xml())
        tela = detectar_tela(root)
        if tela == "lista":
            log("  App pronto.", "OK")
            return True
        log(f"  Tela '{tela}', aguardando...", "WARN")
        back(delay=2) if tela != "desconhecida" else time.sleep(2)
    log("  Nao confirmei tela inicial, continuando.", "WARN")
    return False

# ══════════════════════════════════════════════════════════════════════════════
#  CHECKPOINT DE POSICAO + RECUPERACAO DE CRASH
# ══════════════════════════════════════════════════════════════════════════════
def _atualizar_checkpoint(aba=None, sub_aba=None, scroll_n=None):
    """Registra em que ponto da navegacao o robo esta (Log/estado_posicao.json) -- usado
    na recuperacao de crash (contexto no log) e, no boot de uma execucao nova, pra saber
    de qual aba retomar em vez de comecar do zero. Sobrescreve sempre (so importa o
    ultimo estado, nao e um log historico)."""
    if aba is not None:
        _checkpoint_atual["aba"] = aba
        _checkpoint_atual["sub_aba"] = None
    if sub_aba is not None:
        _checkpoint_atual["sub_aba"] = sub_aba
    if scroll_n is not None:
        _checkpoint_atual["scroll_n"] = scroll_n
    _checkpoint_atual["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump(_checkpoint_atual, f, ensure_ascii=False)
    except OSError as e:
        log(f"  Falha ao gravar checkpoint: {e}", "WARN")

def ler_checkpoint():
    if not os.path.exists(CHECKPOINT_PATH):
        return None
    try:
        with open(CHECKPOINT_PATH, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def limpar_checkpoint():
    """So chamado quando TODAS as abas selecionadas terminam normalmente -- assim a
    proxima execucao nao fica enviesada pra retomar numa aba que ja foi concluida."""
    try:
        if os.path.exists(CHECKPOINT_PATH):
            os.remove(CHECKPOINT_PATH)
    except OSError:
        pass

def registrar_crash():
    """Contador de crashes numa janela deslizante, com backoff progressivo (30/60/120s).
    Retorna os segundos de espera antes de tentar de novo, ou None se estourou o limite
    (a aba correspondente deve ser pulada em vez de insistir num crash-loop)."""
    agora = time.time()
    _crash_timestamps.append(agora)
    while _crash_timestamps and agora - _crash_timestamps[0] > _CRASH_JANELA_SEG:
        _crash_timestamps.pop(0)
    n = len(_crash_timestamps)
    if n > _CRASH_LIMITE:
        return None
    return {1: 30, 2: 60, 3: 120}.get(n, 120)

def recuperar_de_crash(motivo):
    """Reinicia o app do zero apos uma queda/trava. A re-navegacao ate a aba/sub-aba
    certa fica a cargo da PROPRIA funcao da aba (fn(), chamada de novo por
    _rodar_aba_resiliente) -- ela sempre parte do menu Inicio, entao reabrir o app aqui
    e deixar o fluxo normal repetir o tap ja resolve, sem duplicar logica de navegacao."""
    ck = _checkpoint_atual
    log(f"  [CRASH] {motivo} | ultimo checkpoint: aba={ck.get('aba')} "
        f"sub_aba={ck.get('sub_aba')} scroll_n={ck.get('scroll_n')}", "ERR")
    iniciar_app_limpo()

def _rodar_aba_resiliente(chave):
    """Executa a funcao de uma aba com protecao contra crash do app: se o app cair ou
    travar no meio (AppCrashError ou excecao inesperada), reinicia e tenta de novo -- o
    estado de visitados (em_processo/concluido) + qualidades ja salvas garantem que nada
    e reprocessado nem perdido. So desiste da aba se crashar demais em pouco tempo."""
    rotulo, fn = ABAS_DISPONIVEIS[chave]
    while True:
        _atualizar_checkpoint(aba=chave)
        try:
            fn()
            return
        except Exception as e:
            backoff = registrar_crash()
            if backoff is None:
                log(f"  [CRASH] Muitos crashes em pouco tempo, pulando aba '{rotulo}'.", "ERR")
                return
            log(f"  [CRASH] Falha na aba '{rotulo}': {e} -- recuperando em {backoff}s...", "ERR")
            time.sleep(backoff)
            recuperar_de_crash(f"Excecao na aba '{rotulo}'")

# ══════════════════════════════════════════════════════════════════════════════
#  RELATORIO FINAL
# ══════════════════════════════════════════════════════════════════════════════
def imprimir_relatorio(duracao, modo_noturno=False):
    total = sum(stats.values())
    mins  = duracao // 60
    segs  = duracao % 60
    if modo_noturno:
        errs = len(_erros_sessao)
        detalhes = ", ".join([f"{k}: {v}" for k,v in stats.items()])
        log(f"[MODO NOTURNO] {total} capturados | {detalhes} | {mins}m {segs}s | Erros: {errs}", "OK")
        return

    segs  = duracao % 60
    sep   = "=" * 62
    log(f"\n{sep}", "OK")
    log(f"  MISSAO CONCLUIDA  --  Sessao {SESSAO_ID}", "OK")
    log(f"{sep}", "OK")
    log(f"  Duracao : {mins}m {segs}s", "OK")
    log(f"  Total   : {total} links capturados", "OK")
    log(f"{'-'*62}", "OK")
    icons = {"Canais_AoVivo":"[TV]","Filmes":"[Filme]","Series":"[Serie]","Infantil":"[Kids]","Outros":"[???]"}
    for cat, qtd in sorted(stats.items(), key=lambda x: -x[1]):
        icon = icons.get(cat,"[???]")
        log(f"  {icon:<8} {cat:<22} : {qtd:>4} itens", "OK")
    log(f"{'-'*62}", "OK")
    log(f"  Arquivos em: {LOG_DIR}", "OK")
    for fname in sorted(os.listdir(LOG_DIR)):
        if fname.endswith(".m3u"):
            fpath = os.path.join(LOG_DIR, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    count = f.read().count("#EXTINF")
                log(f"    + {fname:<35} -> {count} itens", "OK")
            except OSError:
                pass
    if OCR_DISPONIVEL:
        t, s = OCR_METRICAS["tentativas"], OCR_METRICAS["sucessos"]
        tx = (s/t*100) if t > 0 else 0
        log(f"  OCR Fallback: {s} sucessos em {t} tentativas ({tx:.1f}%)", "INFO")
        log(f"{sep}", "OK")
        
    if _erros_sessao:
        log(f"{'-'*62}", "WARN")
        log(f"  Erros nesta sessao: {len(_erros_sessao)}", "WARN")
        for e in _erros_sessao[-5:]:
            log(f"    * {e[:80]}", "WARN")
    log(f"{sep}", "OK")
    log(f"  Log: {SESSION_LOG}", "INFO")
    log(f"{sep}", "OK")

# ══════════════════════════════════════════════════════════════════════════════
#  ABAS (cada uma pode ser rodada isolada via --abas, sem precisar reprocessar tudo)
# ══════════════════════════════════════════════════════════════════════════════
def rodar_inicio():
    processar_aba("Inicio", *MENU_INICIO)

def rodar_ao_vivo():
    processar_aba("Ao vivo", *MENU_AOVIVO)

def _abrir_aba_por_texto(texto, texto_alt=None):
    tap(*MENU_INICIO, delay=2)
    root = parse_xml(get_ui_xml())
    n = encontrar_no(root, texto=texto)
    if not n and texto_alt:
        n = encontrar_no(root, texto=texto_alt)
    return n

def rodar_filmes():
    n = _abrir_aba_por_texto("Filmes")
    if n:
        cx, cy = bounds_centro(n.get("bounds",""))
        processar_aba_com_subabas("Filmes", cx, cy)
    else:
        log("  Aba 'Filmes' nao encontrada na tela Inicio.", "WARN")

def rodar_series():
    n = _abrir_aba_por_texto("Series", "ries")
    if n:
        cx, cy = bounds_centro(n.get("bounds",""))
        processar_aba_com_subabas("Series", cx, cy)
    else:
        log("  Aba 'Series' nao encontrada na tela Inicio.", "WARN")

def rodar_infantil():
    n = _abrir_aba_por_texto("Infantil")
    if n:
        cx, cy = bounds_centro(n.get("bounds",""))
        processar_aba("Infantil", cx, cy)
    else:
        log("  Aba 'Infantil' nao encontrada na tela Inicio.", "WARN")

# chave usada em --abas -> (rotulo pra log, funcao que executa)
ABAS_DISPONIVEIS = {
    "inicio":   ("Inicio",   rodar_inicio),
    "ao_vivo":  ("Ao vivo",  rodar_ao_vivo),
    "filmes":   ("Filmes",   rodar_filmes),
    "series":   ("Series",   rodar_series),
    "infantil": ("Infantil", rodar_infantil),
}

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    _parser = argparse.ArgumentParser(
        description="Robo Extrator IPTV -- por padrao roda todas as abas; use --abas para isolar."
    )
    _parser.add_argument(
        "--abas", nargs="+", choices=list(ABAS_DISPONIVEIS.keys()) + ["todas"], default=["todas"],
        help=("Quais abas processar (padrao: todas). Ex: --abas filmes | --abas ao_vivo filmes series\n"
              "Util pra atualizar so uma categoria sem reprocessar tudo de novo (URLs ja salvas sao puladas)."),
    )
    _parser.add_argument(
        "--modo-noturno", action="store_true",
        help="Relatorio extremamente compacto ao final. Requer Desktops Virtuais ou nao minimizar."
    )
    args = _parser.parse_args()
    abas_selecionadas = list(ABAS_DISPONIVEIS.keys()) if "todas" in args.abas else args.abas

    # Retomada apos reinicio TOTAL do processo (nao so do app): se ha um checkpoint de
    # uma execucao anterior interrompida e o usuario nao escolheu abas especificas,
    # comeca direto por onde parou em vez de do zero (Regra 1.2).
    _ck_boot = ler_checkpoint()
    if _ck_boot and _ck_boot.get("aba") in ABAS_DISPONIVEIS and "todas" in args.abas:
        _idx = abas_selecionadas.index(_ck_boot["aba"])
        abas_selecionadas = abas_selecionadas[_idx:] + abas_selecionadas[:_idx]
        log(f"Checkpoint anterior encontrado: retomando direto na aba '{_ck_boot['aba']}'.", "INFO")

    BANNER = """
+============================================================+
|   ROBO EXTRATOR IPTV  *  GENIUS 7.1  (Memory Dump)        |
+============================================================+
|  [OK] Navega 100% sozinho via ADB                         |
|  [OK] Captura links por Memory Dump (sem proxy!)          |
|  [OK] Percorre episodios de series automaticamente        |
|  [OK] Scroll horizontal e vertical em todas as categorias |
|  [OK] Retomada automatica de sessao anterior              |
+============================================================+"""
    print(BANNER)
    log(f"Sessao: {SESSAO_ID}", "INFO")
    log(f"Log   : {SESSION_LOG}", "INFO")
    log(f"OCR   : {'disponivel' if OCR_DISPONIVEL else 'indisponivel (pytesseract/Tesseract ausente)'}", "INFO")
    log(f"TMDB  : {'disponivel' if TMDB_DISPONIVEL else 'indisponivel (defina TMDB_API_KEY para habilitar)'}", "INFO")
    log(f"Abas  : {', '.join(abas_selecionadas)}", "INFO")

    try:
        r = subprocess.run(["adb","devices"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"Falha ao consultar ADB: {e}", "ERR")
        input("\nEnter para sair...")
        sys.exit(1)
    if "device" not in r.stdout:
        log("EMULADOR NAO ENCONTRADO! Abra o LDPlayer primeiro.", "ERR")
        input("\nEnter para sair...")
        sys.exit(1)
    log("Emulador conectado!", "OK")

    carregar_playlists_existentes()
    carregar_estado_visitados()
    carregar_qualidades_salvas()
    iniciar_app_limpo()
    log("Iniciando navegacao automatica...", "OK")
    t_inicio = time.time()

    try:
        for _chave in abas_selecionadas:
            _rodar_aba_resiliente(_chave)
        limpar_checkpoint()  # terminou tudo normalmente -- proxima execucao comeca do zero
    except KeyboardInterrupt:
        log("\nParado pelo usuario (Ctrl+C).", "WARN")
    finally:
        duracao = int(time.time() - t_inicio)
        imprimir_relatorio(duracao, args.modo_noturno)
        input("\nPressione Enter para sair...")
