path = r'D:/REPOSITORIOS/PLI-HazardTrack/core/aggregator.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Localizar e substituir o bloco da mensagem
start = content.find('"message": (')
if start >= 0:
    end = content.find('                ),', start)
    if end >= 0:
        end += len('                ),')
        old = content[start:end]
        new = '"message": (\n                    "Sem dado real do MERGE/INPE."\n                ),'
        content = content.replace(old, new)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Fixed message block')
    else:
        print('End not found')
else:
    print('Start not found')
