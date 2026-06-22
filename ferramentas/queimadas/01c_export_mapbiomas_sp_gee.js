/*
Exporta MapBiomas cobertura/uso do solo recortado para o Estado de Sao Paulo.

Executar no Google Earth Engine Code Editor:
https://code.earthengine.google.com/

Saida esperada no Google Drive:
MAPBIOMAS-EXPORT/vegetacao_inpe_sp_2024.tif

Depois baixar manualmente para:
data/queimadas/base/vegetacao_inpe.tif

Motivo: MapBiomas nao publica GeoTIFF pronto por UF em link direto publico.
O recorte por estado/municipio e gerado pela Plataforma MapBiomas ou GEE.
*/

var year = 2024;
var asset = 'projects/mapbiomas-public/assets/brazil/lulc/' +
  'collection10_1/mapbiomas_brazil_collection10_1_coverage_v1';

var sp = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Brazil'))
  .filter(ee.Filter.eq('ADM1_NAME', 'Sao Paulo'));

// Se preferir usar o limite IBGE local, suba data/queimadas/base/limite_sp_ibge.geojson
// como asset e substitua a variavel `sp` acima pelo seu FeatureCollection.

var image = ee.Image(asset).select('classification_' + year).clip(sp);

Map.centerObject(sp, 7);
Map.addLayer(
  image,
  {
    min: 0,
    max: 62,
    palette: [
      'ffffff', '1f8d49', '7dc975', '04381d', '026975', 'd6bc74',
      'edde8e', 'f5b3c8', 'c27ba0', 'db4d4f', 'ffa07a', 'd4271e',
      'db4d4f', 'ffaa5f', '9c0027', '091077'
    ]
  },
  'MapBiomas cobertura ' + year
);

Export.image.toDrive({
  image: image.toByte(),
  description: 'vegetacao_inpe_sp_' + year,
  folder: 'MAPBIOMAS-EXPORT',
  fileNamePrefix: 'vegetacao_inpe_sp_' + year,
  region: sp.geometry(),
  scale: 30,
  crs: 'EPSG:4326',
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});
