import json, sys, math

src, out, step = sys.argv[1], sys.argv[2], float(sys.argv[3])
topo = json.load(open(src))
tr = topo.get("transform")
sc, tl = tr["scale"], tr["translate"]

def decode_arc(arc):
    x = y = 0
    pts = []
    for dx, dy in arc:
        x += dx; y += dy
        pts.append((x * sc[0] + tl[0], y * sc[1] + tl[1]))
    return pts

arcs = [decode_arc(a) for a in topo["arcs"]]

def ring(arc_idx):
    pts = []
    for i in arc_idx:
        a = arcs[~i][::-1] if i < 0 else arcs[i]
        if pts: a = a[1:]
        pts.extend(a)
    return pts

polys = []  # list of (outer ring, [holes]) -- just treat all rings with even-odd rule
for g in topo["objects"]["land"]["geometries"]:
    if g["type"] == "Polygon":
        polys.append([ring(r) for r in g["arcs"]])
    elif g["type"] == "MultiPolygon":
        for p in g["arcs"]:
            polys.append([ring(r) for r in p])

# Build per-polygon bbox and edges for even-odd test
shapes = []
for rings in polys:
    allx = [p[0] for r in rings for p in r]; ally = [p[1] for r in rings for p in r]
    shapes.append((min(allx), max(allx), min(ally), max(ally), rings))

def inside(lon, lat):
    for minx, maxx, miny, maxy, rings in shapes:
        if lon < minx or lon > maxx or lat < miny or lat > maxy: continue
        c = False
        for r in rings:
            n = len(r)
            for i in range(n):
                x1, y1 = r[i]; x2, y2 = r[(i + 1) % n]
                if (y1 > lat) != (y2 > lat):
                    xi = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                    if lon < xi: c = not c
        if c: return True
    return False

pts = []
lat = -85.0
while lat <= 85.0:
    # equal-area-ish: widen lon step at high latitude
    coslat = max(math.cos(math.radians(lat)), 0.15)
    lstep = step / coslat
    lon = -180.0 + (lstep / 2) * ((round(lat / step)) % 2)
    while lon < 180.0:
        if inside(lon, lat):
            pts.append([round(lat, 1), round(((lon + 180) % 360) - 180, 1)])
        lon += lstep
    lat += step

with open(out, "w") as f:
    f.write(json.dumps(pts, separators=(",", ":")))
print(len(pts), "points")
