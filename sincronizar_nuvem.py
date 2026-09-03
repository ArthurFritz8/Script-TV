import os
import subprocess
import re

LOG_DIR = r"D:\Programas Eng.Reversa\Script pegar canais\log"
ARQUIVO_M3U = os.path.join(LOG_DIR, "playlist_completa.m3u")
ARQUIVO_ID_GIST = os.path.join(LOG_DIR, ".gist_id")

def log(msg):
    print(f"[NUVEM] {msg}")

def get_github_username():
    """Descobre o username do Github autenticado via gh cli."""
    try:
        result = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def criar_gist():
    log("Criando Gist privado na nuvem pela primeira vez (via API)...")
    try:
        with open(ARQUIVO_M3U, "r", encoding="utf-8", errors="ignore") as f:
            conteudo = f.read()
            
        import json
        payload = {
            "description": "Playlist Every Cine IPTV",
            "public": False,
            "files": {
                "playlist_completa.m3u": {
                    "content": conteudo
                }
            }
        }
        
        with open("temp_payload.json", "w", encoding="utf-8") as f:
            json.dump(payload, f)
            
        cmd = ["gh", "api", "gists", "--input", "temp_payload.json"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        dados = json.loads(result.stdout)
        gist_id = dados.get("id")
        
        if gist_id:
            with open(ARQUIVO_ID_GIST, "w", encoding="utf-8") as f:
                f.write(gist_id)
            log(f"Gist criado com sucesso! ID: {gist_id}")
            return gist_id
        else:
            log("Erro: API nao retornou ID valido.")
            return None
    except subprocess.CalledProcessError as e:
        log(f"Erro ao criar Gist: {e.stderr}")
        return None
    finally:
        if os.path.exists("temp_payload.json"):
            os.remove("temp_payload.json")

def atualizar_gist(gist_id):
    log(f"Atualizando playlist no Gist existente ({gist_id}) via API...")
    try:
        with open(ARQUIVO_M3U, "r", encoding="utf-8", errors="ignore") as f:
            conteudo = f.read()
            
        import json
        payload = {
            "files": {
                "playlist_completa.m3u": {
                    "content": conteudo
                }
            }
        }
        
        with open("temp_payload_patch.json", "w", encoding="utf-8") as f:
            json.dump(payload, f)
            
        cmd = ["gh", "api", "--method", "PATCH", f"gists/{gist_id}", "--input", "temp_payload_patch.json"]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        log("Playlist atualizada na nuvem com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        erro = e.stderr.lower()
        if "not found" in erro or "404" in erro:
            log("Erro: O Gist anterior nao foi encontrado (talvez tenha sido apagado).")
            return False
        log(f"Erro ao atualizar Gist: {e.stderr}")
        return True # Retorna True para nao recriar se for erro de rede aleatorio
    finally:
        if os.path.exists("temp_payload_patch.json"):
            os.remove("temp_payload_patch.json")

def gerar_raw_url(username, gist_id):
    # A URL raw padrao do Gist aponta sempre para o ultimo commit do arquivo
    return f"https://gist.githubusercontent.com/{username}/{gist_id}/raw/playlist_completa.m3u"

def main():
    if not os.path.exists(ARQUIVO_M3U):
        log("Arquivo playlist_completa.m3u nao encontrado! Rode o gerar_playlist_final.py primeiro.")
        return

    username = get_github_username()
    if not username:
        log("Erro: Voce precisa estar logado no GitHub CLI. Rode 'gh auth login'.")
        return

    gist_id = None
    if os.path.exists(ARQUIVO_ID_GIST):
        with open(ARQUIVO_ID_GIST, "r", encoding="utf-8") as f:
            gist_id = f.read().strip()
            
    if gist_id:
        sucesso = atualizar_gist(gist_id)
        if not sucesso:
            # Gist deletado, recriar
            gist_id = criar_gist()
    else:
        gist_id = criar_gist()

    if gist_id:
        url_raw = gerar_raw_url(username, gist_id)
        print("\n" + "="*80)
        print(" SUCESSO! SUA PLAYLIST ESTA NA NUVEM")
        print("="*80)
        print(f" URL PARA COLAR NO TIVIMATE:")
        print(f" {url_raw}")
        print("="*80)
        print(" (Essa URL nunca muda. Toda vez que rodar este script, a nuvem atualiza)")

if __name__ == "__main__":
    main()
