"""Etangs de Nintendo (trou dans le sol au-dessus d'un plan d'eau) : reperage et deplacement.
Un etang = un trou interieur de la surface du sol (materiaux de jeu + OB) au-dessus de l'eau.
On le deplace par une similitude du plan (rotation, echelle, translation) + un decalage vertical."""
import math, numpy as np
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union
from shapely.prepared import prep
import shapely as sh

GROUND_M = {'M_Fairway', 'M_Rough', 'M_Green', 'M_Bunker', 'M_Color', 'M_OB'}
WATER_M = {'M_Sea', 'M_Lake'}
BIG = 3e6           # au-dela : plan d'ocean, jamais deplace


def _tp(t): return Polygon([(v['pos'][0], v['pos'][2]) for v in t])


def find_holes(tpl):
    """Liste de (trou, materiau d'eau, hauteur de l'eau) pour chaque etang interieur."""
    if getattr(tpl, '_ponds', None) is not None: return tpl._ponds
    gp, wp = [], []
    for n, tl in tpl.vt.items():
        mt = tpl.o2m.get(n)
        for t in tl:
            if min(v['pos'][1] for v in t) < -8000: continue
            p = _tp(t)
            if p.area < 0.01: continue
            if mt in GROUND_M: gp.append(p)
            elif mt in WATER_M and p.area < BIG: wp.append((p, mt, t[0]['pos'][1]))
    U = unary_union([p.buffer(0.02, join_style=2) for p in gp]).buffer(-0.02, join_style=2)
    out = []
    if wp:
        W = unary_union([p for p, _, _ in wp])
        for c in getattr(U, 'geoms', [U]):
            for r in c.interiors:
                h = Polygon(r)
                if h.area < 4000: continue
                if h.intersection(W).area < 0.5 * h.area: continue
                ws = [(p.intersection(h).area, mt, y) for p, mt, y in wp if p.intersects(h)]
                a, mt, y = max(ws)
                out.append((h, mt, y))
    tpl._ponds = out
    return out


class Move:
    """Similitude : p -> c1 + s R(th) (p - c0) ; y -> y + dy."""
    def __init__(self, c0, c1, th, s, dy):
        self.c0, self.c1, self.th, self.s, self.dy = c0, c1, th, s, dy
        self.ct, self.st = math.cos(th), math.sin(th)
    def xz(self, x, z):
        dx, dz = x - self.c0[0], z - self.c0[1]
        return (round(self.c1[0] + self.s * (self.ct * dx - self.st * dz), 2),
                round(self.c1[1] + self.s * (self.st * dx + self.ct * dz), 2))
    def inv(self, x, z):
        dx, dz = (x - self.c1[0]) / self.s, (z - self.c1[1]) / self.s
        return (self.c0[0] + self.ct * dx + self.st * dz, self.c0[1] - self.st * dx + self.ct * dz)
    def pos(self, p):
        x, z = self.xz(p[0], p[2]); return (x, float(p[1]) + self.dy, z)
    def nrm(self, n):
        nx, nz = n[0] / self.s, n[2] / self.s
        x, z = self.ct * nx - self.st * nz, self.st * nx + self.ct * nz
        l = math.sqrt(x * x + n[1] * n[1] + z * z) or 1.0
        return (x / l, n[1] / l, z / l)
    def poly(self, P):
        return Polygon([self.xz(x, z) for x, z in P.exterior.coords])


def _water_fit(tris, chans):
    """Ajustement affine uv = f(x, z) sur les sommets de l'eau de Nintendo (plan plat)."""
    X = np.array([[v['pos'][0], v['pos'][2], 1.0] for t in tris for v in t])
    fit = {}
    for ch in chans:
        Y = np.array([v[ch] for t in tris for v in t], float)
        fit[ch] = np.linalg.lstsq(X, Y, rcond=None)[0]
    return fit


def _tri_poly(P):
    """Triangulation d'un polygone (sens : normale vers le haut)."""
    import triangle as tr
    c = list(P.exterior.coords)[:-1]
    segs = [(i, (i + 1) % len(c)) for i in range(len(c))]
    T = tr.triangulate({'vertices': np.array(c), 'segments': np.array(segs)}, 'p')
    out = []
    for f in T['triangles']:
        a, b, cc = (T['vertices'][i] for i in f)
        if (b[0] - a[0]) * (cc[1] - a[1]) - (b[1] - a[1]) * (cc[0] - a[0]) > 0: b, cc = cc, b   # (x,z) : y vers le haut
        out.append((tuple(a), tuple(b), tuple(cc)))
    return out


