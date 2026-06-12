import sys

path = r'D:/REPOSITORIOS/PLI-HazardTrack/core/aggregator.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Correcoes de linhas longas
replacements = [
    # Line 62
    ('                "id": p["id"], "nome": p["nome"], "rodovia": p["rodovia"], "km": p["km"],',
     '                "id": p["id"], "nome": p["nome"],\n'
     '                "rodovia": p["rodovia"], "km": p["km"],'),
    # Line 129
    ('            summary = self.snapshot.get("summary", {}) if hasattr(self, "snapshot") else {}',
     '            summary = (\n'
     '                self.snapshot.get("summary", {})\n'
     '                if hasattr(self, "snapshot") else {}\n'
     '            )'),
    # Line 143
    ('        """Logica do ciclo, separada para captura de erro/timing em update()."""',
     '        """\n'
     '        Logica do ciclo, separada para captura de\n'
     '        erro/timing em update().\n'
     '        """'),
    # Line 161
    ('            data_status = "ok" if missing_24h < DEGRADED_MISSING_24H_THRESHOLD else "degraded"',
     '            data_status = (\n'
     '                "ok"\n'
     '                if missing_24h < DEGRADED_MISSING_24H_THRESHOLD\n'
     '                else "degraded"\n'
     '            )'),
    # Line 171
    ('                region = find_region_for_point(p["lat"], p["lon"], self.regions)',
     '                region = find_region_for_point(\n'
     '                    p["lat"], p["lon"], self.regions\n'
     '                )'),
    # Line 184
    ('                    "id": p["id"], "nome": p["nome"], "rodovia": p["rodovia"], "km": p["km"],',
     '                    "id": p["id"], "nome": p["nome"],\n'
     '                    "rodovia": p["rodovia"], "km": p["km"],'),
    # Line 186
    ('                    "region_id": result.region_id, "region_name": result.region_name,',
     '                    "region_id": result.region_id,\n'
     '                    "region_name": result.region_name,'),
    # Line 197
    ('                hist = self.point_rd_history.setdefault(p["id"], deque(maxlen=24))',
     '                hist = self.point_rd_history.setdefault(\n'
     '                    p["id"], deque(maxlen=24)\n'
     '                )'),
    # Line 239
    ('            "  ok: %d pontos, max RD=%d, niveis=%s, status=%s (24h faltando=%d)",',
     '            (\n'
     '                "  ok: %d pontos, max RD=%d, "\n'
     '                "niveis=%s, status=%s (24h faltando=%d)"\n'
     '            ),'),
    # Line 257
    ('                "id": p["id"], "nome": p["nome"], "rodovia": p["rodovia"], "km": p["km"],',
     '                "id": p["id"], "nome": p["nome"],\n'
     '                "rodovia": p["rodovia"], "km": p["km"],'),
    # Line 289-290
    ('                    "O servidor pode estar com latencia (>3h) ou indisponivel, '
     'ou o conjunto de',
     '                    (\n'
     '                        "O servidor pode estar com latencia "\n'
     '                        "(>3h) ou indisponivel, ou o conjunto de"\n'
     '                    ),'),
    # Line 290
    ('                    "dados para os horarios acumulados pode estar incompleto. '
     'Tente novamente mais',
     '                    (\n'
     '                        "dados para os horarios acumulados pode "\n'
     '                        "estar incompleto. Tente novamente mais"\n'
     '                    ),'),
    # Line 305
    ('                "uptime_s": (datetime.now(timezone.utc) - self.started_at).total_seconds(),',
     '                "uptime_s": (\n'
     '                    datetime.now(timezone.utc) - self.started_at\n'
     '                ).total_seconds(),'),
    # Line 311
    ('                "last_cycle_finished_at": self.last_cycle_finished_at.isoformat()',
     '                "last_cycle_finished_at": (\n'
     '                    self.last_cycle_finished_at.isoformat()\n'
     '                )'),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f'Fixed: {old[:50]}...')
    else:
        print(f'NOT FOUND: {old[:50]}...')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verificar
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
errors = []
for i, line in enumerate(lines, 1):
    if len(line.rstrip()) > 79:
        errors.append(f'Line {i}: {len(line.rstrip())} chars')

if errors:
    print('\nRemaining errors:')
    for e in errors:
        print(f'  {e}')
else:
    print('\nAll lines <= 79 chars')
