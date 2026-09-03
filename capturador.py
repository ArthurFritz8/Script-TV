import subprocess
import re
import urllib.parse
import os
import sys

# Diretórios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

print(f"[*] Iniciando Capturador Automático de IPTV...")
print(f"[*] Os arquivos da lista serão salvos em: {LOG_DIR}")
print("[*] Aguardando... Abra o emulador e comece a zapear os canais, séries e filmes!")
print("-" * 60)

# Comando ADB para rodar tcpdump como root e filtrar HTTP GET
adb_cmd = [
    "adb", "shell", "su", "-c",
    "tcpdump -i any -A -s 0 'tcp port 80 or tcp port 443'"
]

try:
    process = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, encoding='latin1')
except Exception as e:
    print(f"[!] Erro ao iniciar ADB: {e}")
    sys.exit(1)

current_get = ""
urls_vistas = set()

def salvar_link(url, nome, categoria):
    arquivo = os.path.join(LOG_DIR, f"{categoria}.m3u")
    
    # Se o arquivo não existir, cria o cabeçalho M3U padrão de listas IPTV
    if not os.path.exists(arquivo):
        with open(arquivo, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            
    # Adiciona o canal à lista no formato correto de player
    with open(arquivo, 'a', encoding='utf-8') as f:
        f.write(f"#EXTINF:-1, {nome}\n")
        f.write(f"{url}\n")
        
    print(f"[+] {categoria} salvo -> {nome}")

def extrair_nome(url):
    try:
        # Tira a codificação da URL (%20 vira espaço, etc)
        url_decoded = urllib.parse.unquote(url)
        # Quebra a URL pelas barras e ignora parâmetros de token (?)
        partes = url_decoded.split('?')[0].split('/')
        partes = [p for p in partes if p]
        
        if not partes:
            return "Desconhecido"
            
        # Pega a última parte (nome do arquivo)
        nome = partes[-1].replace('.m3u8', '').replace('.ts', '').replace('.mp4', '').replace('.mkv', '')
        
        # LÓGICA INTELIGENTE: Se for um canal ao vivo com "index.m3u8", o nome real está na pasta anterior!
        if "index" in nome.lower() and len(partes) > 1:
            nome = partes[-2]
            
        # LÓGICA INTELIGENTE (SÉRIES): Se o arquivo tem "S01E01", pega o nome da pasta (Nome da Série) + Episódio!
        elif re.search(r's\d+e\d+', nome.lower()) and len(partes) > 1:
            nome = f"{partes[-2]} - {nome}"
            
        # Limpeza visual
        nome = nome.replace('_', ' ').replace('-', ' ').strip()
        if not nome:
            nome = "Desconhecido"
            
        return nome.title()
    except Exception as e:
        return "Midia Desconhecida"

def categorizar(url, nome):
    url_lower = url.lower()
    nome_lower = nome.lower()
    
    if "movie" in url_lower or "filme" in url_lower or ".mp4" in url_lower or ".mkv" in url_lower:
        return "Filmes"
    elif "series" in url_lower or "serie" in url_lower or re.search(r's\d+e\d+', url_lower) or re.search(r's\d+e\d+', nome_lower):
        return "Series"
    else:
        return "Canais"

try:
    for line in process.stdout:
        line = line.strip()
        
        # 1. Encontra a requisição de vídeo sendo feita
        if line.startswith("GET ") and ("m3u8" in line or "mp4" in line or "mkv" in line or "/hls/" in line):
            parts = line.split(" ")
            if len(parts) >= 2:
                current_get = parts[1]
                
        # 2. Encontra o servidor (Host) que está entregando o vídeo
        elif line.startswith("Host: ") and current_get:
            current_host = line.split(" ")[1].strip()
            
            # 3. Monta o Link Direto Perfeito
            url_completa = f"http://{current_host}{current_get}"
            
            # Filtro Inteligente: Ignora os arquivos .ts (que são só os pedacinhos do vídeo carregando)
            # e garante que não vamos salvar links duplicados!
            if ".ts" not in url_completa and url_completa not in urls_vistas:
                urls_vistas.add(url_completa)
                
                nome = extrair_nome(url_completa)
                categoria = categorizar(url_completa, nome)
                
                salvar_link(url_completa, nome, categoria)
                
            # Limpa para a próxima requisição
            current_get = ""
            
except KeyboardInterrupt:
    print("\n[*] Capturador parado pelo usuário.")
    process.terminate()
except Exception as e:
    print(f"\n[!] Ocorreu um erro: {e}")
    process.terminate()