def transplant(vt, o2m, g):
    """Triangles (par materiau) des etangs deplaces : parois et berges de Nintendo transformees,
    plan d'eau refait a la forme du trou (rien ne depasse sous le terrain).
    Renvoie {materiau: [triangle = [3 sommets]]}, sommets dans l'ordre de Nintendo (ou CCW vu d'en haut pour l'eau, drapeau 'up')."""
    out = {}
    wm = g.get('water_mat')
    for h, mv in g.get('pond_xf') or []:
        hp = prep(h.buffer(0.5)); hb = h.buffer(5)
        water = []
        for n, tl in vt.items():
            mt = o2m.get(n)
            for t in tl:
                if min(v['pos'][1] for v in t) < -8000: continue
                p = _tp(t)
                if mt in WATER_M:
                    if p.area < BIG and p.intersects(hb): water.append(t)
                    continue
                if mt in GROUND_M or p.area < 1e-6 or not hp.contains(p.centroid): continue
                nt = []
                for v in t:
                    e = dict(v); e['pos'] = mv.pos(v['pos'])
                    if 'nrm' in v: e['nrm'] = mv.nrm(v['nrm'])
                    nt.append(e)
                out.setdefault(mt, []).append(nt)
        if water:
            y = float(np.median([v['pos'][1] for t in water for v in t])) + mv.dy
            chans = [c for c in ('uv0', 'uv1') if c in water[0][0]]
            fit = _water_fit(water, chans)
            v0 = water[0][0]
            for tri in _tri_poly(mv.poly(h).buffer(12, join_style=2).simplify(1.0)):
                nt = []
                for x, z in tri:
                    e = dict(v0); e['pos'] = (float(x), y, float(z)); e['nrm'] = (0.0, 1.0, 0.0)
                    xo, zo = mv.inv(x, z)
                    for ch in chans: e[ch] = tuple(float(q) for q in np.array([xo, zo, 1.0]) @ fit[ch])
                    nt.append(e)
                out.setdefault('_water_' + o2m.get([n for n, tl in vt.items() if water[0] in tl][0]), []).append(nt)
    return out


def transplant_kcl(kcl, g, tri_vertices):
    """Prismes de collision des etangs deplaces + eau refaite ; renvoie (a_garder(prisme)->bool, nouveaux)."""
    new, olds = [], []
    for h, mv in g.get('pond_xf') or []:
        hp = prep(h.buffer(0.5)); hb = h.buffer(5); olds.append(hb)
        wattr, wy = None, []
        for p in kcl['prisms']:
            A, B, C = tri_vertices(kcl, p)
            q = Polygon([(v[0], v[2]) for v in (A, B, C)])
            if q.area < 1e-6: continue
            if p[6] & 0x1f == 0x07:
                if q.area < BIG and q.intersects(hb): wattr = p[6]; wy.append(A[1])
                continue
            if hp.contains(q.centroid) and q.area < BIG:
                new.append((mv.pos(A), mv.pos(B), mv.pos(C), p[6]))
        if wattr is not None:
            y = float(np.median(wy)) + mv.dy
            for a, b, c in _tri_poly(mv.poly(h).buffer(12, join_style=2).simplify(1.0)):
                P = [(float(a[0]), y, float(a[1])), (float(b[0]), y, float(b[1])), (float(c[0]), y, float(c[1]))]
                if np.cross(np.subtract(P[1], P[0]), np.subtract(P[2], P[0]))[1] < 0: P[1], P[2] = P[2], P[1]
                new.append((P[0], P[1], P[2], wattr))
    OP = prep(unary_union(olds)) if olds else None
    def drop_old(p, q):
        """Eau de Nintendo d'un etang deplace (plan sous le terrain) : retiree."""
        return OP is not None and p[6] & 0x1f == 0x07 and q.area < BIG and OP.intersects(q)
    return drop_old, new
