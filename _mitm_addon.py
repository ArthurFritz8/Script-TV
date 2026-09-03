"""Addon mitmproxy: captura URLs de midia e escreve num arquivo de fifo."""
import os, re
FIFO = r"D:\\Programas Eng.Reversa\\Script pegar canais\\log\\_urls_capturadas.fifo"

def request(flow):
    url = flow.request.pretty_url
    if re.search(r"\.(m3u8|mp4|mkv|avi)(\?|$)", url, re.I):
        try:
            with open(FIFO, "a", encoding="utf-8") as f:
                f.write(url + "\n")
        except:
            pass