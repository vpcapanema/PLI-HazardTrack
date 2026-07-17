"""Preview + spot-check da camada uas_area_estudo."""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import geopandas as gpd

_reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure_stdout):
    _reconfigure_stdout(encoding="utf-8")

GPKG = "data/pli-hazardtrack.gpkg"
OUT = Path("ferramentas/geracao-geopackage/_preview_uas.png")

mun = gpd.read_file(GPKG, layer="municipios_area_estudo")
regs = gpd.read_file(GPKG, layer="regioes_estudo")
uas = gpd.read_file(GPKG, layer="uas_area_estudo")

print("Colunas uas_area_estudo:")
print(list(uas.columns))
print("\nAmostra (3 primeiras UAs):")
print(uas.head(3).drop(columns="geometry").to_string())

print("\nQtd por escala:")
print(uas["escala"].value_counts())
print("\nQtd por regiao_id x escala:")
print(uas.groupby(["regiao_id", "escala"]).size().unstack(fill_value=0))

COR_REG = {1: "#3498db", 2: "#e67e22", 3: "#27ae60", 4: "#e74c3c"}
COR_ESC = {"25K": "#888888", "10K": "#f39c12", "1K": "#c0392b"}

fig, axes = plt.subplots(1, 2, figsize=(20, 10), dpi=110)

# painel 1 - colorido por regiao
ax = axes[0]
mun.plot(ax=ax, facecolor="#f8f8f5", edgecolor="#999", linewidth=0.6)
for rid, cor in COR_REG.items():
    regs[regs["regiao_id"] == rid].plot(ax=ax, facecolor=cor,
                                        alpha=0.15, edgecolor=cor)
    uas[uas["regiao_id"] == rid].plot(ax=ax, color=cor, linewidth=1.4)
ax.set_title("UAs coloridas por Regiao (4 cores)")
ax.set_aspect("equal")
ax.grid(alpha=0.2)

# painel 2 - colorido por escala
ax = axes[1]
mun.plot(ax=ax, facecolor="#f8f8f5", edgecolor="#999", linewidth=0.6)
regs.plot(ax=ax, facecolor="none", edgecolor="#666",
          linewidth=0.7, linestyle="--")
for esc, cor in COR_ESC.items():
    sub = uas[uas["escala"] == esc]
    if len(sub):
        sub.plot(ax=ax, color=cor, linewidth=1.6, label=f"{esc} ({len(sub)})")
ax.legend(loc="lower right", title="Escala de origem")
ax.set_title("UAs coloridas por Escala (25K=cinza  10K=laranja  1K=vermelho)")
ax.set_aspect("equal")
ax.grid(alpha=0.2)

OUT.parent.mkdir(parents=True, exist_ok=True)
plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nPNG: {OUT}")
