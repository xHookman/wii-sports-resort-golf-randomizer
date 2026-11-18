"""Mode « Nintendo + variations » : on part de la carte officielle intacte (eau, berges, ilots, falaises,
decor) et on ne regenere que la zone de jeu : fairway, rough, bunkers, green et emplacements de drapeau,
sur les hauteurs exactes de Nintendo. Le relief et les arbres viennent ensuite de la Wii (gen.c).

Sortie : meme dictionnaire que gen.generate (build.py et validate le consomment), avec nmode=True.
"""
import math, random, collections
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, Point, LineString, box
from shapely.ops import unary_union
from shapely.prepared import prep
from scipy.interpolate import LinearNDInterpolator
import shapely as sh
from gen import (blob, rounded, fairway_shape, Noise, FOLIE, FORMS, FORMS_SAGES, FORMS_FOLLES, BUNKERS,
                 CUP_R, GREEN_UNDUL, bezier)

PLAY = {'M_Fairway', 'M_Rough', 'M_Green', 'M_Bunker', 'M_Color'}
GROUND = PLAY | {'M_OB'}
DECAL = {'M_Kiwa_R', 'M_Kiwa_F', 'M_Kiwa_OB', 'M_Kiwa_Bunker', 'M_Kiwa_Black'}
MARGIN = 15.0         # distance minimale a l'eau, la roche, la plage, le decor
CORR = 1100.0         # couloir autour de l'axe depart -> drapeau de Nintendo
import os
V23 = os.environ.get('NMODE') == '2'
import ponds


def _tris_of(tpl, mats):
    out = []
    for n, tl in tpl.vt.items():
        mt = tpl.o2m.get(n)
        if mt not in mats: continue
        for t in tl:
            if min(v['pos'][1] for v in t) < -8000: continue
            out.append((mt, t))
    return out


class Ground:
    """Surface exacte de Nintendo (triangles du sol), anciens bunkers combles."""
    def __init__(self, tpl):
        tr_ = [t for mt, t in _tris_of(tpl, GROUND - {'M_Bunker'})]
        A = np.array([[v['pos'] for v in t] for t in tr_], float)          # (n, 3, 3)
        self.A = A
        self.clr = [t for t in tr_]
        self.mat = [mt for mt, t in _tris_of(tpl, GROUND - {'M_Bunker'})]
        xz = A[:, :, [0, 2]]
        self.lo = xz.min(1); self.hi = xz.max(1)
        self.cs = 60.0
        self.x0, self.z0 = self.lo.min(0) - 1
        nx = int((self.hi[:, 0].max() - self.x0) / self.cs) + 2; nz = int((self.hi[:, 1].max() - self.z0) / self.cs) + 2
        self.nx, self.nz = nx, nz
        cells = collections.defaultdict(list)
        for i in range(len(A)):
            i0, j0 = int((self.lo[i, 0] - self.x0) / self.cs), int((self.lo[i, 1] - self.z0) / self.cs)
            i1, j1 = int((self.hi[i, 0] - self.x0) / self.cs), int((self.hi[i, 1] - self.z0) / self.cs)
            for a in range(i0, i1 + 1):
                for b in range(j0, j1 + 1): cells[(a, b)].append(i)
        self.cells = {k: np.array(v) for k, v in cells.items()}
        pts = A.reshape(-1, 3)
        self.fill = LinearNDInterpolator(pts[:, [0, 2]], pts[:, 1])        # comble les anciens bunkers

    def locate(self, x, z):
        ids = self.cells.get((int((x - self.x0) / self.cs), int((z - self.z0) / self.cs)))
        if ids is None: return None
        best = None
        for i in ids:
            a, b, c = self.A[i]
            v0x, v0z = c[0] - a[0], c[2] - a[2]; v1x, v1z = b[0] - a[0], b[2] - a[2]
            den = v0x * v1z - v1x * v0z
            if abs(den) < 1e-9: continue
            v2x, v2z = x - a[0], z - a[2]
            u = (v2x * v1z - v1x * v2z) / den; w = (v0x * v2z - v2x * v0z) / den
            if u < -1e-6 or w < -1e-6 or u + w > 1 + 1e-6: continue
            h = a[1] + u * (c[1] - a[1]) + w * (b[1] - a[1])
            if best is None or h > best[0]: best = (h, i, u, w)
        return best

    def h(self, x, z):
        r = self.locate(x, z)
        if r is not None: return float(r[0])
        v = self.fill(x, z)
        return float(v) if np.isfinite(v) else 0.0

    def color(self, x, z):
        """(materiau, rgba) du sol de Nintendo en (x, z), ou None."""
        r = self.locate(x, z)
        if r is None: return None
        _, i, u, w = r
        t = self.clr[i]
        if 'clr0' not in t[0]: return None
        ca, cb, cc = (np.array(v['clr0'], float) for v in t)
        c = ca + u * (cc - ca) + w * (cb - ca)
        return self.mat[i], tuple(int(round(min(255, max(0, q)))) for q in c)


