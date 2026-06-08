"""
Digitaliza o Risco Analisado (RA) das figuras da secao 3.3.3 do Produto 7
e projeta na malha DER/SP real, gerando ZONAS (trechos contiguos de mesmo RA)
= Unidades de Analise (UAs) aproximadas.

Metodo (validado em POC na Regiao 3):
1. Extrai a imagem nativa do mapa de cada figura regional (RA GEO e RA HID).
2. Georreferencia via ticks do grid UTM (SIRGAS 2000 / UTM 23S, EPSG:31983).
3. Amostra a cor da rodovia sobre a malha DER densificada (~20 m), classifica
   por matiz (legenda RA0..RA4), voto majoritario em janela 5x5.
4. Funde GEO+HID por posicao e agrupa posicoes consecutivas de mesmo
   (ra_geo, ra_hid) em zonas (LineString).

LIMITES (honestos): resolucao ~40 m/px; e uma digitalizacao aproximada das
figuras, nao o vetor original das 809 UAs. Erro de posicao ~dezenas de metros.

Saida: data/ua_zones/ua_zones.geojson  + overlays de validacao em _fig_tmp/.
"""

import sys
import colorsys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import geopandas as gpd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402  # pylint: disable=wrong-import-position

PDF = next(p for p in ROOT.glob('**/*PRODUTO 7 Plano*.pdf') if 'Tema30' in str(p))
DER_SHP = ROOT / 'data' / 'der_sistema_rodoviario' / 'MALHA_RODOVIARIA.shp'
OUT_DIR = ROOT / 'data' / 'ua_zones'
FIG_DIR = ROOT / '_fig_tmp'
FIG_DIR.mkdir(exist_ok=True)

# Config por regiao (paginas 1-based; extents lidos das figuras)
REGIONS = {
    1: dict(rodovia='SP 098', page_geo=52, page_hid=63,
            E=(350000, 430000), N=(7370000, 7410000)),
    2: dict(rodovia='SP 055', page_geo=54, page_hid=65,
            E=(430000, 530000), N=(7370000, 7430000)),
    3: dict(rodovia='SP 055', page_geo=56, page_hid=67,
            E=(420000, 460000), N=(7360000, 7380000)),
    4: dict(rodovia='SP 055', page_geo=58, page_hid=69,
            E=(360000, 420000), N=(7350000, 7380000)),
}


