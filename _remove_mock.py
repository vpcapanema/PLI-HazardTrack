import re

path = r'D:/REPOSITORIOS/PLI-HazardTrack/core/aggregator.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remover import de fetch_mock (ja feito, mas verificar)
content = content.replace(
    'from .merge_inpe import fetch_real_batch, fetch_mock\n',
    'from .merge_inpe import fetch_real_batch\n'
)

# 2. Remover FORCE_MOCK
content = content.replace(
    '# Modo de desenvolvimento sem rede / sem eccodes\n'
    'FORCE_MOCK = os.environ.get("SAMAEG_FORCE_MOCK", "0") == "1"\n',
    ''
)

# 3. Remover bloco de mock
old_block = '''        # Modo dev explicito: chuva sintetica reproduzivel
        if rain_batch is None and FORCE_MOCK:
            log.warning("SAMAEG_FORCE_MOCK=1 -> usando chuva sintetica (NAO USAR EM PRODUCAO)")
            rain_batch = [fetch_mock(p["lat"], p["lon"], now) for p in self.points]
            files_ok = 0
            missing_24h = 24
            missing_96h = 96
            data_source = "MOCK (dev)"
            data_status = "mock"
            degraded = True
        elif rain_batch is None:'''

new_block = '''        if rain_batch is None:'''

content = content.replace(old_block, new_block)

# 4. Atualizar docstring
content = content.replace(
    '- NUNCA usa mock no caminho operacional. Mock so e gerado por chamada\n'
    '  explicita de teste (test_merge.py) ou pela env SAMAEG_FORCE_MOCK=1\n'
    '  durante desenvolvimento local.',
    '- NUNCA usa mock no caminho operacional. Sem dado real = NO_DATA.'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('aggregator.py atualizado')

# 5. Remover fetch_mock do merge_inpe.py
path2 = r'D:/REPOSITORIOS/PLI-HazardTrack/core/merge_inpe.py'
with open(path2, 'r', encoding='utf-8') as f:
    content2 = f.read()

# Remover funcao fetch_mock
pattern = r'# -{2,}\n# MOCK: chuva sintetica.*?def fetch_mock\(.*?\n(?:    .*\n)*?\n'
content2 = re.sub(pattern, '\n', content2, flags=re.DOTALL)

# Remover referencia a mock no comentario inicial
content2 = content2.replace(
    'NAO HA FALLBACK MOCK NO CAMINHO DE PRODUCAO. Se nao houver eccodes ou\n',
    ''
)
content2 = content2.replace(
    'rede, o aggregator marca NO_DATA (nao gera chuva falsa).\n',
    ''
)

with open(path2, 'w', encoding='utf-8') as f:
    f.write(content2)
print('merge_inpe.py atualizado')
