#!/usr/bin/env python3
"""Build the Keighley & Worth Valley world data for index.html.

Inputs (in the cache directory given as the first argument):
  merged.json  OpenStreetMap ways/nodes for the Worth Valley corridor (from the OSM API, ODbL)
  chain.json   the KWVR running line as an ordered chain of OSM nodes, Keighley junction -> Oxenhope buffers
  dem.npy      elevation from the AWS Terrain Tiles (terrarium, zoom 14) covering the valley
Output: kwvr_data.js (a `const KW = {...}` block) and map.jpg (the line map's hillshade background), both in the cache dir.

World coordinates: metres, x east and z north of 53.842 N, 1.930 W. Distances along the line (s) are metres from the
junction with the Network Rail line at Keighley.
"""
import json, math, sys, base64, os
import numpy as np
from PIL import Image

C = sys.argv[1] if len(sys.argv) > 1 else "."
D = json.load(open(os.path.join(C, "merged.json")))
N = {int(k): v for k, v in D["nodes"].items()}
WY = {int(k): v for k, v in D["ways"].items()}
RL = {int(k): v for k, v in D["rels"].items()}
CH = json.load(open(os.path.join(C, "chain.json")))
DEM = np.load(os.path.join(C, "dem.npy"))

LAT0, LON0 = 53.8420, -1.9300
KX, KZ = 111320 * math.cos(math.radians(LAT0)), 110574


def xy(i):
    n = N[i]
    return ((n["lon"] - LON0) * KX, (n["lat"] - LAT0) * KZ)


# ---- elevation: the terrarium mosaic is tiles x 8101..8106, y 5269..5276 at zoom 14 (web mercator)
Z, TX0, TY0 = 14, 8101, 5269


def dem_at(x, z):
    lon = LON0 + x / KX
    lat = LAT0 + z / KZ
    n = 2 ** Z
    px = ((lon + 180) / 360 * n - TX0) * 256
    py = ((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n - TY0) * 256
    px = min(max(px, 0), DEM.shape[1] - 2.001)
    py = min(max(py, 0), DEM.shape[0] - 2.001)
    i, j = int(py), int(px)
    fy, fx = py - i, px - j
    a = DEM[i, j] * (1 - fx) + DEM[i, j + 1] * fx
    b = DEM[i + 1, j] * (1 - fx) + DEM[i + 1, j + 1] * fx
    return a * (1 - fy) + b * fy


# ---- the line
P = [tuple(p) for p in CH["pts"]]
cum = CH["cum"]
L = cum[-1]


def proj(p):
    """distance from the line, s along it, and side (+1 right of the up direction, towards Oxenhope)"""
    best = (1e18, 0.0, 1)
    for k in range(len(P) - 1):
        a, b = P[k], P[k + 1]
        dx, dz = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dz * dz or 1
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / l2))
        q = (a[0] + dx * t, a[1] + dz * t)
        d = math.dist(p, q)
        if d < best[0]:
            best = (d, cum[k] + t * math.dist(a, b), 1 if dx * (p[1] - a[1]) - dz * (p[0] - a[0]) < 0 else -1)
    return best


def at(s):
    s = min(max(s, 0), L)
    for k in range(len(P) - 1):
        if cum[k + 1] >= s:
            f = (s - cum[k]) / ((cum[k + 1] - cum[k]) or 1)
            return (P[k][0] + (P[k + 1][0] - P[k][0]) * f, P[k][1] + (P[k + 1][1] - P[k][1]) * f)
    return P[-1]


# a coarse grid of line points for fast "near the line" tests
LS = np.array([at(s) for s in np.arange(0, L, 10.0)])


def dline(x, z):
    return float(np.min(np.hypot(LS[:, 0] - x, LS[:, 1] - z)))