def _flt(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _zlen(feat):
    return LineString(feat['geometry']['coordinates']).length


def _hist_match(zones, channel, dist):
    """Reatribui a classe do canal por histogram-matching contra a tabela:
    preserva o rank espacial (zonas mais criticas na figura permanecem mais
    criticas) mas impoe as PROPORCOES oficiais por comprimento.
    Anti-sub-alerta: as zonas mais vermelhas seguem vermelhas ate o orcamento
    oficial daquela classe."""
    tot_n = sum(dist.values())
    if tot_n == 0 or not zones:
        return
    total_len = sum(_zlen(z) for z in zones)
    target = {c: total_len * dist.get(c, 0) / tot_n for c in range(5)}
    order = sorted(
        zones,
        key=lambda z: ((z['properties'][channel]
                        if z['properties'][channel] is not None else -1),
                       _zlen(z)),
        reverse=True)
    idx = 0
    for c in (4, 3, 2, 1, 0):
        filled = 0.0
        need = target[c]
        while idx < len(order):
            order[idx]['properties'][channel] = c
            order[idx]['properties']['fonte_' + channel[3:]] = 'tabela'
            filled += _zlen(order[idx])
            idx += 1
            if c != 0 and filled >= need:
                break
    # restante (se houver) -> classe 0
    while idx < len(order):
        order[idx]['properties'][channel] = 0
        order[idx]['properties']['fonte_' + channel[3:]] = 'tabela'
        idx += 1


def apply_hybrid(all_zones):
    """Onde a zona cai em trecho critico mapeado, calibra o RA digitalizado
    pelas proporcoes oficiais (Tabelas 3.3.3.1-3/-4). Fora, mantem a figura."""
    from core.ra_official import RA_GEO_BY_SEGMENT, RA_HID_BY_SEGMENT
    for z in all_zones:
        z['properties'].setdefault('fonte_geo', 'figura')
        z['properties'].setdefault('fonte_hid', 'figura')

    def calibrate(segmap, channel):
        for (rod, k0, k1), data in segmap.items():
            tol = 2.0 if k0 == k1 else 1.0
            lo, hi = min(k0, k1) - tol, max(k0, k1) + tol
            sel = [z for z in all_zones
                   if z['properties']['rodovia'] == rod
                   and z['properties']['km'] is not None
                   and lo <= z['properties']['km'] <= hi]
            _hist_match(sel, channel, data['dist'])

    calibrate(RA_GEO_BY_SEGMENT, 'ra_geo')
    calibrate(RA_HID_BY_SEGMENT, 'ra_hid')

    # recomputa ra (max) e fonte combinada
    for z in all_zones:
        p = z['properties']
        present = [v for v in (p['ra_geo'], p['ra_hid']) if v is not None]
        p['ra'] = max(present) if present else None
        p['fonte'] = ('tabela' if 'tabela' in (p['fonte_geo'], p['fonte_hid'])
                      else 'figura')


def get_map_image(doc, pno):
    """Retorna (np_array RGB, PIL) da maior imagem-mapa (exclui banner)."""
    pg = doc[pno - 1]
    best = None
    for img in pg.get_images(full=True):
        xref = img[0]
        w, h = img[2], img[3]
        if h < 300:           # banner/logo (muito baixo)
            continue
        area = w * h
        if best is None:
            best = (xref, area)
        elif area > best[1]:
            best = (xref, area)
    if best is None:
        raise ValueError(f"nenhuma imagem de mapa na pagina {pno}")
    ext = doc.extract_image(best[0])
    import io
    pil = Image.open(io.BytesIO(ext['image'])).convert('RGB')
    return np.asarray(pil).astype(int), pil


def _centroids(positions, gap=40):
    pos = sorted(int(p) for p in positions)
    groups, cur = [], [pos[0]]
    for p in pos[1:]:
        if p - cur[-1] > gap:
            groups.append(sum(cur) / len(cur))
            cur = [p]
        else:
            cur.append(p)
    groups.append(sum(cur) / len(cur))
    return groups


def georef(arr, E_minmax, N_minmax):
    """Ajuste linear pixel<->UTM pelos ticks extremos do grid."""
    H, _, _ = arr.shape
    gray = arr.mean(axis=2)
    botband = gray[H - 18:H, :]
    darkx = np.where((botband < 60).sum(axis=0) >= 3)[0]
    ex = _centroids(darkx)
    leftband = gray[:, 0:18]
    darky = np.where((leftband < 60).sum(axis=1) >= 3)[0]
    ny = _centroids(darky)
    # extremos -> valores min/max conhecidos
    x_lo, x_hi = min(ex), max(ex)
    y_lo, y_hi = min(ny), max(ny)   # y_lo = topo = N max
    gx0 = (x_hi - x_lo) / (E_minmax[1] - E_minmax[0])
    gx1 = x_lo - gx0 * E_minmax[0]
    gy0 = (y_hi - y_lo) / (N_minmax[0] - N_minmax[1])  # N max no topo (y menor)
    gy1 = y_lo - gy0 * N_minmax[1]
    return (gx0, gx1, gy0, gy1), (len(ex), len(ny))


def classify(rgb):
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hd = h * 360
    if v < 0.5:
        return None
    if 290 <= hd <= 350 and s > 0.30:     # magenta (limite regiao)
        return None
    if s < 0.35:
        return 0 if v > 0.65 else None     # cinza = RA0
    if hd <= 12 or hd >= 350:
        return 4 if s > 0.6 else None      # vermelho estrito
    if 12 < hd < 45:
        return 3
    if 45 <= hd < 70:
        return 2
    if 70 <= hd < 160:
        return 1
    return None


def make_sampler(arr, gref):
    H, W, _ = arr.shape
    gx0, gx1, gy0, gy1 = gref

    def sample(E, N, win=2):
        x = int(round(gx0 * E + gx1))
        y = int(round(gy0 * N + gy1))
        if x < 2 or y < 2 or x >= W - 2 or y >= H - 2:
            return None
        votes = {}
        for dy in range(-win, win + 1):
            for dx in range(-win, win + 1):
                c = classify(arr[y + dy, x + dx])
                if c is not None:
                    votes[c] = votes.get(c, 0) + 1
        if not votes:
            return None
        return max(votes, key=votes.get)
    return sample, (W, H)


def densify_line(ln, step=20.0):
    L = ln.length
    n = max(1, int(L // step))
    return [ln.interpolate(i / n, normalized=True) for i in range(n + 1)]


def main():
    doc = fitz.open(PDF)
    gdf = gpd.read_file(DER_SHP).to_crs(epsg=31983)
    rods = gdf['Rodovia'].astype(str).str.strip().str.upper()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_zones = []

    for rid, cfg in REGIONS.items():
        arr_geo, _ = get_map_image(doc, cfg['page_geo'])
        arr_hid, _ = get_map_image(doc, cfg['page_hid'])
        gref_geo, ng = georef(arr_geo, cfg['E'], cfg['N'])
        gref_hid, nh = georef(arr_hid, cfg['E'], cfg['N'])
        samp_geo, dim = make_sampler(arr_geo, gref_geo)
        samp_hid, _ = make_sampler(arr_hid, gref_hid)
        print(f"Regiao {rid}: ticks GEO {ng} HID {nh} | img {dim}")

        sub = gdf[rods == cfg['rodovia']]
        E0, E1 = cfg['E']
        N0, N1 = cfg['N']

        # overlay de validacao (sobre figura GEO escurecida)
        bg = (arr_geo.astype(float) * 0.35).astype('uint8')
        canvas = Image.fromarray(bg)
        draw = ImageDraw.Draw(canvas)
        OUTCOL = {0: (190, 190, 190), 1: (60, 230, 30), 2: (255, 240, 0),
                  3: (255, 140, 0), 4: (255, 0, 0)}
        gx0, gx1, gy0, gy1 = gref_geo

        region_zones = []
        for _, row in sub.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            km_ini = _flt(row.get('KmInicial'))
            km_fim = _flt(row.get('KmFinal'))
            lines = (geom.geoms if geom.geom_type == 'MultiLineString'
                     else [geom])
            for ln in lines:
                pts = densify_line(ln)
                n = max(1, len(pts) - 1)
                fracs = [i / n for i in range(len(pts))]
                rg_seq, rh_seq, inside = [], [], []
                for p in pts:
                    if not (E0 <= p.x <= E1 and N0 <= p.y <= N1):
                        rg_seq.append(None)
                        rh_seq.append(None)
                        inside.append(False)
                        continue
                    rg_seq.append(samp_geo(p.x, p.y))
                    rh_seq.append(samp_hid(p.x, p.y))
                    inside.append(True)
                # suaviza ao longo do tracado (remove flicker do JPEG)
                rg_seq = _smooth(rg_seq, k=5)
                rh_seq = _smooth(rh_seq, k=5)
                # desenha pontos suavizados no overlay
                for p, rg in zip(pts, rg_seq):
                    if rg is not None:
                        x = int(round(gx0 * p.x + gx1))
                        y = int(round(gy0 * p.y + gy1))
                        draw.ellipse([x-2, y-2, x+2, y+2], fill=OUTCOL[rg])
                seq = list(zip(pts, rg_seq, rh_seq, inside, fracs))
                _group_zones(seq, rid, cfg['rodovia'], km_ini, km_fim,
                             region_zones)
        all_zones.extend(region_zones)
        out_png = FIG_DIR / f'overlay_reg{rid}.png'
        canvas.save(out_png)
        n_ra = sum(1 for z in region_zones if z['properties']['ra'] is not None)
        print(f"  zonas: {len(region_zones)} (com RA: {n_ra}) -> {out_png}")

    apply_hybrid(all_zones)
    import collections
    n_tab = sum(1 for z in all_zones
                if z['properties']['fonte'] == 'tabela')
    print(f"\ncalibracao hibrida: {n_tab}/{len(all_zones)} zonas via tabela "
          f"oficial; resto via figura")

    gj = gpd.GeoDataFrame.from_features(all_zones, crs='EPSG:31983')
    gj = gj.to_crs(epsg=4326)
    out = OUT_DIR / 'ua_zones.geojson'
    gj.to_file(out, driver='GeoJSON')
    print(f"Total de zonas: {len(all_zones)} -> {out}")
    c = collections.Counter(z['properties']['ra'] for z in all_zones)
    print('zonas por RA(max):', dict(sorted(
        c.items(), key=lambda kv: (kv[0] is None, kv[0]))))


def _smooth(seq, k=5):
    """Filtro de moda em janela k (ignora None); empate -> maior classe."""
    import collections
    n = len(seq)
    half = k // 2
    out = [None] * n
    for i in range(n):
        win = [seq[j] for j in range(max(0, i - half), min(n, i + half + 1))
               if seq[j] is not None]
        if not win:
            out[i] = None
            continue
        cnt = collections.Counter(win)
        top = max(cnt.values())
        out[i] = max(c for c, v in cnt.items() if v == top)
    return out


MIN_PTS = 4   # ~80 m: zonas menores sao mescladas ao vizinho de maior risco


def _group_zones(seq, rid, rodovia, km_ini, km_fim, out):
    """Agrupa posicoes de mesmo (ra_geo,ra_hid) em zonas (LineString),
    mesclando zonas curtas no vizinho de maior risco (anti-sub-alerta)."""
    # 1) runs consecutivos de mesma chave (guarda pts e fracoes p/ km)
    runs = []  # [key, [pts], [fracs]]
    for (p, rg, rh, _inside, fr) in seq:
        key = (rg, rh)
        if runs and runs[-1][0] == key:
            runs[-1][1].append(p)
            runs[-1][2].append(fr)
        else:
            runs.append([key, [p], [fr]])

    # 2) mescla runs curtos (e None) no vizinho de maior RA, preservando o
    #    pior caso por canal (anti-sub-alerta: nunca perde um ponto de risco)
    def ra_of(key):
        present = [v for v in key if v is not None]
        return max(present) if present else -1

    def cmax(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return max(a, b)

    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (key, pts, frs) in enumerate(runs):
            # mantem runs longos (RA ou None); so mescla curtos (flicker/gap)
            if len(pts) >= MIN_PTS:
                continue
            cands = [j for j in (i - 1, i + 1) if 0 <= j < len(runs)]
            if not cands:
                continue
            tgt = max(cands, key=lambda j: ra_of(runs[j][0]))
            tk = runs[tgt][0]
            runs[tgt][0] = (cmax(tk[0], key[0]), cmax(tk[1], key[1]))
            if tgt < i:
                runs[tgt][1] = runs[tgt][1] + pts
                runs[tgt][2] = runs[tgt][2] + frs
            else:
                runs[tgt][1] = pts + runs[tgt][1]
                runs[tgt][2] = frs + runs[tgt][2]
            runs.pop(i)
            changed = True
            break

    # 3) emite zonas (descarta None: areas fora da janela / sem dado)
    for key, pts, frs in runs:
        if len(pts) < 2 or key == (None, None):
            continue
        rg, rh = key
        present = [v for v in (rg, rh) if v is not None]
        ra = max(present) if present else None
        km = None
        if km_ini is not None and km_fim is not None and frs:
            fmid = sum(frs) / len(frs)
            km = round(km_ini + fmid * (km_fim - km_ini), 2)
        out.append({
            'type': 'Feature',
            'properties': {
                'regiao': rid, 'rodovia': rodovia,
                'ra_geo': rg, 'ra_hid': rh, 'ra': ra,
                'km': km, 'fonte': 'figura',
            },
            'geometry': LineString([(p.x, p.y)
                                    for p in pts]).__geo_interface__,
        })


if __name__ == '__main__':
    main()