def zone(tpl, keep_green=False):
    """Zone modifiable : triangles de jeu de Nintendo loin de l'eau / roche / decor, dans le couloir.
    keep_green : le green de Nintendo (et ses emplacements de drapeau) est garde tel quel, hors zone.
    v23 (NMODE=2) : les etangs interieurs font partie de la zone (ils sont deplaces par generate_n)."""
    ck = ('_nzone_kg' if keep_green else '_nzone') + ('23' if V23 else '')
    if getattr(tpl, ck, None) is not None: return getattr(tpl, ck)
    t0 = [o for o in tpl.pmp if (o['grp'], o['typ']) == (2, 0)][0]['pos']
    g0 = [o for o in tpl.pmp if (o['grp'], o['typ']) == (11, 1)][0]['pos']
    cor = LineString([(t0[0], t0[2]), (g0[0], g0[2])]).buffer(CORR)
    holes = [h for h, _, _ in ponds.find_holes(tpl) if h.intersects(cor)] if V23 else []
    hp_ = prep(unary_union(holes).buffer(1)) if holes else None
    play, bad = [], []
    for mt, t in _tris_of(tpl, set(tpl.o2m.values())):
        pg = Polygon([(v['pos'][0], v['pos'][2]) for v in t])
        if pg.area < 0.01: continue
        if hp_ is not None and hp_.contains(pg.centroid): continue
        if mt in PLAY: play.append(pg)
        elif mt not in GROUND and mt not in DECAL and pg.area < 2e5: bad.append(pg)
    badu = unary_union([b for b in bad if b.intersects(cor.buffer(300))]).buffer(MARGIN) if bad else Polygon()
    if keep_green:
        gk = green_keep_poly(tpl, (g0[0], g0[2]))
        badu = unary_union([badu, gk.buffer(25)])
    badp = prep(badu)
    keep = [p for p in play if p.intersects(cor) and not badp.intersects(p)]
    # un bunker de Nintendo est entierement dans la zone ou entierement dehors (avec 30 de marge) :
    # sinon une moitie comblee et l'autre en creux -> marche dans le sol
    bk = [Polygon([(v['pos'][0], v['pos'][2]) for v in t]) for mt, t in _tris_of(tpl, {'M_Bunker'})]
    bk = [p for p in bk if p.area > 0.01]
    if bk:
        keep_p = prep(unary_union([p.buffer(0.05) for p in keep]))
        cut = []
        for c in getattr(unary_union([p.buffer(0.3) for p in bk]), 'geoms', [unary_union([p.buffer(0.3) for p in bk])]):
            if not keep_p.contains(c.buffer(-0.35)): cut.append(c.buffer(30))
        if cut:
            cutp = prep(unary_union(cut)); keep = [p for p in keep if not cutp.intersects(p)]
    E = unary_union([p.buffer(0.02, join_style=2) for p in keep] + [h.buffer(0.02, join_style=2) for h in holes]).buffer(-0.02, join_style=2)
    comps = [c for c in getattr(E, 'geoms', [E]) if c.area > 20000]
    # trous minuscules (triangles isoles exclus) : bouches
    comps = [Polygon(c.exterior, [h for h in c.interiors if Polygon(h).area > 5000]) for c in comps]
    E = MultiPolygon(comps) if len(comps) > 1 else comps[0]
    setattr(tpl, ck, (E, (t0[0], t0[2]), (g0[0], g0[2])))
    return getattr(tpl, ck)


def green_keep_poly(tpl, g0):
    """Green + avant-green de Nintendo autour du drapeau (gardes tels quels en mode keep_green)."""
    ps = [Polygon([(v['pos'][0], v['pos'][2]) for v in t]) for mt, t in _tris_of(tpl, {'M_Green', 'M_Color'})]
    ps = [p for p in ps if p.area > 0.01 and p.centroid.distance(Point(g0)) < 450]
    return unary_union([p.buffer(0.05) for p in ps]) if ps else Point(g0).buffer(150)


def _green_radius(tpl, g0):
    a = 0.0
    for mt, t in _tris_of(tpl, {'M_Green'}):
        pg = Polygon([(v['pos'][0], v['pos'][2]) for v in t])
        if pg.centroid.distance(Point(g0)) < 400: a += pg.area
    return max(95.0, min(170.0, math.sqrt(a / math.pi))) if a > 0 else 130.0


def _astar(Z, a, b, cs=25.0):
    """Plus court chemin dans le polygone Z (grille de cs), cout plus fort pres des bords."""
    import heapq
    if Z.is_empty: return None
    x0, z0, x1, z1 = Z.bounds
    nx, nz = int((x1 - x0) / cs) + 1, int((z1 - z0) / cs) + 1
    xs = x0 + cs * np.arange(nx); zs = z0 + cs * np.arange(nz)
    X, Zg = np.meshgrid(xs, zs)
    pts = sh.points(X.ravel(), Zg.ravel())
    ins = sh.contains(Z, pts).reshape(nz, nx)
    dist = np.where(ins, sh.distance(Z.boundary, pts).reshape(nz, nx), 0)
    def cell(p): return (int(round((p[1] - z0) / cs)), int(round((p[0] - x0) / cs)))
    def near_in(c):
        best = None
        for dj in range(-6, 7):
            for di in range(-6, 7):
                j, i = c[0] + dj, c[1] + di
                if 0 <= j < nz and 0 <= i < nx and ins[j, i]:
                    d = dj * dj + di * di
                    if best is None or d < best[0]: best = (d, (j, i))
        return best[1] if best else None
    s0, s1 = near_in(cell(a)), near_in(cell(b))
    if s0 is None or s1 is None: return None
    INF = 1e18; g = {s0: 0.0}; prev = {}; pq = [(0.0, s0)]
    while pq:
        f, c = heapq.heappop(pq)
        if c == s1: break
        for dj, di, w in ((1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)):
            j, i = c[0] + dj, c[1] + di
            if not (0 <= j < nz and 0 <= i < nx and ins[j, i]): continue
            ng = g[c] + w * (1.0 + 3.0 / (1.0 + dist[j, i] / 60.0))
            if ng < g.get((j, i), INF):
                g[(j, i)] = ng; prev[(j, i)] = c
                hh = math.hypot(j - s1[0], i - s1[1])
                heapq.heappush(pq, (ng + hh, (j, i)))
    if s1 not in g: return None
    out = [s1]
    while out[-1] != s0: out.append(prev[out[-1]])
    out.reverse()
    return [a] + [(xs[i], zs[j]) for j, i in out[1:-1]] + [b]


def _smooth(pts, n=200):
    ls = LineString(pts).simplify(40)
    p = list(ls.coords)
    for _ in range(4):
        q = [p[0]]
        for a_, b_ in zip(p, p[1:]):
            q += [(0.75 * a_[0] + 0.25 * b_[0], 0.75 * a_[1] + 0.25 * b_[1]), (0.25 * a_[0] + 0.75 * b_[0], 0.25 * a_[1] + 0.75 * b_[1])]
        q.append(p[-1]); p = q
    ls = LineString(p)
    return [(ls.interpolate(t, normalized=True).x, ls.interpolate(t, normalized=True).y) for t in np.linspace(0, 1, n)]