# ---- the formation: a smooth climb from Keighley to Oxenhope, fitted to the land along the line
step = 20.0
ss = np.arange(0, L + step, step)
raw = np.array([dem_at(*at(s)) for s in ss])
# isotonic (never falling) fit, then smoothed, then made never-falling again
def isotonic(y):
    blocks = [[v, 1] for v in y]
    out = []
    for v in blocks:
        out.append(v)
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            a, b = out.pop(), out.pop()
            out.append([(a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]), a[1] + b[1]])
    r = []
    for v, n in out:
        r += [v] * n
    return np.array(r)


prof = isotonic(raw)
for k in (20, 12):   # smoothed twice, a long and a shorter window, to ease the changes of grade
    pad = np.concatenate([np.full(k, prof[0]), prof, np.full(k, prof[-1])])
    prof = isotonic(np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="valid"))

# ---- stations: platform extents from the OSM platforms, side of the line they stand on (+1 right going up)
STN = [
    dict(key="KEI", name="Keighley", short="Keighley", s0=335, s1=477, side=-1, both=True),
    dict(key="ING", name="Ingrow West", short="Ingrow", s0=2219, s1=2362, side=1),
    dict(key="DAM", name="Damems", short="Damems", s0=3375, s1=3417, side=1),
    dict(key="OAK", name="Oakworth", short="Oakworth", s0=4672, s1=4764, side=1),
    dict(key="HAW", name="Haworth", short="Haworth", s0=5995, s1=6126, side=-1),
    dict(key="OXE", name="Oxenhope", short="Oxenhope", s0=7915, s1=8075, side=-1),
]
for st in STN:
    st["h"] = round(float(np.interp((st["s0"] + st["s1"]) / 2, ss, prof)), 1)

# structures along the line, from the chain's own tags
tun, bri = [], []
k = 0
TG, BG = CH["tunnel"], CH["bridge"]
while k < len(cum) - 1:
    if TG[k] or BG[k]:
        j = k
        while j + 1 < len(cum) - 1 and (TG[j + 1], BG[j + 1]) == (TG[k], BG[k]):
            j += 1
        (tun if TG[k] else bri).append([round(cum[k], 1), round(cum[j + 1], 1)])
        k = j + 1
    else:
        k += 1
TUN_NAMES = {0: "Ingrow Tunnel", 1: "Mytholmes Tunnel"}
# level crossings and signal boxes
lx, boxes = [], []
for i, n in N.items():
    t = n.get("tags", {})
    if t.get("railway") == "level_crossing":
        d, s, side = proj(xy(i))
        if d < 5:
            lx.append(round(s, 1))
    if t.get("railway") == "signal_box":
        d, s, side = proj(xy(i))
        if d < 60:
            boxes.append([round(s, 1), round(side * d, 1), t.get("name", "")])

# the shunting yard at Haworth stands on the loco yard, east of the main line just south of the station
YARD_REGION = (6140, 6560, -60, -6)   # s range and offset range it replaces


def in_yard(p):
    d, s, side = proj(p)
    o = side * d
    return YARD_REGION[0] <= s <= YARD_REGION[1] and YARD_REGION[2] <= o <= YARD_REGION[3]


# ---- terrain grid: heights (decimetres) and land cover, 25 m cells
GX0, GX1, GZ0, GZ1, GC = -3800, 3800, -5200, 5000, 25
nx, nz = int((GX1 - GX0) / GC) + 1, int((GZ1 - GZ0) / GC) + 1
H = np.zeros((nz, nx), dtype=np.uint16)
for j in range(nz):
    for i in range(nx):
        H[j, i] = int(round(dem_at(GX0 + i * GC, GZ0 + j * GC) * 10))


def ring(w):
    ns = [i for i in w["nodes"] if i in N]
    return [xy(i) for i in ns]


def poly_area(ps):
    return 0.5 * abs(sum(ps[i][0] * ps[(i + 1) % len(ps)][1] - ps[(i + 1) % len(ps)][0] * ps[i][1] for i in range(len(ps))))


# land cover codes: 0 pasture, 1 moor, 2 town, 3 industrial, 4 wood, 5 park/grass, 6 water
LC = np.zeros((nz, nx), dtype=np.uint8)
from matplotlib.path import Path as MPath  # noqa: E402

