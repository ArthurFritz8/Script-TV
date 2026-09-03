import sys, io, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

path = r'C:\Users\dougl\AppData\Roaming\httptoolkit\IndexedDB\https_app.httptoolkit.tech_0.indexeddb.leveldb\000003.log'

with open(path, 'rb') as f:
    data = f.read().decode('utf-8', errors='replace')

urls = re.findall(r'https?://[^\x00-\x1f\s"]+\.(?:m3u8|mp4|mkv|avi|ts)[^\x00-\x1f\s"]*', data, re.I)
print(f'URLs encontradas no IndexedDB: {len(urls)}')
for u in set(urls):
    if '.ts' not in u:  # ignora pedacinhos .ts
        print(u)
