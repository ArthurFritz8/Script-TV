import subprocess, xml.etree.ElementTree as ET

r = subprocess.run(['adb','shell','cat','/sdcard/ui2.xml'], 
                   capture_output=True, text=True, encoding='utf-8', errors='replace')

try:
    root = ET.fromstring(r.stdout)
    print(f"XML parsed OK. Analisando elementos clicaveis...\n")
    print(f"{'TEXT':35} {'DESC':35} {'CLASS':25} {'RID':35} {'BOUNDS'}")
    print("-"*160)
    for node in root.iter('node'):
        if node.get('clickable') != 'true':
            continue
        txt    = node.get('text','')
        desc   = node.get('content-desc','')
        cls    = (node.get('class','') or '').split('.')[-1]
        rid    = (node.get('resource-id','') or '').split('/')[-1]
        bounds = node.get('bounds','')
        print(f"{txt[:34]:35} {desc[:34]:35} {cls[:24]:25} {rid[:34]:35} {bounds}")
except Exception as e:
    print(f'ERRO: {e}')
    print(r.stdout[:3000])