gx, gz = np.meshgrid(GX0 + np.arange(nx) * GC, GZ0 + np.arange(nz) * GC)
pts = np.column_stack([gx.ravel(), gz.ravel()])
cover = []
for w in WY.values():
    t = w.get("tags", {})
    code = None
    if t.get("landuse") in ("residential", "retail", "commercial", "garages", "religious"):
        code = 2
    elif t.get("landuse") in ("industrial", "railway", "brownfield", "construction", "quarry"):
        code = 3
    elif t.get("natural") == "wood" or t.get("landuse") == "forest":
        code = 4
    elif t.get("landuse") in ("grass", "recreation_ground", "cemetery", "allotments", "village_green") or t.get("leisure") in ("park", "pitch", "golf_course", "garden"):
        code = 5
    elif t.get("natural") in ("heath", "moor", "scrub") or t.get("landuse") == "meadow":
        code = 1 if t.get("natural") in ("heath", "moor") else None
    if code is None:
        continue
    ps = ring(w)
    if len(ps) < 4 or ps[0] != ps[-1]:
        continue
    cover.append((code, ps))
# draw the biggest first so small parks and woods show inside the town
cover.sort(key=lambda c: -poly_area(c[1]))
flat = LC.ravel()
for code, ps in cover:
    xs, zs = [p[0] for p in ps], [p[1] for p in ps]
    sel = (pts[:, 0] >= min(xs)) & (pts[:, 0] <= max(xs)) & (pts[:, 1] >= min(zs)) & (pts[:, 1] <= max(zs))
    if not sel.any():
        continue
    inside = MPath(ps).contains_points(pts[sel])
    idx = np.nonzero(sel)[0][inside]
    flat[idx] = code
LC = flat.reshape(nz, nx)
# open moor on the high ground away from the town
hm = H.astype(float) / 10
LC[(LC == 0) & (hm > 300)] = 1

# ---- buildings near the line
# type codes: 0 house, 1 terrace, 2 mill/industrial, 3 church/chapel, 4 shed/garage, 5 shop/office/public, 6 station building,
# 7 farm/barn, 8 engine shed (Oxenhope exhibition shed), 9 carriage shed, 10 goods shed (stone), 11 buffet carriage
NAMED = {}
bld = []
names = []
SPECIAL = {199169095: 8, 199168932: 9, 199168931: 10, 1105061583: 11}
for wid, w in WY.items():
    t = w.get("tags", {})
    if "building" not in t:
        continue
    ps = ring(w)
    if len(ps) < 4:
        continue
    if ps[0] == ps[-1]:
        ps = ps[:-1]
    cx, cz = sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)
    if not (GX0 < cx < GX1 and GZ0 < cz < GZ1):
        continue
    dl = dline(cx, cz)
    if dl > 1100:
        continue
    if in_yard((cx, cz)):
        continue
    b = t.get("building")
    A = poly_area(ps)
    ty = 5
    if wid in SPECIAL:
        ty = SPECIAL[wid]
    elif b in ("house", "detached", "semidetached_house", "bungalow"):
        ty = 0
    elif b in ("terrace", "residential", "apartments"):
        ty = 1
    elif b in ("industrial", "manufacture", "warehouse") or (b == "yes" and A > 1500):
        ty = 2
    elif b in ("church", "chapel") or t.get("amenity") == "place_of_worship":
        ty = 3
    elif b in ("shed", "garage", "garages", "roof", "carport", "hut") or (b == "yes" and A < 40):
        ty = 4
    elif b == "train_station":
        ty = 6
    elif b in ("farm", "barn", "farm_auxiliary", "stable"):
        ty = 7
    elif b == "yes" and A < 220:
        ty = 0
    lv = t.get("building:levels")
    try:
        lv = float(lv)
    except (TypeError, ValueError):
        lv = None
    if t.get("height"):
        try:
            h = float(str(t["height"]).split()[0])
        except ValueError:
            h = None
    else:
        h = None
    if h is None:
        if lv:
            h = lv * 3.0 + 0.6
        else:
            h = {0: 6.2, 1: 6.6, 2: 13.0 if A > 2500 else 9.5, 3: 9.0, 4: 2.6, 5: 7.5 if A < 600 else 9.0, 6: 5.5, 7: 6.0,
                 8: 8.0, 9: 6.5, 10: 7.5, 11: 3.9}[ty]
    q = [(int(round(p[0] * 2)), int(round(p[1] * 2))) for p in ps]
    if len(q) > 40:
        q = q[:: math.ceil(len(q) / 40)]
    rec = [ty, int(round(h * 10)), len(q), q[0][0], q[0][1]]
    for a, c in zip(q, q[1:]):
        rec += [c[0] - a[0], c[1] - a[1]]
    bld += rec
    nm = t.get("name")
    if nm and (ty == 3 or t.get("amenity") in ("pub",) or b == "train_station") and dl < 700:
        names.append([round(cx, 1), round(cz, 1), nm, "church" if ty == 3 else "pub" if t.get("amenity") == "pub" else "stn", round(h, 1)])
