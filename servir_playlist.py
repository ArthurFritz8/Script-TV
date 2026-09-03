"""
Sobe um servidor local que serve a pasta Log/ pela rede, pra voce conseguir
um LINK (URL) da playlist e colocar direto no app de IPTV (TV, celular, TV Box)
sem precisar copiar arquivo manualmente. Funciona com qualquer aparelho
conectado no MESMO Wi-Fi/rede deste PC.

Uso:
    python servir_playlist.py            (porta padrao 8765)
    python servir_playlist.py 9000        (escolher outra porta)

O link fica assim:
    http://<ip-deste-pc>:8765/playlist_completa.m3u
(o proprio script imprime o link certinho pra copiar)

Deixe essa janela aberta enquanto for usar a lista no app de IPTV.
Aperte Ctrl+C pra parar o servidor.
"""
import os
import sys
import socket
import functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR  = os.path.join(BASE_DIR, "log")
ARQUIVO_PADRAO = "playlist_completa.m3u"
PORTA_PADRAO = 8765  # 8080 costuma estar reservada pelo Windows (WinError 10013)


def descobrir_ip_local():
    """Pega o IP deste PC na rede local (sem precisar de internet de verdade)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else PORTA_PADRAO
    ip = descobrir_ip_local()

    handler = functools.partial(SimpleHTTPRequestHandler, directory=LOG_DIR)
    servidor = ThreadingHTTPServer(("0.0.0.0", porta), handler)

    print("=" * 60)
    print(" Servidor de playlist rodando!")
    print(f" Link da playlist completa:")
    print(f"   http://{ip}:{porta}/{ARQUIVO_PADRAO}")
    print(" (use esse link no campo 'URL da lista M3U' do seu app de IPTV)")
    print(" Pastas Log/*.m3u tambem ficam acessiveis nesse endereco.")
    print(" Ctrl+C para parar.")
    print("=" * 60)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
        servidor.shutdown()


if __name__ == "__main__":
    main()
