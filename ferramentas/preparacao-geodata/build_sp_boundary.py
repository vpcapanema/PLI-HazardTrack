"""
Gera o contorno simplificado do estado de Sao Paulo a partir do IBGE.

Saida: static/data/sp_state.geojson  (~< 100 KB simplificado)

Esse arquivo e usado pelo frontend para mascarar o "resto do Brasil" no mapa,
destacando o estado de SP. Roda 1x; nao precisa rodar de novo a menos que
queira atualizar o contorno.
"""
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "static" / "data" / "sp_state.geojson"

# Servico oficial IBGE: malha do estado SP (codigo 35), qualidade intermediaria.
URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/35"
    "?formato=application/vnd.geo+json&qualidade=intermediaria"
)

print(f"Baixando {URL}")
req = urllib.request.Request(URL, headers={
    "User-Agent": "PLI-HazardTrack/0.1",
    "Accept-Encoding": "gzip",
})
with urllib.request.urlopen(req, timeout=30) as resp:
    data = resp.read()
    if resp.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
        import gzip
        data = gzip.decompress(data)
    raw = data.decode("utf-8")
gj = json.loads(raw)
print(f"  features: {len(gj.get('features', []))}")

# Simplifica geometria com shapely se disponivel - senao salva como veio
try:
    from shapely.geometry import shape, mapping

    out_features = []
    for feat in gj["features"]:
        geom = shape(feat["geometry"])
        # tolerancia ~0.005 graus -> ~500m, suficiente para vista estadual
        geom = geom.simplify(0.005, preserve_topology=True)
        out_features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": feat.get("properties", {}),
        })
    out = {"type": "FeatureCollection", "features": out_features}
except Exception as e:
    print(f"  shapely nao disponivel ({e}); salvando sem simplificar")
    out = gj

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"Salvo em {OUT}")
print(f"  tamanho: {OUT.stat().st_size / 1024:.1f} KB")