# pubs and cafes mapped as points
for i, n in N.items():
    t = n.get("tags", {})
    if t.get("amenity") == "pub" and t.get("name"):
        p = xy(i)
        if dline(*p) < 500:
            names.append([round(p[0], 1), round(p[1], 1), t["name"], "pub", 0])
    if t.get("tourism") == "museum" and t.get("name") and dline(*xy(i)) < 900:
        p = xy(i)
        names.append([round(p[0], 1), round(p[1], 1), t["name"], "museum", 0])


def poly_rec(ps, extra):
    q = [(int(round(p[0] * 2)), int(round(p[1] * 2))) for p in ps]
    rec = extra + [len(q), q[0][0], q[0][1]]
    for a, c in zip(q, q[1:]):
        rec += [c[0] - a[0], c[1] - a[1]]
    return rec


def near_any(ps, r):
    return any(dline(*p) < r for p in ps[:: max(1, len(ps) // 6)])


# ---- roads: class code, width (dm), bridge flag
RW = {"trunk": (0, 90), "primary": (0, 85), "secondary": (1, 75), "tertiary": (2, 65), "unclassified": (3, 55),
      "residential": (4, 55), "living_street": (4, 50), "service": (5, 35), "pedestrian": (6, 40)}
roads = []
for w in WY.values():
    t = w.get("tags", {})
    hw = t.get("highway")
    if hw not in RW:
        continue
    ps = ring(w)
    if len(ps) < 2 or not near_any(ps, 1300 if RW[hw][0] < 4 else 800):
        continue
    if hw == "service" and not near_any(ps, 350):
        continue
    if any(in_yard(p) for p in ps):
        continue
    br = 1 if t.get("bridge") in ("yes", "viaduct") else 0
    roads += poly_rec(ps, [RW[hw][0], RW[hw][1], br])
# ---- drystone walls and hedges
walls = []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("barrier") not in ("wall", "hedge", "retaining_wall"):
        continue
    ps = ring(w)
    if len(ps) < 2 or not near_any(ps, 900) or any(in_yard(p) for p in ps):
        continue
    walls += poly_rec(ps, [1 if t["barrier"] == "hedge" else 0])
# ---- water: rivers and becks as lines, ponds and reservoirs as polygons
rivers, lakes = [], []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("waterway") in ("river", "stream", "canal") and t.get("tunnel") not in ("culvert", "yes"):
        ps = ring(w)
        if len(ps) >= 2 and near_any(ps, 2500):
            wd = {"river": 9, "canal": 12, "stream": 3}[t["waterway"]]
            rivers += poly_rec(ps, [wd])
    if t.get("natural") == "water" and t.get("water") not in ("wastewater",):
        ps = ring(w)
        if len(ps) >= 4 and ps[0] == ps[-1] and near_any(ps, 3000):
            lakes += poly_rec(ps[:-1], [0])
for r in RL.values():
    t = r.get("tags", {})
    if t.get("natural") == "water":
        for m in r.get("members", []):
            if m.get("type") == "way" and m.get("role") == "outer" and m["ref"] in WY:
                ps = ring(WY[m["ref"]])
                if len(ps) >= 4 and ps[0] == ps[-1]:
                    lakes += poly_rec(ps[:-1], [0])
# ---- woods
woods = []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("natural") == "wood" or t.get("landuse") == "forest":
        ps = ring(w)
        if len(ps) >= 4 and ps[0] == ps[-1] and near_any(ps, 1600):
            woods += poly_rec(ps[:-1], [0])
# ---- other railway: sidings, yards and the Network Rail line through Keighley
chain_nodes = set(CH["path"])
rails = []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("railway") not in ("rail",):
        continue
    ns = [i for i in w["nodes"] if i in N]
    if len(ns) < 2 or all(i in chain_nodes for i in ns):
        continue
    ps = [xy(i) for i in ns]
    if any(in_yard(p) for p in ps):
        continue
    if not near_any(ps, 900):
        continue
    nr = 1 if t.get("usage") == "main" or "Airedale" in t.get("name", "") else 0
    br = 1 if t.get("bridge") else 0
    rails += poly_rec(ps, [nr, br])
plats = []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("railway") == "platform" and t.get("ref") in ("1", "2"):
        ps = ring(w)
        if len(ps) >= 4 and dline(*ps[0]) < 200:
            plats += poly_rec(ps[:-1], [0])
turntables = []
for w in WY.values():
    if w.get("tags", {}).get("railway") == "turntable":
        ps = ring(w)
        cx, cz = sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)
        r = max(math.dist((cx, cz), p) for p in ps)
        turntables.append([round(cx, 1), round(cz, 1), round(r, 1)])


def b64u16(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype="<u2").tobytes()).decode()


def b64u8(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.uint8).tobytes()).decode()


