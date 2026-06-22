"""
Camada 01 do GeoPackage `pli-hazardtrack.gpkg`: municipios_area_estudo.

Fonte de geometria:
  IDESP-SP (Infraestrutura de Dados Espaciais do Estado de Sao Paulo),
  WFS https://www.idesp.sp.gov.br/geoserver/idesp/dradt_mvw_lml_municipio_a_2021/wfs
  shapefile dradt_mvw_lml_municipio_a_2021 (LML 2021, escala 1:50.000)
  CRS de origem: SIRGAS 2000 geografico (EPSG:4674)

Fonte dos atributos rodoviarios:
  Tabela 3.2.1-2 do PRODUTO 7 (Plano de Contingencia), pg 17, Consorcio
  REGEA-NIPPON-GEOTEC-OPTIMUS (Relatorio 2053-R04-21).

Saida: data/pli-hazardtrack.gpkg, camada `municipios_area_estudo`
       (CRS de saida: EPSG:4326 = WGS84 geografico - padrao web).
"""
import sys
from pathlib import Path
import geopandas as gpd

sys.stdout.reconfigure(encoding="utf-8")

SHAPE_IN = Path("data/_dradt_src/dradt_mvw_lml_municipio_a_2021.shp")
GPKG_OUT = Path("data/pli-hazardtrack.gpkg")
LAYER = "municipios_area_estudo"

# Atributos enriquecidos por municipio (Tabela 3.2.1-2 PRODUTO 7).
# - nome_pdf: como aparece no PDF do DER
# - nome_oficial: como o IDESP/IBGE grava
# - geocodigo: IBGE 7-digit
# - rodovias: lista de rodovias da area de estudo dentro do municipio
# - regioes_icc: lista de regioes ICC que atravessam o municipio
# - km_sp055 / km_sp098: extensao da rodovia dentro do municipio
ENRIQUECIMENTO = {
    "3530607": {  # Mogi das Cruzes
        "nome_pdf": "Mogi das Cruzes",
        "rodovias": "SP-098",
        "regioes_icc": "R1",
        "km_sp055": 0.0,
        "km_sp098": 12.100,
        "km_total": 12.100,
        "uba_der": "UBA 10.04 - Mogi das Cruzes (DR.10 Sao Paulo)",
    },
    "3506607": {  # Biritiba Mirim
        "nome_pdf": "Biritiba-Mirim",
        "rodovias": "SP-098",
        "regioes_icc": "R1",
        "km_sp055": 0.0,
        "km_sp098": 7.400,
        "km_total": 7.400,
        "uba_der": "UBA 10.04 - Mogi das Cruzes (DR.10 Sao Paulo)",
    },
    "3506359": {  # Bertioga
        "nome_pdf": "Bertioga",
        "rodovias": "SP-098;SP-055",
        "regioes_icc": "R1;R4",
        "km_sp055": 42.000,
        "km_sp098": 15.700,
        "km_total": 57.700,
        "uba_der": "UBA 05.04 - Sao Vicente (DR.05 Cubatao)",
    },
    "3548500": {  # Santos
        "nome_pdf": "Santos",
        "rodovias": "SP-055",
        "regioes_icc": "R4",
        "km_sp055": 14.700,
        "km_sp098": 0.0,
        "km_total": 14.700,
        "uba_der": "UBA 05.04 - Sao Vicente (DR.05 Cubatao)",
    },
    "3550704": {  # Sao Sebastiao
        "nome_pdf": "São Sebastião",
        "rodovias": "SP-055",
        "regioes_icc": "R2;R3",
        "km_sp055": 78.850,
        "km_sp098": 0.0,
        "km_total": 78.850,
        "uba_der": ("UBA 06.04 - Caraguatatuba + UBA 05.04 - Sao Vicente "
                    "(parcial)"),
    },
    "3510500": {  # Caraguatatuba
        "nome_pdf": "Caraguatatuba",
        "rodovias": "SP-055",
        "regioes_icc": "R2",
        "km_sp055": 30.580,
        "km_sp098": 0.0,
        "km_total": 30.580,
        "uba_der": "UBA 06.04 - Caraguatatuba (DR.06 Taubate)",
    },
    "3555406": {  # Ubatuba
        "nome_pdf": "Ubatuba",
        "rodovias": "SP-055",
        "regioes_icc": "R2",
        "km_sp055": 28.370,
        "km_sp098": 0.0,
        "km_total": 28.370,
        "uba_der": "UBA 06.04 - Caraguatatuba (DR.06 Taubate)",
    },
}


