"""Preview visual das camadas geradas: municipios + regioes + auxiliar."""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import geopandas as gpd

_reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure_stdout):
    _reconfigure_stdout(encoding="utf-8")

GPKG = Path("data/pli-hazardtrack.gpkg")
OUT = Path("ferramentas/geracao-geopackage/_preview_regioes.png")

CORES = {
    1: "#3498db",  # Mogi-Bertioga (azul)
    2: "#e67e22",  # Caraguatatuba-Ubatuba (laranja)
    3: "#27ae60",  # Sao Sebastiao (verde)
    4: "#e74c3c",  # Santos-Bertioga (vermelho)
}

mun = gpd.read_file(GPKG, layer="municipios_area_estudo")
aux = gpd.read_file(GPKG, layer="auxilio_regioes_estudo")
regs = gpd.read_file(GPKG, layer="regioes_estudo")

fig, ax = plt.subplots(figsize=(13, 13), dpi=110)

mun.plot(ax=ax, facecolor="#f5f5f0", edgecolor="#7f7f7f",
         linewidth=0.7, alpha=0.85)
for _, r in mun.iterrows():
    c = r.geometry.representative_point()
    ax.annotate(r["nome_ibge"], (c.x, c.y),
                ha="center", fontsize=8, color="#444", weight="bold")

for rid, cor in CORES.items():
    sub = regs[regs["regiao_id"] == rid]
    sub.plot(ax=ax, facecolor=cor, edgecolor=cor,
             alpha=0.32, linewidth=1.2)

for rid, cor in CORES.items():
    sub = aux[aux["regiao_id"] == rid]
    sub.plot(ax=ax, color=cor, linewidth=1.6)

for rid in [1, 2, 3, 4]:
    row = regs[regs["regiao_id"] == rid].iloc[0]
    c = row.geometry.representative_point()
    txt = f"R{rid} {row['regiao_nome']}\n{row['extensao_oficial_km']:.1f} km"
    ax.annotate(txt, (c.x, c.y), ha="center", fontsize=9,
                color="white", weight="bold",
                bbox=dict(facecolor=CORES[rid], edgecolor="white",
                          alpha=0.9, boxstyle="round,pad=0.35"))

ax.set_title(
    "GPKG pli-hazardtrack: municipios_area_estudo + auxilio + regioes_estudo\n"
    "(buffer 1 km lateral, tampas perpendiculares nas emendas, "
    "round nas absolutas)",
    fontsize=11,
)
ax.set_aspect("equal")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.grid(alpha=0.2)

OUT.parent.mkdir(parents=True, exist_ok=True)
plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"PNG: {OUT}")