# ---- the line map: rotated so the line runs from Keighley at the bottom left to Oxenhope at the top right
kx, kz = at(400)
ox, oz = at(8000)
ang = math.atan2(oz - kz, ox - kx)              # direction Keighley -> Oxenhope
rot = math.radians(32) - ang                     # turn it to point up and to the right at 32 degrees
cr, sr = math.cos(rot), math.sin(rot)
MW, MH = 1000, 620
# fit the turned line into the map with margins
def turned(x, z):
    return (x * cr - z * sr, x * sr + z * cr)
tl = [turned(*p) for p in P]
ux = [p[0] for p in tl]; uz = [p[1] for p in tl]
scale = min((MW - 260) / (max(ux) - min(ux)), (MH - 170) / (max(uz) - min(uz)))
cxm, czm = (max(ux) + min(ux)) / 2, (max(uz) + min(uz)) / 2
def tomap(x, z):
    u, v = turned(x, z)
    return (round(MW / 2 + (u - cxm) * scale, 1), round(MH / 2 - (v - czm) * scale, 1))
def frommap(mx, my):
    u = (mx - MW / 2) / scale + cxm
    v = -(my - MH / 2) / scale + czm
    # inverse rotation
    return (u * cr + v * sr, -u * sr + v * cr)
# hillshade background with land cover tints
img = np.zeros((MH, MW, 3))
for my in range(MH):
    for mx in range(MW):
        x, z = frommap(mx, my)
        if not (-4500 < x < 4050 and -5950 < z < 5400):   # beyond the elevation data
            img[my, mx] = (226, 230, 214); continue
        h = dem_at(x, z)
        hx = dem_at(x + 15, z) - dem_at(x - 15, z)
        hz = dem_at(x, z + 15) - dem_at(x, z - 15)
        nx_, nz_, ny_ = -hx / 10, -hz / 10, 1.0   # the relief shown three times as steep, to read clearly
        l = (nx_ * -0.6 + ny_ * 0.75 + nz_ * 0.45) / math.sqrt(nx_ * nx_ + ny_ * ny_ + nz_ * nz_)
        ci, cj = int((z - GZ0) / GC), int((x - GX0) / GC)
        code = LC[ci, cj] if 0 <= ci < nz and 0 <= cj < nx else (1 if h > 300 else 0)
        base = {0: (226, 233, 206), 1: (216, 199, 208), 2: (226, 216, 206), 3: (214, 210, 204), 4: (190, 214, 176),
                5: (214, 232, 196), 6: (170, 200, 220)}[int(code)]
        if code == 0 and h > 260:
            base = (222, 218, 200)
        k_ = 0.55 + 0.55 * max(0.0, l)
        img[my, mx] = [min(255, c * k_) for c in base]
Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(os.path.join(C, "map.jpg"), quality=72, optimize=True)
# vector layers for the map: the river, the main roads and the reservoirs
def svgpath(ps):
    q = [tomap(*p) for p in ps]
    return "M" + " L".join(f"{a:.0f},{b:.0f}" for a, b in q)
