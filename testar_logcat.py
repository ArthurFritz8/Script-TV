"""Testa o logcat em tempo real para ver o que o app loga quando um video e reproduzido."""
import subprocess, sys, io, re, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("[*] Aguardando URLs no logcat... (abra um video no emulador agora!)")
print("[*] Ctrl+C para parar\n")

proc = subprocess.Popen(
    ["adb", "shell", "logcat", "-c"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
proc.wait()
time.sleep(1)

proc = subprocess.Popen(
    ["adb", "shell", "logcat", "-v", "time", "*:V"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    encoding="utf-8", errors="replace"
)

try:
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(p in lower for p in ["m3u8", ".mp4", ".mkv", ".avi", ".ts?", "stream", "manifest", "cdn", "http", "media", "exo", "player"]):
            print(f"LOG >>> {line}")
except KeyboardInterrupt:
    proc.terminate()
    print("\n[*] Parado.")
