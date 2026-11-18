"""Generateur de trous de golf pour Wii Sports Resort (prototype v1).

Partant d'un trou modele (silhouette de l'ile, grand relief, decor lointain),
fabrique un nouveau trou a partir d'une graine : depart, fairway (avec ou sans
dog-leg), green, anneau du green, bunkers, rough, zone arboree, arbres.
"""
import sys, math, random, collections
sys.path.insert(0, '/home/user/wsr/tools')
import numpy as np
import triangle as tr
from shapely.geometry import box, Polygon, Point, LineString, MultiPolygon
from shapely.ops import unary_union, polygonize
from shapely.prepared import prep
from scipy.interpolate import LinearNDInterpolator
from scipy.ndimage import gaussian_filter

from meshio import value_tris
from kcl import read_kcl
from kcltri import tri_vertices
from pmp import read_pmp

TOP = {'M_OB', 'M_Rough', 'M_Fairway', 'M_Green', 'M_Bunker', 'M_Color', 'M_Iwa', 
       'M_Kiwa_OB', 'M_Kiwa_R', 'M_Kiwa_F', 'M_Kiwa_Bunker', 'M_Kiwa_Black'}
ATTR = {'shore': 0x010c, 'seabed': 0x010c, 'water': 0x0107, 'bank': 0x010c, 'bed': 0x010c, 'ob': 0x0104, 'rough': 0x0102, 'fairway': 0x0101, 'green': 0x0106, 'collar': 0x0109, 'bunker': 0x0103}
MAT = {'shore': 'M_Iwa', 'seabed': 'M_Iwa', 'water': 'M_Sea', 'bank': 'M_Iwa', 'bed': 'M_Iwa', 'ob': 'M_OB', 'rough': 'M_Rough', 'fairway': 'M_Fairway', 'green': 'M_Green', 'collar': 'M_Color', 'bunker': 'M_Bunker'}
# longueurs (centre depart -> centre green, en unites) mesurees sur les 21 trous
LEN = {3: (1280, 1700), 4: (3000, 3700), 5: (4150, 5000)}
BUNKERS = {3: (2, 4), 4: (3, 6), 5: (5, 8)}
POND_P = {3: 0.85, 4: 0.8, 5: 0.9}      # plus de lacs (seulement fcJP3, fcJP6, fcJP11 : vrai materiau de lac)
SEA_P = 0.35
FAR0, FAR1 = 120.0, 380.0
DUNE = 110.0
GRASS_W = 120.0           # pente d'herbe entre la rive et le terrain
SHORE_W = 70.0            # largeur de la rive en roche du bras de mer : toute la pente y tient              # hauteur des dunes de decor au-dela de la zone jouable   # au-dela de FAR0 + FAR1 du rough : relief d'origine de Nintendo          # part des trous dont le green est sur une ile (si l'ile modele est entouree d'ocean)
RELIEF = 0.8
GREEN_UNDUL = 2.0
CUP_R = 15.0 * (2 - 2 ** 0.5) / 2      # rayon inscrit du demi-carre de 15 (4.39), comme Nintendo


def _obj2mat(m):
    o2m = {}
    for lst in m['links'].values():
        for mat, obj, bone in lst: o2m[m['polys'][obj]['name']] = m['mats'][mat]
    return o2m


class Template:
    """Ce qu'on reprend du trou modele."""
    def __init__(self, base, name):
        self.name = name
        self.course = open('%s/G3D/glf_course_%s.brres' % (base, name), 'rb').read()
        self.map = open('%s/G3D/glf_map_%s.brres' % (base, name), 'rb').read()
        self.pmp_raw = open('%s/WS2_glf_course_%s.pmp' % (base, name), 'rb').read()
        self.pmp = read_pmp('%s/WS2_glf_course_%s.pmp' % (base, name))
        self.kcl = read_kcl('%s/WS2_glf_course_%s.kcl' % (base, name))
        self.vt, self.m = value_tris(self.course)
        self.o2m = _obj2mat(self.m)
        # rochers : falaises du rivage (a garder) ou berges d'etang (a regenerer) ?
        iw = [v['pos'] for n_, tl in self.vt.items() if self.o2m.get(n_) == 'M_Iwa' for t in tl for v in t]
        iw = np.array(iw) if iw else np.zeros((0, 3))
        self.iwa_cliff = len(iw) > 0 and max(np.ptp(iw[:, 0]), np.ptp(iw[:, 2])) > 1500
        top = TOP - {'M_Iwa'} if self.iwa_cliff else TOP
        # surface de l'ile : contour + echantillonneur de hauteur
        polys, pts = [], []
        for name_, tl in self.vt.items():
            if self.o2m.get(name_) not in top: continue
            for t in tl:
                p = [(v['pos'][0], v['pos'][2]) for v in t]
                pg = Polygon(p)
                if pg.area > 1: polys.append(pg.buffer(0.5))
                for v in t: pts.append(v['pos'])
        isl = unary_union(polys)
        if isinstance(isl, MultiPolygon):
            t0 = [o for o in self.pmp if (o['grp'], o['typ']) == (2, 0)][0]['pos']
            on = [g for g in isl.geoms if g.buffer(30).contains(Point(t0[0], t0[2])) and g.buffer(-330).area > 1.5e6]
            isl = on[0] if on else max(isl.geoms, key=lambda g: g.area)
        self.island = Polygon(isl.exterior).simplify(12)
        P = np.array(pts)
        self.top_pts = P                              # surface exacte (raccord des bords)
        interp = LinearNDInterpolator(P[:, [0, 2]], P[:, 1])
        x0, z0, x1, z1 = self.island.bounds
        self.gx = np.arange(x0 - 100, x1 + 100, 40.0); self.gz = np.arange(z0 - 100, z1 + 100, 40.0)
        X, Z = np.meshgrid(self.gx, self.gz)
        Hh = interp(X, Z)
        Hh = np.where(np.isnan(Hh), np.nanmedian(Hh), Hh)
        self.hsmooth = gaussian_filter(Hh, 6)      # ~240 unites : grand relief seulement
        self.uvfit = self._fit_uv(self.vt, self.o2m)
        # materiau utilisable pour un etang : M_Lake, ou M_Sea s'il ne s'agit pas de l'ocean
        ext = {}
        for name_, tl in self.vt.items():
            mt = self.o2m.get(name_)
            if mt in ('M_Lake', 'M_Sea'):
                P_ = np.array([v['pos'] for t in tl for v in t]); ext[mt] = max(np.ptp(P_[:, 0]), np.ptp(P_[:, 2]))
        # lac aussi sur les trous a ocean : on reprend le materiau d'eau M_Sea (memes textures d'eau),
        # le plan d'ocean de Nintendo est garde tel quel dans le meme objet (build.py : ocean_keep)
        # lac seulement avec un vrai materiau de lac de Nintendo (translucide, 4 etages : M_Lake de fcJP6,
        # petit M_Sea de lac de fcJP3/fcJP11). Le M_Sea d'ocean est opaque : un lac avec lui ressemble a la mer.
        self.water_mat = 'M_Lake' if 'M_Lake' in ext else ('M_Sea' if ext.get('M_Sea', 1e9) < 4000 else None)
        self.ocean_keep = False
        # niveau de l'ocean (plan M_Sea geant) : le terrain et le fond des etangs doivent rester au-dessus
        oc = [v['pos'][1] for n_, tl in self.vt.items() if self.o2m.get(n_) == 'M_Sea' for t in tl for v in t]
        self.ocean_y = float(min(oc)) if oc and ext.get('M_Sea', 0) >= 4000 else None

    @staticmethod
    def _fit_uv(vt, o2m):
        fits = {}
        for name, tl in vt.items():
            vs = [v for t in tl for v in t]
            if not vs: continue
            P = np.array([v['pos'] for v in vs]); X = np.c_[P[:, 0], P[:, 2], np.ones(len(P))]
            f = {}
            for ch in ('uv0', 'uv1'):
                if ch in vs[0]:
                    U = np.array([v[ch] for v in vs]); coef = np.linalg.lstsq(X, U, rcond=None)[0]
                    f[ch] = coef
            if 'clr0' in vs[0]:
                f['clr'] = tuple(int(round(c)) for c in np.mean([v['clr0'] for v in vs], 0))
            fits[o2m.get(name, name)] = f
        return fits

    def base_height(self, x, z):
        i = np.clip((z - self.gz[0]) / 40.0, 0, len(self.gz) - 1.001)
        j = np.clip((x - self.gx[0]) / 40.0, 0, len(self.gx) - 1.001)
        i0, j0 = int(i), int(j); fi, fj = i - i0, j - j0
        h = self.hsmooth
        return (h[i0, j0] * (1 - fi) * (1 - fj) + h[i0, j0 + 1] * (1 - fi) * fj +
                h[i0 + 1, j0] * fi * (1 - fj) + h[i0 + 1, j0 + 1] * fi * fj)