def main():
    print(f"Lendo {SHAPE_IN} ...")
    gdf = gpd.read_file(SHAPE_IN, encoding="ISO-8859-1")
    print(f"  Total municipios no SP: {len(gdf)}")
    print(f"  CRS origem: {gdf.crs}")

    geocodigos = list(ENRIQUECIMENTO.keys())
    sel = gdf[gdf["geocodigo"].isin(geocodigos)].copy()
    print(f"\n  Filtrado: {len(sel)} feicoes (esperado: 7)")
    assert len(sel) == 7, f"Esperava 7 municipios, encontrou {len(sel)}"

    # Enriquecimento
    def enrich(geo):
        return ENRIQUECIMENTO[geo]

    for k in ["nome_pdf", "rodovias", "regioes_icc", "km_sp055",
              "km_sp098", "km_total", "uba_der"]:
        sel[k] = sel["geocodigo"].apply(lambda g: enrich(g)[k])

    # Calcula area em km^2 e centroide em UTM 23S (EPSG:31983) para precisao
    sel_utm = sel.to_crs(31983)
    sel["area_km2"] = (sel_utm.area / 1e6).round(3)
    centroids = sel_utm.geometry.centroid.to_crs(4326)
    sel["centroide_lon"] = centroids.x.round(6)
    sel["centroide_lat"] = centroids.y.round(6)

    # Renomeia colunas para o schema final
    sel = sel.rename(columns={"nome": "nome_ibge"})

    # Ordem operacional: do oeste (Mogi) para leste (Ubatuba)
    ordem = {
        "3530607": 1,  # Mogi das Cruzes
        "3506607": 2,  # Biritiba Mirim
        "3506359": 3,  # Bertioga
        "3548500": 4,  # Santos
        "3550704": 5,  # Sao Sebastiao
        "3510500": 6,  # Caraguatatuba
        "3555406": 7,  # Ubatuba
    }
    sel["ordem_oeste_leste"] = sel["geocodigo"].apply(lambda g: ordem[g])
    sel = sel.sort_values("ordem_oeste_leste").reset_index(drop=True)

    # Schema final - apenas colunas escolhidas, em ordem
    schema = [
        "ordem_oeste_leste",
        "geocodigo",
        "nome_ibge",
        "nome_pdf",
        "rodovias",
        "regioes_icc",
        "km_sp055",
        "km_sp098",
        "km_total",
        "area_km2",
        "centroide_lon",
        "centroide_lat",
        "uba_der",
        "geometry",
    ]
    sel = sel[schema]

    # Reprojeta para EPSG:4326
    sel = sel.to_crs(4326)

    # Garante MultiPolygon (alguns municipios costeiros tem ilhas)
    from shapely.geometry import MultiPolygon
    sel["geometry"] = sel["geometry"].apply(
        lambda g: g if isinstance(g, MultiPolygon)
        else MultiPolygon([g])
    )

    # Grava no GeoPackage
    GPKG_OUT.parent.mkdir(parents=True, exist_ok=True)
    sel.to_file(GPKG_OUT, layer=LAYER, driver="GPKG", index=False)
    print(f"\n  Camada '{LAYER}' gravada em {GPKG_OUT}")
    print(f"  CRS de saida: EPSG:{sel.crs.to_epsg()}")

    print("\nRESUMO DA CAMADA:")
    print(sel.drop(columns="geometry").to_string(index=False))

    return GPKG_OUT


if __name__ == "__main__":
    main()