def generate_n(tpl, seed, par=4):
    rng = random.Random(seed)
    noise = Noise(rng)
    fol = FOLIE.get(tpl.name, 1)
    E, t0, g0 = zone(tpl)
    if not hasattr(tpl, '_nground'): tpl._nground = Ground(tpl)
    GR = tpl._nground
    comps = list(getattr(E, 'geoms', [E]))
    cg = [c for c in comps if c.buffer(5).contains(Point(g0))]
    ct = [c for c in comps if c.buffer(5).contains(Point(t0))]
    if not ct: raise RuntimeError('depart hors de la zone modifiable')
    gr0_ = _green_radius(tpl, g0)
    # green de Nintendo trop serre (eau, roche) : on le garde tel quel avec ses emplacements de drapeau
    keep_green = not cg or cg[0].area < 2.5 * math.pi * gr0_ ** 2 or cg[0].boundary.distance(Point(g0)) < gr0_ + 30
    if keep_green:
        E, t0, g0 = zone(tpl, keep_green=True)
        comps = list(getattr(E, 'geoms', [E]))
        ct = [c for c in comps if c.buffer(5).contains(Point(t0))]
        if not ct: raise RuntimeError('depart hors de la zone modifiable')
        cg = []
    Et = ct[0]; Eg = cg[0] if cg else None
    REJ = collections.Counter()

    # ---------------------------------------------------------- depart et green
    D0 = math.dist(t0, g0); u = ((g0[0] - t0[0]) / D0, (g0[1] - t0[1]) / D0); nv = (-u[1], u[0])
    span = (60, 90, 130)[fol]
    tee = t0
    for _ in range(80):
        s = rng.uniform(-span, span * 1.3); lat = rng.uniform(-50, 50)
        q = (t0[0] - u[0] * s + nv[0] * lat, t0[1] - u[1] * s + nv[1] * lat)
        if Et.buffer(-95).contains(Point(q)): tee = q; break
    else:
        REJ['depart'] += 1
    gr0 = gr0_
    green = g0
    # nouveau green ailleurs sur la terre : direction a +-45 deg de l'axe de Nintendo (cadre de la minimap),
    # longueur 0,75-1,15 x Nintendo, loin du green d'origine -> on redecouvre le trou
    D0n = math.dist(t0, g0); ang0 = math.atan2(g0[1] - t0[1], g0[0] - t0[0])
    xb0, zb0, xb1, zb1 = E.bounds
    frame = box(min(t0[0], g0[0]) - 900, min(t0[1], g0[1]) - 900, max(t0[0], g0[0]) + 900, max(t0[1], g0[1]) + 900)
    lands = [c for c in comps if c.area > 4 * math.pi * gr0 ** 2]
    cand = []
    _rg = random.Random(seed * 5381 + 17)
    for _ in range(1500):
        q = (_rg.uniform(xb0, xb1), _rg.uniform(zb0, zb1))
        d = math.dist(tee, q)
        if not (0.75 * D0n <= d <= 1.2 * D0n): continue
        da = math.atan2(q[1] - tee[1], q[0] - tee[0]) - ang0; da = (da + math.pi) % (2 * math.pi) - math.pi
        if abs(da) > math.radians(50) or not frame.contains(Point(q)): continue
        if math.dist(q, g0) < 350: continue
        Lq = [c for c in lands if c.buffer(-(gr0 + 60)).contains(Point(q))]
        if not Lq: continue
        cand.append((q, Lq[0]))
    if cand:
        cand.sort(key=lambda c: -math.dist(c[0], g0))                    # les plus eloignes du green d'origine
        green, Eg = cand[_rg.randrange(max(1, int(len(cand) * 0.4)))]
        keep_green = False; moved_green = True
    else:
        moved_green = False
    for k in range(0 if keep_green else 40):
        gr = gr0 * rng.uniform(1.0, 1.2) * (1 - 0.01 * k)
        green_p = blob(green[0], green[1], gr, rng, 0.10 + 0.03 * fol, stretch=rng.uniform(0.9, 1.25), ang=rng.uniform(0, 3.14))
        green_p = green_p.intersection(Eg.buffer(-40))
        if isinstance(green_p, Polygon) and green_p.area > 0.75 * math.pi * gr * gr * 0.8 and green_p.contains(Point(green)):
            break
    else:
        if keep_green:
            gr = gr0; green_p = Polygon()
        else:
            green_p = Point(green).buffer(gr0 * 0.8).intersection(Eg.buffer(-35))
            if not isinstance(green_p, Polygon): raise RuntimeError('green impossible')
            gr = gr0 * 0.8
    if not green_p.is_empty: green_p = rounded(green_p, 25)

    # ---------------------------------------------------------- v23 : coupure du fairway et etangs deplaces
    _rc = random.Random(seed * 911 + 5)
    old_ponds = [(h, mt, y) for h, mt, y in ponds.find_holes(tpl) if E.buffer(1).contains(h)] if V23 else []
    cut = None
    if V23 and _rc.random() < (0.6 if par == 3 else 0.5):
        w_ = [('lac', 0.4 if old_ponds else 0), ('sable', 0.25 if 'M_Bunker' in set(tpl.o2m.values()) else 0), ('arbres', 0.25 if par > 3 else 0), ('rough', 0.1 if par > 3 else 0)]
        r_ = _rc.uniform(0, sum(w for _, w in w_))
        for k_, w in w_:
            if r_ < w: cut = k_; break
            r_ -= w
    moves, new_holes = [], []
    gpoly_ = green_p if not green_p.is_empty else Point(green).buffer(gr)
    D_ = math.dist(tee, green)
    # regle : un etang deplace ne doit avoir aucun autre plan d'eau dessous (la mer passe sous la terre :
    # elle se verrait a travers l'eau translucide d'un lac, fcJP6)
    _sea = []
    if old_ponds:
        for mt_, t_ in _tris_of(tpl, ponds.WATER_M):
            q_ = Polygon([(v['pos'][0], v['pos'][2]) for v in t_])
            if q_.area > 0.01 and not any(q_.intersects(h_.buffer(5)) and q_.area < ponds.BIG for h_, _, _ in old_ponds): _sea.append(q_)
    seaP = prep(unary_union(_sea).buffer(25)) if _sea else None
    for k_, (h, mt, y) in enumerate(old_ponds):
        c0 = (h.centroid.x, h.centroid.y); Rh = math.sqrt(h.area / math.pi)
        ug_ = ((green[0] - tee[0]) / D_, (green[1] - tee[1]) / D_)
        best_ = None
        for t_ in range(400):
            th = _rc.uniform(0, 2 * math.pi); sc = _rc.uniform(0.7, 1.3) if t_ < 300 else 0.7
            if cut == 'lac' and k_ == 0 and t_ < 250:
                f = _rc.uniform(0.35, 0.65) if par > 3 else _rc.uniform(0.45, 0.7); lat = _rc.uniform(-60, 60)
            else:
                f = _rc.uniform(0.15, 0.85); lat = _rc.choice((-1, 1)) * (Rh * sc + _rc.uniform(120, 320))
            c1 = (tee[0] + ug_[0] * f * D_ - ug_[1] * lat, tee[1] + ug_[1] * f * D_ + ug_[0] * lat)
            mv = ponds.Move(c0, c1, th, sc, 0.0); hn = mv.poly(h)
            if not hn.is_valid: continue
            if not E.buffer(-120).contains(hn): continue
            if seaP is not None and seaP.intersects(hn): continue
            lac_ = cut == 'lac' and k_ == 0 and par > 3
            if hn.distance(Point(tee)) < (650 if lac_ else 200) or hn.distance(gpoly_) < (gr + 300 if lac_ else 160): continue
            if any(hn.distance(q) < 150 for q in new_holes): continue
            best_ = (mv, hn); break
        if best_ is None:                                   # contraintes relachees : n'importe ou dans la zone
            bx0, bz0, bx1, bz1 = E.bounds
            for t_ in range(600):
                th = _rc.uniform(0, 2 * math.pi); sc = _rc.uniform(0.6, 1.0)
                c1 = (_rc.uniform(bx0, bx1), _rc.uniform(bz0, bz1))
                mv = ponds.Move(c0, c1, th, sc, 0.0); hn = mv.poly(h)
                if not hn.is_valid or not E.buffer(-60).contains(hn): continue
                if seaP is not None and seaP.intersects(hn): continue
                if hn.distance(Point(tee)) < 150 or hn.distance(gpoly_) < 130: continue
                if any(hn.distance(q) < 120 for q in new_holes): continue
                best_ = (mv, hn); break
            if cut == 'lac' and k_ == 0: cut = None
        if best_ is None:                                   # dernier recours : reste a sa place (si rien ne gene)
            mv = ponds.Move(c0, c0, 0.0, 1.0, 0.0); hn = mv.poly(h)
            if hn.distance(Point(tee)) < 100 or hn.distance(gpoly_) < 70: raise RuntimeError('etang : aucune place')
            best_ = (mv, hn)
        mv, hn = best_
        r0 = [GR.h(x, z) for x, z in h.exterior.coords]; r1 = [GR.h(*mv.xz(x, z)) for x, z in h.exterior.coords]
        mv.dy = float(np.median(r1) - np.median(r0))
        moves.append((h, mv, mt, y)); new_holes.append(hn)
    holesU = unary_union(new_holes) if new_holes else Polygon()
    if cut == 'lac' and not moves: cut = None

    # ---------------------------------------------------------- trace : suit la terre (plus court chemin dans
    # la zone, centre prefere) par un point de passage tire au hasard -> varie d'une partie a l'autre
    single = Eg is not None and Et.equals(Eg)
    def route(a, b, Z):
        return _astar(Z, a, b)
    # style du trace (cahier des charges) : droit, virage franc (dogleg) ou double virage (S)
    _rs = random.Random(seed * 7121 + 3)
    style = _rs.choice(['droit', 'dogleg', 'dogleg', 'S']) if par > 3 else _rs.choice(['droit', 'droit', 'dogleg'])
    if V23: style = _rs.choice(['dogleg'] * 9 + ['S'] * 7 + ['inflexions'] * 4) if par > 3 else 'leger'
    Lg = math.dist(tee, green); ug = ((green[0] - tee[0]) / Lg, (green[1] - tee[1]) / Lg); ng = (-ug[1], ug[0])
    def wpt(f, lat): return (tee[0] + ug[0] * f * Lg + ng[0] * lat * Lg, tee[1] + ug[1] * f * Lg + ng[1] * lat * Lg)
    if single:
        Zr = Et.buffer(-70)
        if V23 and moves:                                   # etangs a contourner (sauf celui que le trace traverse)
            side_ = [hn for j_, hn in enumerate(new_holes) if not (cut == 'lac' and j_ == 0)]
            if side_: Zr = Zr.difference(unary_union(side_).buffer(110))
        best = None; ref_ = None
        if V23:                                             # virages mesures par rapport au chemin naturel (suit la terre)
            rr_ = route(tee, green, Zr)
            if rr_:
                refL = LineString(rr_); ref_ = refL.length
                def wpt(f, lat):
                    p_ = refL.interpolate(f * ref_); q_ = refL.interpolate(min(ref_, f * ref_ + 5)); o_ = refL.interpolate(max(0, f * ref_ - 5))
                    dx, dz = q_.x - o_.x, q_.y - o_.y; nn_ = math.hypot(dx, dz) or 1
                    lg_ = min(Lg, 1100.0)
                    return (p_.x - dz / nn_ * lat * lg_, p_.y + dx / nn_ * lat * lg_)
        for k in range(40):
            sg_ = _rs.choice((-1, 1)); shrink = 1 - k / 50.0
            if style == 'dogleg': wps = [wpt(_rs.uniform(0.5, 0.68), sg_ * _rs.uniform(0.16, 0.3) * shrink)]
            elif style == 'S': wps = [wpt(_rs.uniform(0.28, 0.4), sg_ * _rs.uniform(0.12, 0.22) * shrink), wpt(_rs.uniform(0.62, 0.74), -sg_ * _rs.uniform(0.12, 0.22) * shrink)]
            elif style == 'inflexions': wps = [wpt(0.25 + 0.25 * j_ + _rs.uniform(-0.04, 0.04), (-1) ** j_ * sg_ * _rs.uniform(0.06, 0.11) * shrink) for j_ in range(3)]
            elif style == 'leger': wps = [wpt(_rs.uniform(0.4, 0.6), sg_ * _rs.uniform(0.08, 0.15) * shrink)]
            else: wps = []
            if not all(Et.buffer(-150).contains(Point(w)) for w in wps): continue
            if V23 and not all(Zr.contains(Point(w)) for w in wps): continue
            pts_ = [tee] + wps + [green]; seg = []
            for a_, b_ in zip(pts_, pts_[1:]):
                r_ = route(a_, b_, Zr)
                if not r_: seg = None; break
                seg += r_ if not seg else r_[1:]
            if seg and V23:                                  # detour trop long par rapport au chemin le plus court
                if ref_ is None: ref_ = LineString(route(tee, green, Zr) or [tee, green]).length
                if LineString(seg).length > 1.2 * ref_ + 150: continue
            if seg: best = seg; break
        if best is None: best = route(tee, green, Zr) or [tee, green]; style = 'droit'
        raw = best
        if V23:                                             # trace presque droit : un obstacle casse la ligne
            ch_ = LineString([tee, green]); dev = max(ch_.distance(Point(q)) for q in raw) / max(1.0, ch_.length)
            if dev < 0.05 and cut is None: cut = 'sable' if 'M_Bunker' in set(tpl.o2m.values()) and _rc.random() < 0.5 else 'arbres'
    else:
        # depart et green sur deux terres : on va par la terre du depart jusqu'au point le plus proche du green, puis en l'air
        from shapely.ops import nearest_points
        q = nearest_points(Et.buffer(-90), Point(green))[0]
        raw = (route(tee, (q.x, q.y), Et.buffer(-70)) or [tee, (q.x, q.y)]) + [green]
    path = _smooth(raw)
    line = LineString(path); Ltot = line.length
    d_end = (green[0] - path[-6][0], green[1] - path[-6][1]); dn = math.hypot(*d_end) or 1
    approach = (d_end[0] / dn, d_end[1] / dn)
    d0 = (path[5][0] - tee[0], path[5][1] - tee[1]); d0n = math.hypot(*d0) or 1; aim = (d0[0] / d0n, d0[1] / d0n)

    # ---------------------------------------------------------- formes
    collar_p = green_p.buffer(24).difference(green_p).intersection(E) if not green_p.is_empty else Polygon()
    tee_p = blob(tee[0], tee[1], 60, rng, 0.05, stretch=1.6, ang=math.atan2(aim[1], aim[0])).intersection(Et.buffer(-20))
    s0 = (rng.uniform(380, 620) if not V23 else rng.uniform(260, 400)) if par > 3 else gr + 120
    s1 = Ltot - gr * rng.uniform(0.6, 0.9)
    ws = rng.uniform(210, 260) if style == 'droit' else rng.uniform(150, 200)        # demi-largeur
    _rf = random.Random(seed * 104729 + par * 13 + 7)
    form = style
    Ebd = E.boundary
    side_holes = unary_union([hn for j_, hn in enumerate(new_holes) if not (cut == 'lac' and j_ == 0)]) if new_holes else Polygon()
    def wfun(sv):
        p_ = line.interpolate(sv)
        room = min(Ebd.distance(p_), side_holes.distance(p_) if not side_holes.is_empty else 1e9) - 70.0                     # rough garanti entre le fairway et le bord (eau, roche...)
        t_ = max(0.55, min(1.0, (sv - s0) / 260.0, (s1 - sv) / 220.0 + 0.6))
        return max(55.0, min(ws * t_ * (1 + 0.08 * noise(p_.x, p_.y, 1200)), room))
    if par > 3 or _rf.random() < 0.5 or V23:
        a_ = s0 if par > 3 else max(0.0, Ltot - gr - _rf.uniform(260, 420))
        L_, R_ = [], []
        for sv in np.linspace(a_, s1, 90):
            p_ = line.interpolate(sv); q_ = line.interpolate(min(Ltot, sv + 5)); r_ = line.interpolate(max(0, sv - 5))
            dx, dz = q_.x - r_.x, q_.y - r_.y; nn_ = math.hypot(dx, dz) or 1; w_ = wfun(sv)
            L_.append((p_.x - dz / nn_ * w_, p_.y + dx / nn_ * w_)); R_.append((p_.x + dz / nn_ * w_, p_.y - dx / nn_ * w_))
        fair_p = Polygon(L_ + R_[::-1]).buffer(0)
        fair_p = rounded(fair_p, 40) if not fair_p.is_empty else fair_p
    else:
        fair_p = Polygon()
    fair_p = fair_p.intersection(E.buffer(-45)) if not fair_p.is_empty else fair_p
    tree_row = []
    if V23 and not fair_p.is_empty:
        if not holesU.is_empty: fair_p = fair_p.difference(holesU.buffer(55))        # toujours du rough avant l'eau
        if cut in ('arbres', 'rough'):
            a_ = s0 + 180 if par > 3 else max(0.0, Ltot - gr - 200)
            b_ = max(a_ + 1, (0.68 if par > 3 else 0.8) * Ltot - 120)
            sc_ = _rc.uniform(max(a_, 0.4 * Ltot), max(a_, b_)) if par > 3 else a_
            gw = _rc.uniform(70, 110)
            from shapely.ops import substring as _sub
            seg_ = _sub(line, sc_, min(Ltot - gr - 40, sc_ + gw))
            if seg_.length > 20:
                fair_p = fair_p.difference(seg_.buffer(ws + 80, cap_style=2))
                if cut == 'arbres':
                    m_ = line.interpolate(sc_ + seg_.length / 2); q_ = line.interpolate(min(Ltot, sc_ + seg_.length / 2 + 5))
                    dx, dz = q_.x - m_.x, q_.y - m_.y; nn_ = math.hypot(dx, dz) or 1
                    nx_, nz_ = -dz / nn_, dx / nn_; o_ = -(ws + 30)
                    while o_ <= ws + 30:
                        tp_ = (m_.x + nx_ * o_ + _rc.uniform(-12, 12), m_.y + nz_ * o_ + _rc.uniform(-12, 12))
                        if E.buffer(-30).contains(Point(tp_)) and (holesU.is_empty or holesU.distance(Point(tp_)) > 40): tree_row.append(tp_)
                        o_ += _rc.uniform(45, 62)
            else: cut = None
    if not fair_p.is_empty:
        fair_p = rounded(fair_p, 25)
        if hasattr(fair_p, 'geoms'): fair_p = unary_union([q for q in fair_p.geoms if q.area > (40000 if V23 else 15000)])
    # bunkers (seulement si le modele a du sable)
    bunkers = []
    if 'M_Bunker' in set(tpl.o2m.values()):
        nb = rng.randint(*BUNKERS[par]) + fol
        n_green = min(nb, rng.randint(1, 2))
        for i in range(n_green):
            side = rng.choice((-1, 1)); a = math.atan2(approach[1], approach[0]) + side * math.radians(rng.uniform(55, 130))
            dist = gr + rng.uniform(35, 70)
            bunkers.append(blob(green[0] + math.cos(a) * dist, green[1] + math.sin(a) * dist, rng.uniform(40, 70), rng, 0.18,
                                stretch=rng.uniform(1.3, 2.0), ang=a + 1.57))
        for i in range(nb - n_green):
            s = rng.uniform(0.5, 0.8) * Ltot if par > 3 else rng.uniform(0.3, 0.6) * Ltot
            p = line.interpolate(s); q = line.interpolate(min(Ltot, s + 5))
            dx, dz = q.x - p.x, q.y - p.y; n = math.hypot(dx, dz) or 1
            side = rng.choice((-1, 1)); off = ws + rng.uniform(-30, 70)
            bunkers.append(blob(p.x - dz / n * off * side, p.y + dx / n * off * side, rng.uniform(50, 90), rng, 0.2,
                                stretch=rng.uniform(1.4, 2.4), ang=math.atan2(dz, dx)))
        if par > 3 and rng.random() < 0.3 + 0.2 * fol and not V23:
            s_ = rng.uniform(0.5, 0.72) * Ltot; p_ = line.interpolate(s_); q_ = line.interpolate(min(Ltot, s_ + 5))
            dx, dz = q_.x - p_.x, q_.y - p_.y
            bunkers.append(blob(p_.x, p_.y, rng.uniform(45, 70), rng, 0.15, stretch=rng.uniform(2.2, 3.2), ang=math.atan2(-dx, dz)))
    if V23 and cut == 'sable' and 'M_Bunker' in set(tpl.o2m.values()):
        sc_ = _rc.uniform(0.45, 0.68) * Ltot if par > 3 else max(gr + 120, Ltot - gr - _rc.uniform(70, 130))
        p_ = line.interpolate(sc_); q_ = line.interpolate(min(Ltot, sc_ + 5)); dx, dz = q_.x - p_.x, q_.y - p_.y
        th_ = _rc.uniform(32, 48)                                 # demi-epaisseur ; longueur = largeur du fairway
        bunkers.append(blob(p_.x, p_.y, th_, rng, 0.12, stretch=(ws + _rc.uniform(20, 60)) / th_, ang=math.atan2(-dx, dz)))
    bunk_p = unary_union([b.simplify(5) for b in bunkers]) if bunkers else Polygon()
    if not bunk_p.is_empty:
        bunk_p = bunk_p.intersection(E.buffer(-45)).difference(tee_p.buffer(60))
        if not holesU.is_empty: bunk_p = bunk_p.difference(holesU.buffer(50))
        bunk_p = rounded(bunk_p, 10) if not bunk_p.is_empty else bunk_p

    regions = collections.OrderedDict()
    regions['green'] = green_p.simplify(2)
    regions['collar'] = collar_p.simplify(2)
    regions['bunker'] = rounded(rounded(bunk_p, 12).difference(green_p.union(collar_p).buffer(14)), 10) if not bunk_p.is_empty else Polygon()
    taken = unary_union([regions['green'], regions['collar'], regions['bunker']])
    for k in ('sea', 'water', 'bank', 'shore'): regions[k] = Polygon()
    regions['fairway'] = rounded(unary_union([fair_p, tee_p]).difference(taken.buffer(10)), 14).difference(taken).intersection(E)
    taken = taken.union(regions['fairway'])
    regions['rough'] = E.difference(taken)
    regions['ob'] = Polygon()
    if not holesU.is_empty:
        for k_ in ('fairway', 'rough', 'bunker', 'green', 'collar'): regions[k_] = regions[k_].difference(holesU)

    # ---------------------------------------------------------- maillage
    STEP = {'rough': 65, 'fairway': 45, 'green': 15, 'collar': 15, 'bunker': 20}
    SPACING = {'rough': 95, 'fairway': 85, 'green': 15, 'collar': 15, 'bunker': 40}   # assez fin pour suivre le terrain de Nintendo et le relief
    inner_keys = ['green', 'collar', 'bunker', 'fairway']
    for k in inner_keys:
        if not regions[k].is_empty: regions[k] = sh.set_precision(sh.make_valid(regions[k]), 0.1)
    regions['rough'] = sh.make_valid(E.difference(unary_union([regions[k] for k in inner_keys if not regions[k].is_empty])))
    if not holesU.is_empty: regions['rough'] = sh.make_valid(regions['rough'].difference(holesU))
    Eb = E.boundary
    lines = []
    for k in inner_keys:
        g = regions[k]
        for pg in getattr(g, 'geoms', [g]):
            if pg.is_empty or not hasattr(pg, 'exterior'): continue
            lines.append(LineString(pg.exterior.coords))
            for h in pg.interiors: lines.append(LineString(h.coords))
    inner_lines = unary_union(lines) if lines else None
    verts, vidx, segs = [], {}, set()
    def vid(p):
        k = (round(p[0], 2), round(p[1], 2))
        if k not in vidx: vidx[k] = len(verts); verts.append(k)
        return vidx[k]
    # bord de la zone : les aretes exactes de Nintendo (aucune simplification -> raccord sans fente)
    for ring in getattr(Eb, 'geoms', [Eb]):
        c = list(ring.coords)
        for a_, b_ in zip(c, c[1:]):
            n_ = max(1, int(math.dist(a_, b_) / STEP['rough']))
            pts = [(a_[0] + (b_[0] - a_[0]) * i / n_, a_[1] + (b_[1] - a_[1]) * i / n_) for i in range(n_ + 1)]
            for p_, q_ in zip(pts, pts[1:]):
                ia, ib = vid(p_), vid(q_)
                if ia != ib: segs.add((min(ia, ib), max(ia, ib)))
    for h_, mv_, _, _ in moves:                         # bord des etangs deplaces : sommets exacts (raccord avec les parois)
        c = [mv_.xz(x, z) for x, z in h_.exterior.coords]
        for a_, b_ in zip(c, c[1:]):
            ia, ib = vid(a_), vid(b_)
            if ia != ib: segs.add((min(ia, ib), max(ia, ib)))
    fine = unary_union([regions[k] for k in ('green', 'collar', 'bunker') if not regions[k].is_empty]).buffer(3)
    if inner_lines is not None:
        noded = unary_union([inner_lines]).intersection(E.buffer(-0.3))
        if not holesU.is_empty: noded = noded.difference(holesU.buffer(0.3))
        for ls in getattr(noded, 'geoms', [noded]):
            if ls.is_empty or ls.geom_type != 'LineString': continue
            ls2 = ls.simplify(1.0 if fine.intersects(ls) else 2.0)
            st = STEP['green'] if fine.contains(ls2.interpolate(0.5, normalized=True)) else STEP['fairway']
            ls2 = ls2.segmentize(st)
            c = list(ls2.coords)
            if Eb.distance(Point(c[0])) < 1.0 and Eb.distance(Point(c[-1])) < 1.0 and ls2.length < 3: continue
            for a_, b_ in zip(c, c[1:]):
                ia, ib = vid(a_), vid(b_)
                if ia != ib: segs.add((min(ia, ib), max(ia, ib)))
    # trous : emplacements de drapeau (comme gen.generate : centre inscrit d'un demi-carre de 15)
    n_pins = max(1, sum(1 for o in tpl.pmp if (o['grp'], o['typ']) == (2, 1)))
    pin_zone = regions['green'].buffer(-34) if not keep_green else Polygon()
    pins = [tuple(green)] if not keep_green else []
    _rp = random.Random(seed * 977 + 5)
    for half, sep in ((2, 64.0), (1, 36.0)):
        tries = 0
        while len(pins) < n_pins + 1 and tries < 600 and not pin_zone.is_empty:
            tries += 1
            bx0, bz0, bx1, bz1 = pin_zone.bounds
            q = (_rp.uniform(bx0, bx1), _rp.uniform(bz0, bz1))
            if not pin_zone.contains(Point(q)): continue
            if all(math.hypot(q[0] - p_[0], q[1] - p_[1]) >= sep for p_ in pins): pins.append(q)
        if len(pins) >= n_pins + 1: break
    pin_half = {}
    for k_, (px_, pz_) in enumerate(pins):
        hf = 2 if (k_ == 0 or all(math.hypot(px_ - q_[0], pz_ - q_[1]) >= 64 for q_ in pins if q_ != (px_, pz_))) else 1
        pin_half[(px_, pz_)] = hf
        ox_, oz_ = px_ - CUP_R, pz_ - CUP_R
        grid_ = {}
        for i_ in range(-hf, hf + 1):
            for j_ in range(-hf, hf + 1): grid_[(i_, j_)] = vid((ox_ + 15.0 * i_, oz_ + 15.0 * j_))
        ia, ib = grid_[(1, 0)], grid_[(0, 1)]; segs.add((min(ia, ib), max(ia, ib)))
        for r_ in range(1, hf + 1):
            ring_ = [(i_, -r_) for i_ in range(-r_, r_)] + [(r_, j_) for j_ in range(-r_, r_)] + \
                    [(i_, r_) for i_ in range(r_, -r_, -1)] + [(-r_, j_) for j_ in range(r_, -r_, -1)]
            for a_, b_ in zip(ring_, ring_[1:] + ring_[:1]):
                ia, ib = grid_[a_], grid_[b_]; segs.add((min(ia, ib), max(ia, ib)))
    def in_cup_box(x, z):
        return any(abs(x - p_[0] + CUP_R) < 15 * h_ + 18 and abs(z - p_[1] + CUP_R) < 15 * h_ + 18 for p_, h_ in pin_half.items())
    # points interieurs
    for k in ('green', 'collar', 'bunker', 'fairway', 'rough'):
        g = regions[k]; sp = SPACING[k]
        if g.is_empty: continue
        pg = prep(g.buffer(-sp * 0.4 if sp > 20 else -4))
        bx0, bz0, bx1, bz1 = g.bounds
        for gx_ in np.arange(bx0 + sp / 2, bx1, sp):
            for gz_ in np.arange(bz0 + sp / 2, bz1, sp):
                x = gx_ + rng.uniform(-0.3, 0.3) * sp; z = gz_ + rng.uniform(-0.3, 0.3) * sp
                if pg.contains(Point(x, z)) and not in_cup_box(x, z) and Eb.distance(Point(x, z)) > 8 and (holesU.is_empty or holesU.distance(Point(x, z)) > 8): vid((x, z))
    import triangle as tr
    T = tr.triangulate({'vertices': np.array(verts), 'segments': np.array(sorted(segs))}, 'p')
    V = T['vertices']; F = T['triangles']
    if len(V) > len(verts):                        # points ajoutes par Triangle : jamais sur le bord de la zone
        dn_ = sh.distance(Eb, sh.points(V[len(verts):]))
        # un point ajoute sur le bord est sur une arete de Nintendo : il prend la hauteur exacte de Nintendo
        # plus bas (raccord sans fente, verifie par le controle des raccords)
    prepared = {k: prep(g) for k, g in regions.items() if not g.is_empty}
    Ep = prep(E.difference(holesU) if not holesU.is_empty else E)
    labels, tris = [], []
    for f in F:
        c = V[f].mean(0); pt = Point(c)
        if not Ep.contains(pt): continue
        lab = 'rough'
        for k in ('green', 'collar', 'bunker', 'fairway'):
            if k in prepared and prepared[k].contains(pt): lab = k; break
        labels.append(lab); tris.append(f)

    # ---------------------------------------------------------- hauteurs : celles de Nintendo
    H0 = np.array([GR.h(x, z) for x, z in V])
    H = H0.copy()
    # style de relief tire par variante (cahier des charges) : terrasses, dunes ou peu de relief
    rstyle = random.Random(seed * 3571 + 9).choice(['terrasses', 'dunes', 'plat'])
    if rstyle == 'plat': A1, A2, A3 = 8, 3, 0
    elif rstyle == 'dunes': A1, A2, A3 = (22, 30, 38)[fol], (6, 8, 10)[fol], (25, 35, 45)[fol]
    else: A1, A2, A3 = 10, 4, 0
    dE_ = sh.distance(Eb, sh.points(V)); fr = np.clip(dE_ / 220.0, 0, 1); fr = fr * fr * (3 - 2 * fr)
    fw_ = regions['fairway']
    for i, (x, z) in enumerate(V):
        h = A1 * noise(x + 211, z - 97, 900) + A2 * noise(x - 31, z + 57, 260)
        if not fw_.is_empty:
            df = fw_.distance(Point(x, z))
            if 40 < df < 320:
                h += A3 * math.sin(math.pi * (df - 40) / 280) * max(0.0, noise(x - 333, z + 77, 380) + 0.3)
        H[i] += fr[i] * h
    # grandes dunes dans le rough (loin du fairway, du green et du depart), plus hautes de Resort A a C
    nd = rng.randint(*((4, 6), (6, 9), (8, 12))[fol]) if rstyle == 'dunes' else 0; hmax = (70, 95, 125)[fol]
    rough_ = regions['rough']; avoid_ = unary_union([fw_.buffer(110) if not fw_.is_empty else Polygon(), green_p.buffer(160) if not green_p.is_empty else Point(green).buffer(200), tee_p.buffer(160)])
    dunes = []
    rx0, rz0, rx1, rz1 = rough_.bounds
    for _ in range(400):
        if len(dunes) >= nd: break
        q = (rng.uniform(rx0, rx1), rng.uniform(rz0, rz1))
        if not rough_.buffer(-60).contains(Point(q)) or avoid_.contains(Point(q)): continue
        if any(math.dist(q, d_[0]) < 250 for d_ in dunes): continue
        dunes.append((q, rng.uniform(0.45, 1.0) * hmax, rng.uniform(110, 220), rng.uniform(1.0, 1.8), rng.uniform(0, 3.14)))
    if dunes:
        avp = prep(avoid_.buffer(-1)) if not avoid_.is_empty else None
        for i, (x, z) in enumerate(V):
            h = 0.0
            for (dx_, dz_), A_, sg, st, an in dunes:
                ex, ez = x - dx_, z - dz_
                u_ = (ex * math.cos(an) + ez * math.sin(an)) / st; v_ = -ex * math.sin(an) + ez * math.cos(an)
                r2 = (u_ * u_ + v_ * v_) / (sg * sg)
                if r2 < 9: h += A_ * math.exp(-r2)
            if h:
                da = avoid_.distance(Point(x, z)) if not avoid_.is_empty else 999
                h *= min(1.0, da / 120.0)
                H[i] += fr[i] * h
    _re = random.Random(seed * 131 + par)
    if rstyle == 'terrasses':
        # plateaux a bord franc (petites falaises d'herbe) : green perche ou en contrebas, paliers le long du trace
        ter = []
        gp_ = green_p if not green_p.is_empty else Point(green).buffer(gr)
        goff_ = rng.choice((1, 1, -1)) * rng.uniform(18, 38) * (1 + 0.25 * fol)
        ter.append((rounded(gp_.buffer(rng.uniform(70, 160)), 40), goff_))
        for _ in range(rng.randint(1, 3)):
            sv = rng.uniform(0.3, 0.75) * Ltot; p_ = line.interpolate(sv)
            b_ = blob(p_.x + rng.uniform(-120, 120), p_.y + rng.uniform(-120, 120), rng.uniform(220, 420), rng, 0.15,
                      stretch=rng.uniform(1.2, 2.0), ang=rng.uniform(0, 3.14))
            ter.append((b_.difference(gp_.buffer(140)).difference(tee_p.buffer(160)), rng.choice((-1, 1)) * rng.uniform(15, 32) * (1 + 0.25 * fol)))
        ramp = rng.uniform(26, 40)
        for poly_, off_ in ter:
            if poly_.is_empty: continue
            bd_ = poly_.boundary
            for i, (x, z) in enumerate(V):
                p = Point(x, z)
                if not poly_.buffer(ramp).contains(p): continue
                d_ = bd_.distance(p); d_ = d_ if poly_.contains(p) else -d_
                t_ = min(1.0, max(0.0, (d_ + ramp) / (2 * ramp))); t_ = t_ * t_ * (3 - 2 * t_)
                H[i] += fr[i] * off_ * t_
    gh = float(np.mean([H[i] for i, (x, z) in enumerate(V) if not green_p.is_empty and green_p.buffer(20).contains(Point(x, z))] or [GR.h(*green)]))
    slope = rng.uniform(0.006, 0.016)
    for i, (x, z) in enumerate(V):
        p = Point(x, z)
        dg = (green_p.distance(p) if not green_p.contains(p) else 0.0) if not green_p.is_empty else 1e9
        if dg < 140:
            t = 1 - dg / 140.0; t = t * t * (3 - 2 * t)
            plane = gh + slope * ((x - green[0]) * approach[0] + (z - green[1]) * approach[1]) \
                + GREEN_UNDUL * (noise(x + 71, z - 13, 170) + 0.5 * noise(x - 5, z + 9, 110))
            H[i] = H[i] * (1 - t) + plane * t
    tee_h = GR.h(*tee) + _re.uniform(0, 6)
    for i, (x, z) in enumerate(V):
        p = Point(x, z); dt = tee_p.distance(p) if not tee_p.contains(p) else 0.0
        if dt < 100:
            t = 1 - dt / 100.0; t = t * t * (3 - 2 * t)
            H[i] = H[i] * (1 - t) + tee_h * t
    if not regions['bunker'].is_empty:
        for bp in getattr(regions['bunker'], 'geoms', [regions['bunker']]):
            zone_ = bp.buffer(120); ids = [i for i, (x, z) in enumerate(V) if zone_.contains(Point(x, z))]
            if len(ids) < 3: continue
            P_ = V[ids]; A_ = np.c_[P_[:, 0], P_[:, 1], np.ones(len(ids))]
            a_, b_, c_ = np.linalg.lstsq(A_, H[ids], rcond=None)[0]
            gmag = math.hypot(a_, b_); lim = math.tan(math.radians(5))
            if gmag > lim: a_, b_ = a_ * lim / gmag, b_ * lim / gmag
            mx, mz = P_[:, 0].mean(), P_[:, 1].mean(); c0 = H[ids].mean()
            for i in ids:
                x, z = V[i]; p = Point(x, z)
                d = 0.0 if bp.contains(p) else bp.distance(p)
                t = 1 - d / 120.0; t = t * t * (3 - 2 * t)
                t *= min(1.0, green_p.distance(p) / 40.0) if not green_p.is_empty else 1.0
                H[i] = H[i] * (1 - t) + (c0 + a_ * (x - mx) + b_ * (z - mz)) * t
        Bk_ = regions['bunker']
        for i, (x, z) in enumerate(V):
            p = Point(x, z)
            if Bk_.contains(p): H[i] -= min(22, Bk_.boundary.distance(p) * 0.35)
    # raccord : exactement Nintendo sur le bord de la zone, transition sur 60 unites
    dE = sh.distance(Eb, sh.points(V))
    t = np.clip(dE / 60.0, 0, 1); t = t * t * (3 - 2 * t)
    H = H0 + (H - H0) * t
    for h_, mv_, _, _ in moves:
        ring3 = LineString([mv_.xz(x, z) + (GR.h(x, z) + mv_.dy,) for x, z in h_.exterior.coords])
        r2 = LineString([q[:2] for q in ring3.coords])
        dR = sh.distance(r2, sh.points(V))
        for i in np.nonzero(dR < 130)[0]:
            p_ = Point(V[i]); q_ = ring3.interpolate(r2.project(p_))
            tt = min(1.0, dR[i] / 130.0); tt = tt * tt * (3 - 2 * tt)
            H[i] = q_.z * (1 - tt) + H[i] * tt
    P3 = np.c_[V[:, 0], H, V[:, 1]]
    N = np.zeros_like(P3)
    for f in tris:
        a, b, c = P3[f]; N[f] += np.cross(b - a, c - a)
    N /= np.linalg.norm(N, axis=1)[:, None] + 1e-9
    N[N[:, 1] < 0] *= -1
    tris2 = []
    for f, lab in zip(tris, labels):
        a, b, c = P3[f]
        if np.cross(b - a, c - a)[1] < 0: f = [f[0], f[2], f[1]]
        tris2.append((list(f), lab))
    return dict(pins=pins, V=P3, N=N, tris=tris2, regions=regions, sea=Polygon(), sea_kcl=[], ocean_y=None, tee=tee, green=green,
                gh=gh, tee_h=tee_h, aim=aim, approach=approach, path=path, par=par, gr=gr, seed=seed, Ltot=Ltot,
                pond=holesU, wl=(moves[0][3] + moves[0][1].dy) if moves else None,
                pond_xf=[(h_, mv_) for h_, mv_, _, _ in moves] or None, cut=cut, tree_row=tree_row,
                style=style, form=form, feature=rstyle, water_mat=(moves[0][2] if moves else None), ocean_keep=False, rej=REJ, island=E,
                bank_mat='M_Iwa', iwa_cliff=True, nmode=True, ncolor=GR.color, keep_pins=keep_green,
                keep_green_poly=green_keep_poly(tpl, g0) if keep_green else None)