# ------------------------------------------------------------------ bruit
class Noise:
    def __init__(self, rng):
        self.ph = [(rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0.6, 1.4), rng.uniform(0, 6.28))
                   for _ in range(6)]
    def __call__(self, x, z, wl):
        s = 0.0
        for k, (a, b, f, r) in enumerate(self.ph):
            ca, sa = math.cos(r), math.sin(r)
            u = (x * ca - z * sa) / wl * f * (1 + k * 0.7); v = (x * sa + z * ca) / wl * f * (1 + k * 0.7)
            s += math.sin(u + a) * math.cos(v + b) / (1 + k)
        return s / 2.45


def blob(cx, cz, r, rng, wobble=0.12, n=48, stretch=1.0, ang=0.0, nh=4):
    k = [(rng.uniform(-wobble, wobble), rng.uniform(0, 6.28)) for _ in range(nh)]
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        rr = r * (1 + sum(a * math.cos((j + 2) * t + p) for j, (a, p) in enumerate(k)))
        x, z = rr * math.cos(t) * stretch, rr * math.sin(t)
        pts.append((cx + x * math.cos(ang) - z * math.sin(ang), cz + x * math.sin(ang) + z * math.cos(ang)))
    return Polygon(pts).buffer(0)


def bezier(p0, p1, p2, n=200):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in np.linspace(0, 1, n)]


def path_len(pts): return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# Resort A sage, B plus fou, C le plus fou (formes, iles, lacs, bunkers)
FOLIE = {'fcJP11': 0, 'fcJP6': 0, 'fcJP12': 0, 'fcJP16': 1, 'fcJP7': 1, 'fcJP10': 1, 'fcJP9': 2, 'fcJP13': 2, 'fcJP3': 2}
FORMS_SAGES = ['ruban', 'serpent', 'croissant', 'fourche', 'chapelet', 'ruban', 'serpent']
FORMS_FOLLES = ['iles', 'gruyere', 'damier', 'nuages', 'dents', 'trompette', 'chapelet', 'iles', 'nuages']
FORMS = ['ruban', 'iles', 'chapelet', 'serpent', 'fourche', 'gruyere', 'trompette', 'damier', 'nuages', 'dents', 'croissant']

def rounded(P, r):
    """Arrondit tous les coins (convexes et concaves) avec un rayon r : pas d'angle vif."""
    if P.is_empty: return P
    Q = P.buffer(r, resolution=12).buffer(-2 * r, resolution=12).buffer(r, resolution=12)
    Q = Q.buffer(-r, resolution=12).buffer(2 * r, resolution=12).buffer(-r, resolution=12)
    return Q if not Q.is_empty else P.buffer(0)

def fairway_shape(form, line, Ltot, s0, s1, ws, green, gr, rng, noise):
    """Polygone du fairway le long de la ligne de jeu, selon une famille de formes."""
    def frame(s):
        p = line.interpolate(s); q = line.interpolate(min(Ltot, s + 5)); r = line.interpolate(max(0, s - 5))
        dx, dz = q.x - r.x, q.y - r.y; n = math.hypot(dx, dz) or 1
        return p.x, p.y, -dz / n, dx / n
    def ribbon(a, b, wfun, off=lambda s: 0.0, n=70):
        L_, R_ = [], []
        for s in np.linspace(a, b, n):
            x, z, nx, nz = frame(s); w = max(18.0, wfun(s)); o = off(s)
            L_.append((x + nx * (o + w), z + nz * (o + w))); R_.append((x + nx * (o - w), z + nz * (o - w)))
        return Polygon(L_ + R_[::-1]).buffer(0)
    def taper(s): return max(0.45, min(1, (s - s0) / 260, (s1 - s) / 200 + 0.55))
    base_w = lambda s: ws * (1 + 0.16 * noise(*frame(s)[:2], 900)) * taper(s)
    if form == 'aucun' or s1 - s0 < 200:
        return Polygon()
    if form == 'ruban':
        P = ribbon(s0, s1, base_w)
    elif form == 'iles':                       # 2 a 4 iles de fairway separees par du rough
        k = rng.randint(2, 4); cuts = sorted(rng.uniform(s0 + 150, s1 - 150) for _ in range(k - 1))
        bounds = [s0] + cuts + [s1]; parts = []
        for i in range(k):
            a_, b_ = bounds[i] + (rng.uniform(70, 160) if i else 0), bounds[i + 1] - (rng.uniform(70, 160) if i < k - 1 else 0)
            if b_ - a_ > 120: parts.append(ribbon(a_, b_, lambda s: base_w(s) * rng.uniform(0.85, 1.25)))
        P = unary_union(parts)
    elif form == 'chapelet':                   # perles : largeur qui pulse fortement
        lam = rng.uniform(380, 650); ph = rng.uniform(0, 6.28)
        P = ribbon(s0, s1, lambda s: ws * (0.28 + 0.95 * abs(math.sin(math.pi * s / lam + ph))) * taper(s), n=140)
    elif form == 'serpent':                    # fairway etroit qui ondule autour de la ligne
        A = rng.uniform(90, 170); lam = rng.uniform(450, 800); ph = rng.uniform(0, 6.28)
        P = ribbon(s0, s1, lambda s: ws * 0.62 * taper(s), off=lambda s: A * math.sin(2 * math.pi * s / lam + ph) * min(1, (s1 - s) / 300), n=140)
    elif form == 'fourche':                    # deux couloirs autour d'un ilot de rough central
        P = ribbon(s0, s1, lambda s: base_w(s) * 1.35)
        a_ = rng.uniform(s0 + 120, s0 + 0.4 * (s1 - s0)); b_ = rng.uniform(a_ + 300, s1 - 120)
        if b_ > a_ + 200:
            P = P.difference(ribbon(a_, b_, lambda s: ws * 0.75 * math.sin(math.pi * (s - a_) / (b_ - a_)) + 10))
    elif form == 'gruyere':                    # large fairway perce d'ilots de rough
        P = ribbon(s0, s1, lambda s: base_w(s) * 1.3)
        for _ in range(rng.randint(2, 5)):
            x, z, nx, nz = frame(rng.uniform(s0 + 100, s1 - 100)); o = rng.uniform(-0.6, 0.6) * ws
            P = P.difference(blob(x + nx * o, z + nz * o, rng.uniform(35, 70), rng, 0.25))
    elif form == 'trompette':                  # etroit au depart, tres large a l'atterrissage, puis goulot
        m = rng.uniform(0.45, 0.7)
        def wt(s):
            t = (s - s0) / max(1, s1 - s0)
            return ws * (0.35 + 1.25 * math.exp(-((t - m) / 0.18) ** 2)) * taper(s)
        P = ribbon(s0, s1, wt, n=120)
    elif form == 'damier':                     # zones d'atterrissage decalees gauche / droite
        k = rng.randint(3, 5); parts = []; side = rng.choice((-1, 1))
        for i in range(k):
            s = s0 + (i + 0.5) * (s1 - s0) / k; x, z, nx, nz = frame(s); o = side * ws * rng.uniform(0.5, 0.9)
            parts.append(blob(x + nx * o, z + nz * o, ws * rng.uniform(1.0, 1.4), rng, 0.15, stretch=1.5,
                              ang=math.atan2(nz, nx) + 1.57)); side = -side
        parts.append(ribbon(s0, s1, lambda s: ws * 0.3))   # fin couloir qui relie le tout
        P = unary_union(parts)
    elif form == 'nuages':                     # union de taches irregulieres de tailles tres variees
        parts = []
        for _ in range(rng.randint(7, 13)):
            x, z, nx, nz = frame(rng.uniform(s0, s1)); o = rng.uniform(-0.5, 0.5) * ws
            parts.append(blob(x + nx * o, z + nz * o, ws * rng.uniform(0.45, 1.1), rng, 0.3, stretch=rng.uniform(1, 2.2), ang=rng.uniform(0, 3.14)))
        P = unary_union(parts)
    elif form == 'dents':                      # bords en vagues (arrondies)
        lam = rng.uniform(220, 360); amp = rng.uniform(0.25, 0.4); ph = rng.uniform(0, 6.28)
        P = ribbon(s0, s1, lambda s: base_w(s) * (1 + amp * math.sin(2 * math.pi * s / lam + ph)), n=200)
    elif form == 'croissant':                  # grand arc de cercle au-dela de la ligne (ou devant le green en par 3)
        x, z, nx, nz = frame(s0 + 0.6 * (s1 - s0)); side = rng.choice((-1, 1))
        R_ = ws * rng.uniform(2.2, 3.0)
        outer = Point(x + nx * side * ws * 0.4, z + nz * side * ws * 0.4).buffer(R_)
        inner = Point(x + nx * side * (ws * 0.4 + R_ * 0.5), z + nz * side * (ws * 0.4 + R_ * 0.5)).buffer(R_ * 0.72)
        P = unary_union([outer.difference(inner), ribbon(s0, s1, lambda s: ws * 0.35)])
    elif form == 'pastille':                   # par 3 : petite zone de fairway posee devant le green
        x, z, nx, nz = frame(max(s0, Ltot - gr - rng.uniform(220, 380)))
        P = blob(x, z, rng.uniform(90, 140), rng, 0.25, stretch=rng.uniform(1.2, 2.0), ang=rng.uniform(0, 3.14))
    else:
        P = ribbon(s0, s1, base_w)
    if form in ('chapelet', 'croissant') and Ltot < 2000:   # par 3 : formes reduites devant le green
        x, z, nx, nz = frame(max(0, Ltot - gr - 300))
        P = P.intersection(Point(x, z).buffer(320))
    P = rounded(P, 45)
    if hasattr(P, 'geoms'):
        P = unary_union([g for g in P.geoms if g.area > 15000])
    return P if not P.is_empty else Polygon()


