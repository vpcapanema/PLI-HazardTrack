"""
Pontos de monitoramento ao longo das rodovias SP-055 e SP-098.

Cada ponto tem:
- id, nome, lat, lon
- ra (Risco Analisado) - default 1 ate haver shapefile RA do IG-SP
- km, rodovia (referencia rodoviaria)

Estes pontos sao amostrados a cada ciclo de atualizacao para producao do
mapa de calor de risco em tempo real.
"""

# Pontos amostrais ao longo das rodovias (lat, lon aprox, espacados ~5-10 km)
MONITORING_POINTS = [
    # SP-098 (Mogi-Bertioga) - Regiao 1
    {"id": "SP098-01", "rodovia": "SP-098", "km": 65, "lat": -23.510, "lon": -46.150, "ra": 2, "nome": "Mogi das Cruzes"},
    {"id": "SP098-02", "rodovia": "SP-098", "km": 72, "lat": -23.540, "lon": -46.080, "ra": 2, "nome": "Biritiba-Mirim N"},
    {"id": "SP098-03", "rodovia": "SP-098", "km": 78, "lat": -23.585, "lon": -46.030, "ra": 3, "nome": "Biritiba-Mirim S"},
    {"id": "SP098-04", "rodovia": "SP-098", "km": 85, "lat": -23.660, "lon": -46.000, "ra": 3, "nome": "Serra Mogi-Bert"},
    {"id": "SP098-05", "rodovia": "SP-098", "km": 92, "lat": -23.745, "lon": -46.020, "ra": 3, "nome": "Bertioga N"},
    {"id": "SP098-06", "rodovia": "SP-098", "km": 97, "lat": -23.790, "lon": -46.060, "ra": 2, "nome": "Bertioga"},

    # SP-055 (Caraguatatuba-Ubatuba) - Regiao 2
    {"id": "SP055-N01", "rodovia": "SP-055", "km": 55, "lat": -23.255, "lon": -44.835, "ra": 2, "nome": "Ubatuba N"},
    {"id": "SP055-N02", "rodovia": "SP-055", "km": 65, "lat": -23.330, "lon": -44.920, "ra": 3, "nome": "Ubatuba Centro"},
    {"id": "SP055-N03", "rodovia": "SP-055", "km": 75, "lat": -23.395, "lon": -44.985, "ra": 3, "nome": "Ubatuba S"},
    {"id": "SP055-N04", "rodovia": "SP-055", "km": 85, "lat": -23.470, "lon": -45.060, "ra": 3, "nome": "Caraguatatuba N"},
    {"id": "SP055-N05", "rodovia": "SP-055", "km": 95, "lat": -23.555, "lon": -45.155, "ra": 2, "nome": "Caraguatatuba C"},
    {"id": "SP055-N06", "rodovia": "SP-055", "km": 105, "lat": -23.625, "lon": -45.230, "ra": 2, "nome": "Caraguatatuba S"},

    # SP-055 (Sao Sebastiao) - Regiao 3 (mais critica, K=200)
    {"id": "SP055-C01", "rodovia": "SP-055", "km": 130, "lat": -23.690, "lon": -45.350, "ra": 3, "nome": "Boicucanga"},
    {"id": "SP055-C02", "rodovia": "SP-055", "km": 140, "lat": -23.745, "lon": -45.430, "ra": 4, "nome": "Maresias"},
    {"id": "SP055-C03", "rodovia": "SP-055", "km": 150, "lat": -23.785, "lon": -45.510, "ra": 4, "nome": "Camburi"},
    {"id": "SP055-C04", "rodovia": "SP-055", "km": 160, "lat": -23.810, "lon": -45.600, "ra": 4, "nome": "Juquehy"},
    {"id": "SP055-C05", "rodovia": "SP-055", "km": 170, "lat": -23.835, "lon": -45.690, "ra": 3, "nome": "Sao Sebastiao N"},
    {"id": "SP055-C06", "rodovia": "SP-055", "km": 180, "lat": -23.825, "lon": -45.745, "ra": 3, "nome": "Sao Sebastiao C"},
    {"id": "SP055-C07", "rodovia": "SP-055", "km": 190, "lat": -23.815, "lon": -45.810, "ra": 2, "nome": "Sao Sebastiao S"},

    # SP-055 (Santos-Bertioga) - Regiao 4
    {"id": "SP055-S01", "rodovia": "SP-055", "km": 200, "lat": -23.825, "lon": -45.890, "ra": 2, "nome": "Bertioga L"},
    {"id": "SP055-S02", "rodovia": "SP-055", "km": 210, "lat": -23.838, "lon": -46.000, "ra": 2, "nome": "Bertioga Centro"},
    {"id": "SP055-S03", "rodovia": "SP-055", "km": 225, "lat": -23.875, "lon": -46.135, "ra": 2, "nome": "Guaruja N"},
    {"id": "SP055-S04", "rodovia": "SP-055", "km": 235, "lat": -23.940, "lon": -46.220, "ra": 2, "nome": "Guaruja"},
    {"id": "SP055-S05", "rodovia": "SP-055", "km": 245, "lat": -23.985, "lon": -46.330, "ra": 2, "nome": "Santos"},
]