map_rivers, map_roads, map_lakes = [], [], []
for w in WY.values():
    t = w.get("tags", {})
    if t.get("waterway") == "river" or (t.get("waterway") == "stream" and t.get("name") in ("Bridgehouse Beck", "North Beck", "Leeming Water")):
        map_rivers.append(svgpath(ring(w)))
    if t.get("highway") in ("trunk", "primary", "secondary", "tertiary"):
        map_roads.append([svgpath(ring(w)), {"trunk": 3, "primary": 3, "secondary": 2, "tertiary": 1}[t["highway"]], t.get("ref", "")])
for r in RL.values():
    if r.get("tags", {}).get("natural") == "water":
        for m in r.get("members", []):
            if m.get("type") == "way" and m.get("role") == "outer" and m["ref"] in WY:
                map_lakes.append(svgpath(ring(WY[m["ref"]])))
for w in WY.values():
    t = w.get("tags", {})
    if t.get("natural") == "water" and t.get("water") == "reservoir":
        map_lakes.append(svgpath(ring(w)))
# the line on the map, every 40 m, with its distance along
mline = [[*tomap(*at(s)), round(s, 1)] for s in np.arange(0, L, 40.0)] + [[*tomap(*P[-1]), round(L, 1)]]
mstn = [list(tomap(*at((st["s0"] + st["s1"]) / 2))) for st in STN]
north = [round(-math.sin(rot) * 1, 4), round(-math.cos(rot) * 1, 4)]   # screen direction of north
out = dict(
    o=[LAT0, LON0], L=round(L, 1),
    line=[[round(p[0], 2), round(p[1], 2)] for p in P],
    prof=[round(float(v), 2) for v in prof], profStep=step,
    stn=STN, tun=tun, bri=bri, lx=lx, boxes=boxes,
    grid=dict(x0=GX0, z0=GZ0, cell=GC, nx=nx, nz=nz, h=b64u16(H), lc=b64u8(LC)),
    bld=bld, names=names, roads=roads, walls=walls, rivers=rivers, lakes=lakes, woods=woods, rails=rails, plats=plats,
    tt=turntables,
    map=dict(line=mline, stn=mstn, rivers=map_rivers, roads=map_roads, lakes=map_lakes, north=north, scale=round(scale, 5)),
)
js = "const KW = " + json.dumps(out, separators=(",", ":")) + ";\n"
open(os.path.join(C, "kwvr_data.js"), "w").write(js)
print("bytes", len(js), "buildings", sum(1 for _ in range(0)), "stations", [(s["name"], s["h"]) for s in STN])
print("tunnels", tun, "bridges", bri, "crossings", lx, "boxes", boxes)
print("sizes", {k: len(json.dumps(v)) for k, v in out.items()})
print("prof ends", prof[0], prof[-1], "max grade 1 in", round(step / max(np.diff(prof).max(), 1e-6)))