def generate(tpl, seed, par=4, free=True):
    rng = random.Random(seed)
    noise = Noise(rng)
    isl = tpl.island
    inner = isl.buffer(-330)
    inner_p = prep(inner)
    x0, z0, x1, z1 = isl.bounds
    cx = (x0 + x1) / 2
    # zone jouable de Nintendo pour ce creneau : le jeu refuse un depart hors de cette zone
    if not hasattr(tpl, 'inb'):
        from kcl import read_kcl as _rk
        from kcltri import tri_vertices as _tv
        k_ = _rk(tpl.kcl) if isinstance(tpl.kcl, str) else tpl.kcl
        P_ = np.array([np.array(_tv(k_, p_)) for p_ in k_['prisms'] if p_[6] in (0x101, 0x102, 0x103, 0x106, 0x109)]).reshape(-1, 3)
        tpl.inb = (float(P_[:, 0].min()), float(P_[:, 2].min()), float(P_[:, 0].max()), float(P_[:, 2].max()))
    if not hasattr(tpl, 'inb_poly'):
        from kcl import read_kcl as _rk
        from kcltri import tri_vertices as _tv
        k_ = tpl.kcl
        tp_ = [Polygon([(v[0], v[2]) for v in _tv(k_, p_)]) for p_ in k_['prisms'] if p_[6] in (0x101, 0x102, 0x103, 0x106, 0x109)]
        u_ = unary_union([t.buffer(0.5) for t in tp_ if t.area > 0.01]).buffer(-0.5)
        if not isinstance(u_, Polygon): u_ = max(u_.geoms, key=lambda q: q.area)
        tpl.inb_poly = Polygon(u_.exterior).simplify(10)
    # zone acceptee par le jeu (deduite des tests en jeu) : boite de la zone jouable de Nintendo
    # ET couloir de ~560 u autour de l'axe depart -> drapeau du trou d'origine
    t0_ = [o for o in tpl.pmp if (o['grp'], o['typ']) == (2, 0)][0]['pos']
    g0_ = [o for o in tpl.pmp if (o['grp'], o['typ']) == (11, 1)][0]['pos']
    inb = box(*tpl.inb).intersection(LineString([(t0_[0], t0_[2]), (g0_[0], g0_[2])]).buffer(560))
    inb_in = prep(inb.buffer(-260))
    ix0, iz0, ix1, iz1 = tpl.inb
    tee_box = box(ix0 + 250, iz0 + 250, ix1 - 250, iz1 - 120)
    # ---------------------------------------------------------- trace
    # styles : droit, dogleg (un virage franc), S (deux virages opposes), banane (courbe continue)
    if free:
        styles = {3: [('droit', 2), ('leger', 4)],
                  4: [('droit', 1), ('dogleg', 4), ('S', 4), ('banane', 2), ('crochet', 2)],
                  5: [('dogleg', 2), ('S', 4), ('banane', 2), ('zigzag', 3), ('crochet', 2)]}[par]
        style = rng.choices([k for k, _ in styles], [w for _, w in styles])[0]
    else:
        style = 'ancien'
    icx, icz = inner.centroid.x, inner.centroid.y
    ib = inner.bounds
    def chaikin(pts, it=3):
        for _ in range(it):
            q = [pts[0]]
            for a_, b_ in zip(pts, pts[1:]):
                q += [(0.75 * a_[0] + 0.25 * b_[0], 0.75 * a_[1] + 0.25 * b_[1]), (0.25 * a_[0] + 0.75 * b_[0], 0.25 * a_[1] + 0.75 * b_[1])]
            q.append(pts[-1]); pts = q
        return pts
    def resample(pts, n=200):
        ls = LineString(pts); return [(ls.interpolate(t, normalized=True).x, ls.interpolate(t, normalized=True).y) for t in np.linspace(0, 1, n)]
    t0_ = [o for o in tpl.pmp if (o['grp'], o['typ']) == (2, 0)][0]['pos']
    g0_ = [o for o in tpl.pmp if (o['grp'], o['typ']) == (11, 1)][0]['pos']
    nD_ = math.hypot(g0_[0] - t0_[0], g0_[2] - t0_[2]); nu_ = ((g0_[0] - t0_[0]) / nD_, (g0_[2] - t0_[2]) / nD_)
    frame_p = prep(box(*tpl.inb).buffer(350))
    for attempt in range(1500 if free else 400):
        L = rng.uniform(*LEN[par])
        if style == 'ancien':
            zt_ = iz1 - rng.uniform(390, 560)
            xs_ = [x_ for x_ in np.linspace(ix0, ix1, 60) if inb_in.contains(Point(x_, zt_))]
            if not xs_: continue
            tee = (rng.uniform(min(xs_), max(xs_)), zt_)
            ang = math.radians(180 + rng.uniform(-14, 14))
            dog = 0.0 if rng.random() < 0.35 else rng.uniform(-1, 1) * (0.12 if par == 3 else 0.22)
            green = (tee[0] + L * math.sin(ang), tee[1] + L * math.cos(ang))
            mid = ((tee[0] + green[0]) / 2, (tee[1] + green[1]) / 2)
            perp = (math.cos(ang), -math.sin(ang))
            ctrl = (mid[0] + perp[0] * dog * L, mid[1] + perp[1] * dog * L)
            path = bezier(tee, ctrl, green)
            sc = L / path_len(path)
            green = (tee[0] + (green[0] - tee[0]) * sc, tee[1] + (green[1] - tee[1]) * sc)
            ctrl = (tee[0] + (ctrl[0] - tee[0]) * sc, tee[1] + (ctrl[1] - tee[1]) * sc)
            path = bezier(tee, ctrl, green)
        else:
            tee = (rng.uniform(ib[0], ib[2]), rng.uniform(ib[1], ib[3]))
            if not inner_p.contains(Point(tee)): continue
            h0 = math.atan2(icz - tee[1], icx - tee[0]) + math.radians(rng.uniform(-40, 40))
            sgn = rng.choice((-1, 1))
            if style == 'droit': segs = [(1.0, 0)]
            elif style == 'leger': segs = [(0.5, 0), (0.5, sgn * rng.uniform(8, 18))]
            elif style == 'dogleg':
                f = rng.uniform(0.45, 0.68); segs = [(f, 0), (1 - f, sgn * rng.uniform(35, 70))]
            elif style == 'crochet':      # virage tres serre en fin de trou
                f = rng.uniform(0.55, 0.7); segs = [(f, 0), (0.12, sgn * 45), (1 - f - 0.12, sgn * rng.uniform(35, 50))]
            elif style == 'S':
                t1 = rng.uniform(35, 60); segs = [(0.3, 0), (0.35, sgn * t1), (0.35, -sgn * rng.uniform(55, 95))]
            elif style == 'zigzag':
                t1 = rng.uniform(35, 55); segs = [(0.25, 0), (0.25, sgn * t1), (0.25, -sgn * 2 * t1 * rng.uniform(0.8, 1.1)), (0.25, sgn * t1)]
            else:   # banane : virages reguliers dans le meme sens
                t1 = rng.uniform(8, 16); segs = [(0.2, 0)] + [(0.2, sgn * t1)] * 4
            pts = [tee]; hd = h0
            for frac, turn in segs:
                hd += math.radians(turn)
                x, z = pts[-1]; pts.append((x + math.cos(hd) * frac * L, z + math.sin(hd) * frac * L))
            path = resample(chaikin(pts, 3))
            sc = L / path_len(path)
            path = [(tee[0] + (x - tee[0]) * sc, tee[1] + (z - tee[1]) * sc) for x, z in path]
            green = path[-1]
        # la mini-carte cadre l'axe depart -> drapeau : le trace doit rester dans ce cadre
        D_ = math.dist(tee, green); u_ = ((green[0] - tee[0]) / D_, (green[1] - tee[1]) / D_)
        lat_ = max(abs((p[0] - tee[0]) * -u_[1] + (p[1] - tee[1]) * u_[0]) for p in path)
        lon_ = [(p[0] - tee[0]) * u_[0] + (p[1] - tee[1]) * u_[1] for p in path]
        cadre = lat_ <= 0.2 * D_ + 120 and min(lon_) > -150 and max(lon_) < D_ + 150 and D_ > 0.7 * L
        # la mini-carte a l'orientation et le cadrage du trou de Nintendo : meme sens general,
        # et tout le trace dans la zone qu'elle montre (zone jouable d'origine elargie)
        dang_ = math.degrees(math.atan2(u_[0] * nu_[1] - u_[1] * nu_[0], u_[0] * nu_[0] + u_[1] * nu_[1]))
        cadre = cadre and abs(dang_) < 50 and all(frame_p.contains(Point(p)) for p in path[::8])
        ok_ = (cadre and all(inner_p.contains(Point(p)) for p in path[::4]) and inner_p.contains(Point(green))
               and inner.buffer(150).contains(LineString([tee, green]))) if free else \
              (all(inb_in.contains(Point(p)) for p in path[::5]) and inb_in.contains(Point(green)))
        if ok_:
            break
    else:
        raise RuntimeError('aucun trace ne tient dans l\'ile')
    line = LineString(path)
    Ltot = line.length
    d_end = (green[0] - path[-6][0], green[1] - path[-6][1]); dn = math.hypot(*d_end)
    approach = (d_end[0] / dn, d_end[1] / dn)                     # direction d'arrivee au green
    d0 = (path[5][0] - tee[0], path[5][1] - tee[1]); d0n = math.hypot(*d0); aim = (d0[0] / d0n, d0[1] / d0n)

    # ---------------------------------------------------------- formes
    gr = rng.uniform(118, 158)
    green_p = blob(green[0], green[1], gr, rng, 0.10, stretch=rng.uniform(0.9, 1.15), ang=rng.uniform(0, 3.14))
    collar_p = green_p.buffer(24).difference(green_p)
    tee_p = blob(tee[0], tee[1], 60, rng, 0.05, stretch=1.6, ang=math.atan2(aim[1], aim[0]))
    s0 = rng.uniform(380, 620) if par > 3 else gr + 120
    s1 = Ltot - gr * rng.uniform(0.6, 0.9)
    ws = rng.uniform(150, 205)
    # forme du fairway : on tire une forme parmi plusieurs familles bien differentes
    _rf = random.Random(seed * 104729 + par * 13 + 7)
    fol = FOLIE.get(getattr(tpl, 'name', ''), 1)
    if par > 3:
        form = _rf.choice([FORMS_SAGES, FORMS, FORMS + FORMS_FOLLES][fol])
    else:
        form = _rf.choice([['aucun', 'aucun', 'pastille', 'croissant'], ['aucun', 'pastille', 'chapelet', 'croissant'],
                           ['pastille', 'chapelet', 'chapelet', 'croissant']][fol])
    fair_p = fairway_shape(form, line, Ltot, s0, s1, ws, green, gr, _rf, noise)
    if not fair_p.is_empty: fair_p = rounded(fair_p, 35)           # jamais d'angle, quelle que soit la forme
    if par > 3 and not fair_p.is_empty:      # le fairway rejoint toujours l'avant du green
        fair_p = rounded(unary_union([fair_p, LineString(path[-40:]).buffer(ws * 0.45)]), 45)
    # bunkers
    bunkers = []
    nb = rng.randint(*BUNKERS[par]) + FOLIE.get(getattr(tpl, 'name', ''), 1) - 1
    n_green = min(nb, rng.randint(1, 2))
    for i in range(n_green):
        side = rng.choice((-1, 1)); a = math.atan2(approach[1], approach[0]) + side * math.radians(rng.uniform(55, 130))
        dist = gr + rng.uniform(35, 70)
        bx, bz = green[0] + math.cos(a) * dist, green[1] + math.sin(a) * dist
        bunkers.append(blob(bx, bz, rng.uniform(45, 75), rng, 0.18, stretch=rng.uniform(1.3, 2.0), ang=a + 1.57))
    for i in range(nb - n_green):
        s = rng.uniform(0.55, 0.78) * Ltot if par > 3 else rng.uniform(0.3, 0.6) * Ltot
        p = line.interpolate(s); q = line.interpolate(min(Ltot, s + 5))
        dx, dz = q.x - p.x, q.y - p.y; n = math.hypot(dx, dz) or 1
        side = rng.choice((-1, 1)); off = ws + rng.uniform(-30, 70)
        bx, bz = p.x - dz / n * off * side, p.y + dx / n * off * side
        bunkers.append(blob(bx, bz, rng.uniform(55, 95), rng, 0.2, stretch=rng.uniform(1.4, 2.4), ang=math.atan2(dz, dx)))
    if par > 3 and rng.random() < 0.55:                  # bunker en travers du fairway
        s_ = rng.uniform(0.5, 0.72) * Ltot; p_ = line.interpolate(s_); q_ = line.interpolate(min(Ltot, s_ + 5))
        dx, dz = q_.x - p_.x, q_.y - p_.y; nn = math.hypot(dx, dz) or 1
        bunkers.append(blob(p_.x, p_.y, rng.uniform(45, 70), rng, 0.15, stretch=rng.uniform(2.2, 3.2), ang=math.atan2(-dx, dz)))
    for _ in range(rng.randint(0, 2) if par > 3 else 0):   # petits bunkers-pots au milieu
        s_ = rng.uniform(0.35, 0.8) * Ltot; p_ = line.interpolate(s_)
        bunkers.append(blob(p_.x + rng.uniform(-60, 60), p_.y + rng.uniform(-60, 60), rng.uniform(28, 40), rng, 0.15))
    bunk_p = unary_union([b.simplify(5) for b in bunkers]) if bunkers else Polygon()
    if 'M_Bunker' not in set(tpl.o2m.values()): bunk_p = Polygon()   # pas de sable dans le modele (fcJP13) : sinon trou dans la carte
    # etang (obstacle d'eau) : devant le green ou le long du fairway
    pond = Polygon(); REJ = collections.Counter(); feature = 'etang'
    _r2 = random.Random(seed * 7919 + par * 31 + 5)
    _pr = _r2.random(); _pf = _r2.random()
    has_water = getattr(tpl, 'water_mat', None)
    if has_water and par == 3 and _pf < 0.35:
        # green-ile : anneau d'eau autour du green, on y arrive en l'air
        feature = 'green-ile'
        ring = green_p.buffer(24 + 150 + _r2.uniform(0, 70)).difference(green_p.buffer(24 + 22))
        ring = ring.simplify(4)
        if isl.buffer(-140).contains(ring.envelope.intersection(isl)) and not ring.intersects(tee_p.buffer(160)):
            pond = Polygon(ring.exterior, [ring.interiors[0]]) if ring.geom_type == 'Polygon' and ring.interiors else Polygon()
            bunk_p = bunk_p.difference(ring.buffer(30)) if not bunk_p.is_empty else bunk_p
        _pr = 1.0
    # green sur une ile : bras de mer en anneau autour du green (on le franchit en l'air), rives en roche
    sea_p = Polygon(); sea_isle = Polygon(); oy_ = getattr(tpl, 'ocean_y', None)
    _rs = random.Random(seed * 6151 + par * 3 + 11)
    if oy_ is not None and feature != 'green-ile' and _rs.random() < SEA_P * (0.6, 1.15, 1.7)[FOLIE.get(tpl.name, 1)] and tpl.base_height(*green) - oy_ < 220:
        for _ in range(12):
            isle = rounded(blob(green[0], green[1], gr + _rs.uniform(95, 160), _rs, 0.10, n=64, nh=3,
                                stretch=_rs.uniform(1.0, 1.3), ang=_rs.uniform(0, 3.14)), 50)
            outer = rounded(isle.buffer(_rs.uniform(170, 300) if par > 3 else _rs.uniform(200, 340)), 80)
            ring = outer.difference(isle).intersection(isl)
            if ring.is_empty or outer.intersects(tee_p.buffer(450)): continue
            if not isl.buffer(-40).contains(green_p.buffer(70)): continue
            sea_p = rounded(ring, 30).simplify(4); sea_isle = isle.intersection(isl); feature = 'ile-mer'; _pr = 1.0
            if not bunk_p.is_empty:                      # pas de bunker sur les pentes qui descendent vers la mer
                keep_isle = bunk_p.intersection(sea_isle.buffer(-(SHORE_W + 45)))
                bunk_p = unary_union([bunk_p.difference(sea_p.buffer(SHORE_W + 200)).difference(sea_isle), keep_isle])
            fair_p = rounded(fair_p.difference(sea_p.buffer(50)), 40) if not fair_p.is_empty else fair_p
            break
    if has_water and _pr < POND_P.get(par, 0.5) * (0.8, 1.0, 1.3)[FOLIE.get(tpl.name, 1)]:
        avoid = unary_union([green_p.buffer(55), tee_p.buffer(140), bunk_p.buffer(35)])
        for _ in range(40):
            r = rng.uniform(110, 210)
            if rng.random() < (0.8 if par == 3 else 0.45):   # devant le green, a traverser
                s = Ltot - gr - r * rng.uniform(0.9, 1.4) - 30
                p = line.interpolate(max(s, 0.3 * Ltot)); lat = rng.uniform(-0.5, 0.5) * r
            else:                                            # sur le cote du fairway
                s = rng.uniform(0.3, 0.75) * Ltot; p = line.interpolate(s)
                lat = rng.choice((-1, 1)) * (ws + r * rng.uniform(0.5, 0.9))
            q = line.interpolate(min(Ltot, s + 5)); dx, dz = q.x - p.x, q.y - p.y; nn = math.hypot(dx, dz) or 1
            cx_, cz_ = p.x - dz / nn * lat, p.y + dx / nn * lat
            cand = rounded(blob(cx_, cz_, r, rng, 0.06, n=64, stretch=rng.uniform(1.0, 1.45), ang=rng.uniform(0, 3.14), nh=2), 40).simplify(2)
            if cand.intersects(avoid): REJ['avoid'] += 1; continue
            if not free and not inb.buffer(-60).contains(cand): REJ['zone'] += 1; continue
            if not isl.buffer(-140).contains(cand): REJ['ile'] += 1; continue
            pond = cand; break
    green_p = green_p.simplify(4); collar_p = green_p.buffer(24, resolution=6).difference(green_p)
    tee_p = tee_p.simplify(4); fair_p = fair_p.simplify(4)
    play = unary_union([fair_p, green_p, collar_p, tee_p, bunk_p, pond])
    # couloir continu depart -> green : jamais de hors-limite sous la trajectoire
    corridor = LineString(path).buffer(ws * 1.1)
    # tir tout droit depuis le depart : toujours en jeu (rough), jamais hors limite
    drive = LineString([tee, (tee[0] + aim[0] * 2000, tee[1] + aim[1] * 2000)]).buffer(260)
    corridor = unary_union([corridor, drive])
    _rr = random.Random(seed * 7907 + par)
    rough_zone = unary_union([play, corridor]).buffer(_rr.uniform(330, 600)).buffer(-60).buffer(60)
    if isinstance(rough_zone, Polygon):
        edge = list(rough_zone.exterior.coords)
        for _ in range(_rr.randint(0, 3)):               # lobes de rough qui debordent
            x_, z_ = edge[_rr.randrange(len(edge))]
            rough_zone = rough_zone.union(blob(x_, z_, _rr.uniform(150, 320), _rr, 0.25, stretch=_rr.uniform(1, 2), ang=_rr.uniform(0, 3.14)))
        for _ in range(_rr.randint(1, 4)):               # doigts de hors-limite qui entrent dans le rough
            x_, z_ = edge[_rr.randrange(len(edge))]
            cut = blob(x_, z_, _rr.uniform(120, 260), _rr, 0.3, stretch=_rr.uniform(1.5, 2.8), ang=_rr.uniform(0, 3.14))
            rough_zone = rough_zone.difference(cut.difference(unary_union([play, corridor]).buffer(110)))
        rough_zone = rounded(rough_zone, 70)
    if not isinstance(rough_zone, Polygon): rough_zone = max(rough_zone.geoms, key=lambda q: q.area)
    # bord du rough legerement ondule
    if isinstance(rough_zone, Polygon):
        ext = list(rough_zone.exterior.coords)
        ext2 = [(x + 45 * noise(x, z, 500), z + 45 * noise(z, x, 500)) for x, z in ext]
        rough_zone = Polygon(ext2).buffer(0)
    rough_zone = rough_zone.intersection(isl.buffer(-120)).simplify(6)
    rough_zone = unary_union([rough_zone, corridor.buffer(150).intersection(isl.buffer(-120))])
    rough_zone = rounded(rough_zone, 60).intersection(isl.buffer(-120))
    if not free: rough_zone = rough_zone.intersection(inb.buffer(-15))
    if not isinstance(rough_zone, Polygon): rough_zone = max(rough_zone.geoms, key=lambda q: q.area)

    regions = collections.OrderedDict()
    regions['green'] = green_p
    regions['collar'] = collar_p
    regions['bunker'] = rounded(rounded(bunk_p, 12).difference(green_p.union(collar_p).buffer(14)), 10) if not bunk_p.is_empty else Polygon()
    taken = unary_union([regions['green'], regions['collar'], regions['bunker']])
    regions['sea'] = sea_p.difference(taken) if not sea_p.is_empty else Polygon()
    taken = unary_union([taken, regions['sea']])
    bank_p = pond.buffer(26).difference(pond) if not pond.is_empty else Polygon()
    regions['water'] = pond
    regions['bank'] = bank_p.difference(taken)
    taken = unary_union([taken, pond, regions['bank']])
    regions['shore'] = sea_p.buffer(SHORE_W, resolution=6).simplify(4).difference(taken) if not sea_p.is_empty else Polygon()
    taken = unary_union([taken, regions['shore']])
    # fairway : un liseré de rough autour des bunkers / du green, et pas de pointe la ou deux courbes se croisent
    regions['fairway'] = rounded(unary_union([fair_p, tee_p]).difference(taken.buffer(10)), 14).difference(taken)
    taken = taken.union(regions['fairway'])
    regions['rough'] = rough_zone.difference(taken)
    regions['ob'] = isl.difference(rough_zone.union(taken))
    if not sea_p.is_empty:                               # l'ile du green : herbe (rough) jusqu'a la rive
        isle_ = sea_isle.difference(sea_p)
        regions['rough'] = unary_union([regions['rough'], regions['ob'].intersection(isle_)])
        regions['ob'] = regions['ob'].difference(isle_)

    # ---------------------------------------------------------- maillage
    # frontieres echantillonnees a pas fixe + points interieurs par zone,
    # triangulation contrainte sans raffinement (nombre de triangles borne)
    STEP = {'shore': 55, 'sea': 80, 'island': 220, 'ob': 220, 'rough': 110, 'fairway': 45, 'green': 15, 'collar': 15, 'bunker': 20, 'water': 30, 'bank': 18}
    SPACING = {'shore': 0, 'sea': 220, 'ob': 520, 'rough': 230, 'fairway': 150, 'green': 15, 'collar': 15, 'bunker': 50, 'water': 0, 'bank': 0}
    lines = []
    def add_poly(g, step):
        for pg in (g.geoms if hasattr(g, 'geoms') else [g]):
            if pg.is_empty or not hasattr(pg, 'exterior'): continue
            lines.append(LineString(pg.exterior.coords))
            for h in pg.interiors: lines.append(LineString(h.coords))
    # frontieres sur une grille commune : les bords partages (mer/berge/ile...) deviennent identiques
    import shapely as _sh
    # simplification commune (les bords partages restent identiques) : les arrondis avaient un point tous les
    # ~1,5 u -> archives 2x trop grosses, plus de memoire en jeu (plantage). Le contour de l'ile ne bouge pas.
    ks = [k for k in regions if not regions[k].is_empty]
    try:
        simp = _sh.coverage_simplify([_sh.make_valid(regions[k]) for k in ks], 2.0, simplify_boundary=False)
        for k, gk in zip(ks, simp):
            if not gk.is_empty: regions[k] = gk
    except Exception:
        pass
    for k in list(regions):
        if not regions[k].is_empty: regions[k] = _sh.set_precision(regions[k], 0.5)
    add_poly(_sh.set_precision(isl, 0.5), STEP['island'])
    for k, g in regions.items(): add_poly(g, STEP[k])
    # chaque frontiere n'existe qu'une fois apres le noeud : on la simplifie (les arrondis ont un point tous les
    # ~4 u, inutile) puis on la redecoupe au pas de la region la plus fine qu'elle borde
    from shapely.ops import linemerge as _lm
    noded = unary_union(lines)
    fine = unary_union([regions[k] for k in ('green', 'collar', 'bunker', 'water', 'bank') if not regions[k].is_empty]).buffer(3)
    mid_ = unary_union([regions[k] for k in ('fairway', 'sea', 'shore') if not regions[k].is_empty]).buffer(3)
    out_ = []
    for ls in (noded.geoms if hasattr(noded, 'geoms') else [noded]):
        ls2 = ls.simplify(1.2 if fine.intersects(ls) else 2.5)
        st = STEP['green'] if fine.intersects(ls2) and fine.contains(ls2.interpolate(0.5, normalized=True)) else \
             STEP['fairway'] if mid_.contains(ls2.interpolate(0.5, normalized=True)) else STEP['rough']
        out_.append(ls2.segmentize(st))
    noded = unary_union(out_)
    verts, vidx, segs = [], {}, set()
    def vid(p):
        k = (round(p[0], 1), round(p[1], 1))
        if k not in vidx: vidx[k] = len(verts); verts.append(k)
        return vidx[k]
    for ls in (noded.geoms if hasattr(noded, 'geoms') else [noded]):
        c = list(ls.coords)
        for a_, b_ in zip(c, c[1:]):
            ia, ib = vid(a_), vid(b_)
            if ia != ib: segs.add((min(ia, ib), max(ia, ib)))
    # maillage du trou comme chez Nintendo : un sommet exactement au trou, une grille de 15 sur 60 x 60
    # (carres de 30 et 60 contraints) -> petits triangles autour de la coupe
    # Emplacements de drapeau : le jeu cree un objet par (2, 1), en tire UN comme trou et pose un BOUCHON
    # sur les autres. Ils doivent donc etre distincts (sinon les bouchons couvrent le trou). Chacun recoit
    # le maillage du trou de Nintendo (sommet au centre, grille de 15).
    n_pins = max(1, sum(1 for o in tpl.pmp if (o['grp'], o['typ']) == (2, 1)))
    pin_zone = regions['green'].buffer(-34)
    pins = [tuple(green)]
    _rp = random.Random(seed * 977 + 5)
    for half, sep in ((2, 64.0), (1, 36.0)):
        tries = 0
        while len(pins) < n_pins + 1 and tries < 600:
            tries += 1
            bx0, bz0, bx1, bz1 = pin_zone.bounds if not pin_zone.is_empty else (0, 0, 0, 0)
            if pin_zone.is_empty: break
            q = (_rp.uniform(bx0, bx1), _rp.uniform(bz0, bz1))
            if not pin_zone.contains(Point(q)): continue
            if all(math.hypot(q[0] - p_[0], q[1] - p_[1]) >= sep for p_ in pins): pins.append(q)
        if len(pins) >= n_pins + 1: break
    pin_half = {}
    for k_, (px_, pz_) in enumerate(pins):
        hf = 2 if (k_ == 0 or all(math.hypot(px_ - q_[0], pz_ - q_[1]) >= 64 for q_ in pins if q_ != (px_, pz_))) else 1
        pin_half[(px_, pz_)] = hf
        # comme Nintendo : la grille est DECALEE pour que le trou soit au centre inscrit d'un demi-carre
        # (triangle rectangle de cotes 15, a 4.39 de chaque bord). Le jeu ne perce QUE le triangle KCL
        # sous le drapeau : un sommet au trou (5 a 7 triangles) laisse la balle rouler dessus.
        ox_, oz_ = px_ - CUP_R, pz_ - CUP_R
        grid_ = {}
        for i_ in range(-hf, hf + 1):
            for j_ in range(-hf, hf + 1): grid_[(i_, j_)] = vid((ox_ + 15.0 * i_, oz_ + 15.0 * j_))
        ia, ib = grid_[(1, 0)], grid_[(0, 1)]; segs.add((min(ia, ib), max(ia, ib)))   # diagonale du demi-carre
        for r_ in range(1, hf + 1):
            ring_ = [(i_, -r_) for i_ in range(-r_, r_)] + [(r_, j_) for j_ in range(-r_, r_)] + \
                    [(i_, r_) for i_ in range(r_, -r_, -1)] + [(-r_, j_) for j_ in range(r_, -r_, -1)]
            for a_, b_ in zip(ring_, ring_[1:] + ring_[:1]):
                ia, ib = grid_[a_], grid_[b_]; segs.add((min(ia, ib), max(ia, ib)))
    def in_cup_box(x, z):
        return any(abs(x - p_[0] + CUP_R) < 15 * h_ + 18 and abs(z - p_[1] + CUP_R) < 15 * h_ + 18 for p_, h_ in pin_half.items())
    for k, g in regions.items():
        sp = SPACING[k]
        if not sp or g.is_empty: continue
        pg = prep(g.buffer(-sp * 0.4))
        bx0, bz0, bx1, bz1 = g.bounds
        for gx_ in np.arange(bx0 + sp / 2, bx1, sp):
            for gz_ in np.arange(bz0 + sp / 2, bz1, sp):
                x = gx_ + rng.uniform(-0.3, 0.3) * sp; z = gz_ + rng.uniform(-0.3, 0.3) * sp
                if pg.contains(Point(x, z)) and not in_cup_box(x, z): vid((x, z))
    T = tr.triangulate({'vertices': np.array(verts), 'segments': np.array(sorted(segs))}, 'p')
    V = T['vertices']; F = T['triangles']
    prepared = {k: prep(g) for k, g in regions.items()}
    isl_p = prep(isl)
    labels, tris = [], []
    for f in F:
        c = V[f].mean(0); pt = Point(c)
        if not isl_p.contains(pt): continue
        lab = 'ob'
        for k in ('green', 'collar', 'bunker', 'sea', 'water', 'bank', 'shore', 'fairway', 'rough'):
            if prepared[k].contains(pt): lab = k; break
        labels.append(lab); tris.append(f)

    # ---------------------------------------------------------- relief
    edge = isl.exterior
    gpt = Point(green)
    g_h = None
    H = np.zeros(len(V))
    _re = random.Random(seed * 131 + par)
    tee_h = tpl.base_height(*tee) + 10 + (_re.uniform(0, 55) if free else 0)   # depart sureleve
    exact = LinearNDInterpolator(tpl.top_pts[:, [0, 2]], tpl.top_pts[:, 1]) if hasattr(tpl, 'top_pts') else None
    for i, (x, z) in enumerate(V):
        base = tpl.base_height(x, z)
        dedge = edge.distance(Point(x, z))
        w = min(1.0, dedge / 700.0) ** 2
        h = base + w * (RELIEF * 85 * noise(x, z, 2100) + RELIEF * 34 * noise(x + 999, z, 700) + RELIEF * 9 * noise(x, z + 555, 260))
        # buttes qui encadrent le fairway (dans le rough, a 60-260 du bord)
        if not fair_p.is_empty:
            df = fair_p.distance(Point(x, z))
            if 50 < df < 280:
                k_ = math.sin(math.pi * (df - 50) / 230)
                h += RELIEF * 26 * k_ * max(0.0, noise(x - 333, z + 77, 330) + 0.25)
        H[i] = h
    # green : plan legerement incline, depart : plat, bunkers : creux
    gh = np.mean([H[i] for i, (x, z) in enumerate(V) if green_p.buffer(30).contains(Point(x, z))] or [tpl.base_height(*green)])
    if free: gh += _re.uniform(-45, 40)                       # green en contrebas ou perche
    slope = rng.uniform(0.008, 0.02)
    Gr_ = unary_union([green_p, regions['green']]) if not regions['green'].is_empty else green_p
    for i, (x, z) in enumerate(V):
        p = Point(x, z)
        dg = Gr_.distance(p) if not Gr_.contains(p) else 0.0
        if dg < 160:
            t = 1 - dg / 160.0; t = t * t * (3 - 2 * t)
            plane = gh + slope * ((x - green[0]) * approach[0] + (z - green[1]) * approach[1]) \
                + GREEN_UNDUL * (noise(x + 71, z - 13, 170) + 0.5 * noise(x - 5, z + 9, 110))
            H[i] = H[i] * (1 - t) + plane * t
        dt = tee_p.distance(p) if not tee_p.contains(p) else 0.0
        if dt < 120:
            t = 1 - dt / 120.0; t = t * t * (3 - 2 * t)
            H[i] = H[i] * (1 - t) + tee_h * t
    # bunkers : jamais sur une dune -> terrain ramene a un plan doux (pente <= 5 deg) sous et autour du bunker
    if not regions['bunker'].is_empty:
        for bp in (regions['bunker'].geoms if hasattr(regions['bunker'], 'geoms') else [regions['bunker']]):
            zone = bp.buffer(70); ids = [i for i, (x, z) in enumerate(V) if zone.contains(Point(x, z))]
            if len(ids) < 3: continue
            P_ = V[ids]; A_ = np.c_[P_[:, 0], P_[:, 1], np.ones(len(ids))]
            a_, b_, c_ = np.linalg.lstsq(A_, H[ids], rcond=None)[0]
            gmag = math.hypot(a_, b_); lim = math.tan(math.radians(5))
            if gmag > lim: a_, b_ = a_ * lim / gmag, b_ * lim / gmag
            mx, mz = P_[:, 0].mean(), P_[:, 1].mean(); c0 = H[ids].mean()
            for i in ids:
                x, z = V[i]; p = Point(x, z)
                d = 0.0 if bp.contains(p) else bp.distance(p)
                t = 1 - d / 70.0; t = t * t * (3 - 2 * t)
                t *= min(1.0, green_p.distance(p) / 40.0)          # le green garde son plan
                H[i] = H[i] * (1 - t) + (c0 + a_ * (x - mx) + b_ * (z - mz)) * t
    Bk_ = regions['bunker']
    for i, (x, z) in enumerate(V):
        p = Point(x, z)
        if not Bk_.is_empty and Bk_.contains(p):                # creux : seulement dans le bunker final (jamais sous le green)
            H[i] -= min(22, Bk_.boundary.distance(p) * 0.35)
    if exact is not None:
        for i, (x, z) in enumerate(V):
            de = edge.distance(Point(x, z))
            if de < 180:
                e_ = exact(x, z)
                if np.isfinite(e_):
                    t = de / 180.0; t = t * t * (3 - 2 * t)
                    H[i] = float(e_) * (1 - t) + H[i] * t
    # loin de la zone jouable : le terrain d'origine de Nintendo, tel quel (collines qui cachent le pied du decor
    # de fond, chateau...). Tout l'effort de generation va a la zone jouable.
    if exact is not None:
        import shapely as _sh
        dz_ = _sh.distance(rough_zone.buffer(0), _sh.points(V))
        for i, (x, z) in enumerate(V):
            if dz_[i] > FAR0:
                e_ = exact(x, z)
                if np.isfinite(e_):
                    t = min(1.0, (dz_[i] - FAR0) / FAR1); t = t * t * (3 - 2 * t)
                    # grandes dunes de decor (jamais sous le relief de Nintendo), sauf pres du rivage
                    de_ = edge.distance(Point(x, z)); tc = min(1.0, max(0.0, (de_ - 200.0) / 300.0))
                    dune = tc * (DUNE * max(0.0, noise(x + 4321, z - 987, 650) + 0.35) + 0.4 * DUNE * max(0.0, noise(x - 77, z + 4242, 260)))
                    H[i] = H[i] * (1 - t) + (float(e_) + dune) * t
    oy = getattr(tpl, 'ocean_y', None)
    if oy is not None:
        H = np.maximum(H, oy + 18)                       # jamais sous le niveau de la mer
        if not sea_p.is_empty:                           # bras de mer : fond sous l'ocean, rives qui plongent
            SH = 130.0
            for i, (x, z) in enumerate(V):
                p = Point(x, z)
                if sea_p.contains(p) or sea_p.boundary.distance(p) < 0.5:
                    di = sea_p.boundary.distance(p); t = min(1.0, di / 70.0); t = t * t * (3 - 2 * t)
                    H[i] = oy - 6 - 26 * t
                else:
                    d = sea_p.distance(p)
                    on_isle = sea_isle.contains(p)
                    if d < SHORE_W:                              # rive en roche basse : de l'eau a oy + 10
                        H[i] = (oy - 6) + 16.0 * d / SHORE_W
                    elif on_isle:                                # ilot bas et plat (comme Nintendo) : green et bunkers a plat
                        t = min(1.0, (d - SHORE_W) / 35.0); t = t * t * (3 - 2 * t)
                        H[i] = oy + 10 + 8.0 * t + 0.012 * ((x - green[0]) * approach[0] + (z - green[1]) * approach[1]) * t
                    else:                                        # rive d'en face : pente d'herbe douce (pente <= 0,4)
                        W = min(450.0, max(GRASS_W, 2.5 * (H[i] - oy - 10)))
                        if d < SHORE_W + W:
                            t = (d - SHORE_W) / W; t = t * t * (3 - 2 * t)
                            H[i] = (oy + 10) * (1 - t) + max(H[i], oy + 10) * t
    wl = None
    if not pond.is_empty:
        ring_ = pond.buffer(26).exterior
        # niveau d'eau proche du terrain autour (mediane) : etang plein, pas un trou profond
        hs = sorted(H[i] for i, (x, z) in enumerate(V) if 0 < pond.distance(Point(x, z)) < 90)
        wl = (hs[len(hs) // 2] if hs else tpl.base_height(*pond.centroid.coords[0])) - 5
        if oy is not None: wl = max(wl, oy + 62)          # fond (jusqu a wl-55) au-dessus de l ocean
        SHORE = 170.0                                     # rive en pente douce sur 170 unites
        for i, (x, z) in enumerate(V):
            p = Point(x, z)
            if pond.contains(p) or pond.exterior.distance(p) < 0.5: H[i] = wl; continue
            d = pond.distance(p)
            if d < SHORE:
                t = d / SHORE; t = t * t * (3 - 2 * t)
                H[i] = max((wl + 2.5) * (1 - t) + H[i] * t, wl + 2.5)
    P3 = np.c_[V[:, 0], H, V[:, 1]]

    # normales lissees
    N = np.zeros_like(P3)
    for f in tris:
        a, b, c = P3[f]
        n = np.cross(b - a, c - a)
        N[f] += n
    N /= np.linalg.norm(N, axis=1)[:, None] + 1e-9
    for i in range(len(N)):
        if N[i, 1] < 0: N[i] = -N[i]

    # orientation : la normale de chaque triangle doit pointer vers le haut
    tris2 = []
    for f, lab in zip(tris, labels):
        a, b, c = P3[f]
        if np.cross(b - a, c - a)[1] < 0: f = [f[0], f[2], f[1]]
        tris2.append((list(f), lab))

    # fond de l'etang (visible a travers l'eau, et sol pour la balle) : copie 10 unites plus bas
    wt = [f for f, lab in tris2 if lab == 'water']
    if wt:
        ids = sorted({i for f in wt for i in f}); remap = {}
        extra = []
        for i in ids:
            di = pond.boundary.distance(Point(P3[i][0], P3[i][2])); t = min(1.0, di / 80.0); t = t * t * (3 - 2 * t)
            # profondeur comme les lacs de Nintendo (fcJP3 : jusqu'a ~57 sous l'eau)
            remap[i] = len(P3) + len(extra); extra.append(P3[i] - np.array([0.0, 12.0 + 43.0 * t, 0.0]))
        P3 = np.vstack([P3, np.array(extra)]); N = np.vstack([N, np.tile([0.0, 1.0, 0.0], (len(extra), 1))])
        tris2 = [([remap[i] for i in f], 'bed') for f in wt] + tris2
    sea_kcl = []
    if not sea_p.is_empty:
        for f, lab in tris2:
            if lab == 'sea':
                sea_kcl.append(tuple((float(P3[i][0]), float(oy), float(P3[i][2])) for i in f))
        tris2 = [(f, 'seabed' if lab == 'sea' else lab) for f, lab in tris2]
        # rive basse : jamais de roche la ou le terrain touche l'eau a plat -> herbe qui entre dans l'eau
        # (la roche ne reste que sous l'eau, comme fond)
        tris2 = [(f, 'rough' if lab == 'shore' and P3[f][:, 1].max() > oy + 0.5 else lab) for f, lab in tris2]
    return dict(pins=pins, V=P3, N=N, tris=tris2, regions=regions, sea=sea_p, sea_kcl=sea_kcl, ocean_y=oy, tee=tee, green=green, gh=gh, tee_h=tee_h,
                aim=aim, approach=approach, path=path, par=par, gr=gr, seed=seed, Ltot=Ltot, pond=pond, wl=wl, style=style, form=form, feature=feature, water_mat=getattr(tpl, 'water_mat', None), ocean_keep=getattr(tpl, 'ocean_keep', False), rej=REJ, island=isl,
                bank_mat='M_Iwa', iwa_cliff=getattr(tpl, 'iwa_cliff', False))



def validate(tpl, g):
    """Controles de coherence : rien ne flotte, rien ne manque."""
    from shapely.geometry import Polygon as _P
    from shapely.ops import unary_union as _uu
    pb = []
    V = g['V']
    tri = [(f, l) for f, l in g['tris'] if l != 'bed']
    # couverture : somme des aires projetees (le maillage contraint ne se recouvre pas)
    P_ = np.array([V[f][:, [0, 2]] for f, l in tri])
    area = 0.5 * np.abs((P_[:, 1, 0] - P_[:, 0, 0]) * (P_[:, 2, 1] - P_[:, 0, 1]) - (P_[:, 2, 0] - P_[:, 0, 0]) * (P_[:, 1, 1] - P_[:, 0, 1])).sum()
    miss = max(0.0, 1.0 - area / ((g['island'].area - (g['pond'].area if g.get('pond_xf') else 0.0)) if g.get('nmode') else tpl.island.area))
    if miss > 0.002: pb.append('terrain : %.1f %% de l\'ile sans sol' % (100 * miss))
    oy = getattr(tpl, 'ocean_y', None)
    if oy is not None:
        low = [l for f, l in g['tris'] if l not in ('seabed', 'shore') and V[f][:, 1].max() < oy + 1]   # terre entierement noyee
        if low: pb.append('%d triangles sous le niveau de la mer' % len(low))
    nw = sum(1 for f, l in g['tris'] if l == 'water'); nb = sum(1 for f, l in g['tris'] if l == 'bed')
    if nw != nb: pb.append('eau sans fond (%d/%d)' % (nb, nw))
    if nw:
        R = g['regions']; water = R['water']
        shore = water.buffer(30).difference(water)
        land = _uu([R[k] for k in ('bank', 'rough', 'fairway', 'green', 'collar', 'bunker', 'ob') if not R[k].is_empty])
        if shore.difference(land.buffer(2)).area > 0.02 * shore.area: pb.append('rive d\'etang ouverte')
    # ---- regle : loin de la zone jouable, le sol est celui de Nintendo (decor de fond pose dessus) ----
    if hasattr(tpl, 'top_pts'):
        from scipy.interpolate import LinearNDInterpolator as _LI
        import shapely as _sh
        ex_ = getattr(tpl, '_exact', None) or _LI(tpl.top_pts[:, [0, 2]], tpl.top_pts[:, 1]); tpl._exact = ex_
        far = [i for i, d in enumerate(_sh.distance(g['regions']['rough'].buffer(0).union(g['regions']['fairway']), _sh.points(V[:, [0, 2]]))) if d > FAR0 + FAR1 + 10]
        if far:
            e_ = ex_(V[far][:, 0], V[far][:, 2]); ok_ = np.isfinite(e_)
            low = float(np.max(e_[ok_] - V[far][:, 1][ok_])) if ok_.any() else 0.0
            if low > 20: pb.append('hors-limite lointain plus bas que le relief de Nintendo (%.0f) : le decor flotterait' % low)
    # ---- regle : bunkers sur terrain doux (pas sur une dune abrupte) ----
    Nn = np.cross(V[[f[1] for f, l in g['tris']]] - V[[f[0] for f, l in g['tris']]], V[[f[2] for f, l in g['tris']]] - V[[f[0] for f, l in g['tris']]])
    ny = np.abs(Nn[:, 1]) / (np.linalg.norm(Nn, axis=1) + 1e-9)
    lab_ = np.array([l for f, l in g['tris']])
    B_ = g['regions'].get('bunker')
    if B_ is not None and not B_.is_empty:
        import shapely as _sh
        for bp in (B_.geoms if hasattr(B_, 'geoms') else [B_]):
            ring = np.array(bp.exterior.coords)[:-1]
            if len(ring) < 4: continue
            idx = np.unique(np.argmin(((V[:, [0, 2]][None, :, :] - ring[:, None, :]) ** 2).sum(2), axis=1))
            P_ = V[idx]
            if len(P_) < 4: continue
            A_ = np.c_[P_[:, 0], P_[:, 2], np.ones(len(P_))]
            cx_, cz_, _ = np.linalg.lstsq(A_, P_[:, 1], rcond=None)[0]
            ang = np.degrees(np.arctan(np.hypot(cx_, cz_)))
            if ang > 9: pb.append('bunker sur une pente trop forte (%.0f deg)' % ang); break
    if (lab_ == 'green').any():
        C_ = (V[[f[0] for f, l in g['tris']]] + V[[f[1] for f, l in g['tris']]] + V[[f[2] for f, l in g['tris']]]) / 3
        dc = np.hypot(C_[:, 0] - g['green'][0], C_[:, 2] - g['green'][1])
        near = (lab_ == 'green') & (dc < 90)
        if near.any() and ny[near].min() < math.cos(math.radians(7)):        # autour du trou : putting doux
            pb.append('green trop pentu pres du trou (%.0f deg)' % np.degrees(np.arccos(ny[near].min())))
        if ny[lab_ == 'green'].min() < math.cos(math.radians(18)):
            pb.append('green trop pentu (%.0f deg)' % np.degrees(np.arccos(ny[lab_ == 'green'].min())))
    # ---- regle : chaque type de sol utilise doit avoir son materiau dans le modele (sinon trou dans la carte) ----
    _have = set(tpl.o2m.values())
    _miss = sorted({MAT[l] for f, l in g['tris'] if l in MAT and MAT[l] not in _have and not (l == 'water' and g.get('water_mat'))})
    if _miss: pb.append('materiau absent du modele : %s (trou dans la carte)' % ', '.join(_miss))
    # ---- regle : emplacements de drapeau distincts (sinon un bouchon couvre le trou), tous sur le green ----
    P_ = g.get('pins', [])
    n21 = sum(1 for o in tpl.pmp if (o['grp'], o['typ']) == (2, 1))
    if g.get('keep_pins'): P_ = []; n21 = -1               # green et drapeaux de Nintendo gardes tels quels
    if len(P_) < n21 + 1: pb.append('pas assez d\'emplacements de drapeau distincts (%d/%d)' % (len(P_) - 1, n21))
    # ---- regle : chaque trou au milieu d'UN seul triangle (le jeu ne perce que ce triangle), marge >= 3.5 ----
    _V = np.asarray(g['V']); _F = np.array([f for f, l in g['tris']])
    _A, _B, _C = _V[_F[:, 0]][:, [0, 2]], _V[_F[:, 1]][:, [0, 2]], _V[_F[:, 2]][:, [0, 2]]
    def _dseg(p, a, b):
        d = b - a; L = (d * d).sum(1) + 1e-12
        t = np.clip(((p - a) * d).sum(1) / L, 0, 1)
        return np.hypot(*(p - a - d * t[:, None]).T)
    for (px_, pz_) in P_:
        p = np.array([px_, pz_])
        m = np.minimum(np.minimum(_dseg(p, _A, _B), _dseg(p, _B, _C)), _dseg(p, _C, _A))
        if (m < 3.5).any():
            pb.append('trou pres d\'une arete KCL (%.2f) : la balle ne tomberait pas' % m.min()); break
    # ---- regle : pas d'angle vif sur les elements de jeu ----
    def _sharp(geom):
        n = 0
        for p_ in (geom.geoms if hasattr(geom, 'geoms') else [geom]):
            if p_.is_empty or not hasattr(p_, 'exterior'): continue
            c = np.array(p_.exterior.simplify(4).coords)[:-1]
            if len(c) < 4: continue
            a = np.roll(c, 1, 0) - c; b = np.roll(c, -1, 0) - c
            cos = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)
            n += int((cos > 0.5).sum())                                  # angle interieur < 60 degres
        return n
    for k_ in ('fairway', 'green', 'bunker', 'water', 'sea'):
        G_ = g['regions'].get(k_)
        if G_ is not None and not G_.is_empty and _sharp(G_): pb.append('angle vif : %s' % k_)
    # ---- regles de coherence (lacs) ----
    pond = g.get('pond')
    if pond is not None and not pond.is_empty:
        import math as _m
        parts = [] if g.get('pond_xf') else list(pond.geoms) if hasattr(pond, 'geoms') else [pond]   # etangs de Nintendo deplaces : forme d'origine
        for p_ in parts:
            if g.get('feature') == 'green-ile':
                if len(p_.interiors) != 1: pb.append('lac : anneau du green-ile ouvert')
                continue
            if p_.interiors: pb.append('lac : terre au milieu')
            rnd = 4 * _m.pi * p_.area / p_.length ** 2
            if rnd < 0.7: pb.append('lac : forme pas assez ronde (%.2f)' % rnd)
            if p_.area < 15000: pb.append('lac : trop petit')
            if p_.minimum_rotated_rectangle.length and p_.area / p_.minimum_rotated_rectangle.area < 0.65: pb.append('lac : allonge ou creuse')
        if g['tee'] and pond.distance(Point(*g['tee'])) < 120: pb.append('lac : trop pres du depart')
    return pb
