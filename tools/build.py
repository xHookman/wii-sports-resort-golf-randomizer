"""Assemblage d'un trou genere en fichiers du jeu (archive glf_course_XXX.carc)."""
import sys, struct, math, collections
sys.path.insert(0, '/home/user/wsr/tools')
import numpy as np
from gen import Template, MAT, ATTR, _obj2mat
from meshio import value_tris
from mdl0write import replace_geometry, _hdr_offset
from brres import brres_tree
from mdl0 import read_mdl0
from kclwrite import write_kcl
from kcltri import tri_vertices
from pack import write_pmp

REGEN = {'M_OB', 'M_Rough', 'M_Fairway', 'M_Green', 'M_Bunker', 'M_Color', 'M_Sea', 'M_Iwa'}
HIDE = {'M_Kiwa_R', 'M_Kiwa_F', 'M_Kiwa_Black'}
FMTRANGE = {0: (0, 255), 1: (-128, 127), 2: (0, 65535), 3: (-32768, 32767)}


def sink_polygons(data, names):
    """Cache des objets en envoyant tous leurs sommets tres loin sous l'ile
    (seul le tableau de positions est modifie, sur place)."""
    d = bytearray(data)
    t = brres_tree(bytes(d)); mo = t['3DModels(NW4R)'][0][1]; m = read_mdl0(bytes(d), mo)
    for p in m['polys']:
        if p['name'] not in names: continue
        ho = _hdr_offset(d, mo, 'pos', p['ids'][0])
        meta = [mt for n, v, mt in m['arr']['pos'] if mt['idx'] == p['ids'][0]][0]
        cnt = struct.unpack('>H', bytes(d[ho + 0x1E:ho + 0x20]))[0]
        off = ho + struct.unpack('>i', bytes(d[ho + 8:ho + 12]))[0]
        if meta['fmt'] != 4: continue
        for i in range(cnt):
            struct.pack_into('>3f', d, off + meta['stride'] * i, 0.0, -9000.0, 0.0)
        struct.pack_into('>6f', d, ho + 0x20, 0, -9000, 0, 0, -9000, 0)
    return bytes(d)


def _ground(g):
    from scipy.interpolate import LinearNDInterpolator
    keep = sorted({i for f, lab in g['tris'] if lab != 'bed' for i in f})
    V = g['V'][keep]; hi = LinearNDInterpolator(V[:, [0, 2]], V[:, 1]); mean = float(np.nanmean(V[:, 1]))
    def h(x, z):
        v = hi(x, z); return float(v) if np.isfinite(v) else mean
    return h


def strip(poly, width, v0, v1, ustep, h, step=24.0, y=None, a0=255, a1=255, lift=0.4):
    """Ruban le long du contour exterieur de `poly`, vers l'interieur.
    -> triangles de sommets dict(pos, u, v, a)."""
    from shapely.geometry import Polygon as _P, Point as _Pt
    out = []
    geoms = poly.geoms if hasattr(poly, 'geoms') else [poly]
    for pg in geoms:
        if pg.is_empty or pg.area < 1500 or pg.area / pg.length < 8: continue
        ring = pg.exterior; inside = _P(ring)
        n = max(8, int(ring.length / step))
        P = np.array([(ring.interpolate(i / n, normalized=True).x, ring.interpolate(i / n, normalized=True).y) for i in range(n)])
        per = max(1, round(ring.length * ustep))                 # u boucle sur un entier
        rows = []
        for i in range(n):
            t = P[(i + 1) % n] - P[i - 1]; t /= (np.linalg.norm(t) + 1e-9)
            nv = np.array([-t[1], t[0]])
            q = P[i] + nv * width
            if not inside.contains(_Pt(*q)): q = P[i] - nv * width
            u = per * i / n
            rows.append((P[i], q, u))
        for i in range(n):
            (o0, i0, u0), (o1, i1, u1) = rows[i], rows[(i + 1) % n]
            if i == n - 1: u1 = per
            def vtx(p, u, v, a):
                yy = (h(*p) + lift) if y is None else y
                return dict(pos=(float(p[0]), yy, float(p[1])), u=u, v=v, a=a)
            A, B, C, D = vtx(o0, u0, v0, a0), vtx(o1, u1, v0, a0), vtx(i1, u1, v1, a1), vtx(i0, u0, v1, a1)
            out.append([A, B, C]); out.append([A, C, D])
    return out


def special_strips(g):
    """Rubans decoratifs regeneres : bord du rough (Kiwa_OB), levre des bunkers
    (Kiwa_Bunker), ecume au bord de l'etang (XNamiuchi)."""
    from shapely.ops import unary_union
    h = _ground(g); R = g['regions']
    zone = unary_union([R[k] for k in ('rough', 'fairway', 'green', 'collar', 'bunker', 'water', 'bank') if k in R]).buffer(0.5).buffer(-0.5)
    if zone.geom_type != 'Polygon': zone = max(zone.geoms, key=lambda q: q.area)
    res = {'M_Kiwa_OB': strip(zone, 10, 0.0, 0.98, 0.045, h, step=30)}
    res['M_Kiwa_Bunker'] = strip(R['bunker'], 8, 0.0, 0.25, 0.048, h, step=14, lift=0.3) if not R['bunker'].is_empty else []
    if g.get('pond') is not None and not g['pond'].is_empty and not g.get('pond_xf'):
        res['M_XNamiuchi'] = strip(g['pond'], 24, 1.0, 0.0, 0.008, h, step=24, y=g['wl'] + 0.5, a0=255, a1=0)
    return res

def _uv_ok(meta, vals):
    if meta['fmt'] == 4: return True
    lo, hi = FMTRANGE[meta['fmt']]; s = 1 << meta['div']
    return all(lo <= v * s <= hi for vv in vals for v in vv)


# sol des ilots : le trou regenere ne couvre que la plus grande ile ; les autres terres gardent leur dessus
# (sans quoi il ne reste que les falaises). Fairway, green, bunker, avant-green d'origine -> rough.
TO_ROUGH = {'M_Fairway', 'M_Green', 'M_Bunker', 'M_Color'}
def _outside_ground(vt, o2m, g, regen):
    isl = g.get('island')
    if isl is None: return {}
    from shapely.geometry import Point as _Pt
    from shapely.prepared import prep as _prep
    nm = g.get('nmode')
    inside = _prep(isl if nm else isl.buffer(5)); core = _prep(isl.buffer(-150))
    out = collections.defaultdict(list); conv = None
    for name, tl in vt.items():
        mat = o2m.get(name)
        if mat not in regen: continue
        if nm:                                             # mode Nintendo : tout ce qui est hors de la zone reste tel quel
            if conv is None:
                from shapely.geometry import Polygon as _Pg
                from shapely.ops import unary_union as _uu
                cp_ = [_Pg([(v['pos'][0], v['pos'][2]) for v in t]) for n2, tl2 in vt.items()
                       if o2m.get(n2) in ('M_Fairway', 'M_Green', 'M_Color') for t in tl2]
                kg_ = _prep(g['keep_green_poly'].buffer(1)) if g.get('keep_green_poly') is not None else None
                cp_ = [p for p in cp_ if p.area > 0.01 and not inside.contains(p.centroid) and not (kg_ and kg_.contains(p.centroid))]
                conv = _prep(_uu(cp_).buffer(25)) if cp_ else _prep(_Pg())
            for t in tl:
                if min(v['pos'][1] for v in t) < -8000: continue
                cx = sum(v['pos'][0] for v in t) / 3; cz = sum(v['pos'][2] for v in t) / 3
                if inside.contains(_Pt(cx, cz)): continue
                if g.get('pond_xf') and mat in ('M_Sea', 'M_Lake'):
                    import ponds
                    tp_ = ponds._tp(t)
                    if tp_.area < ponds.BIG and any(tp_.intersects(h_.buffer(5)) for h_, _ in g['pond_xf']): continue
                if mat in ('M_Fairway', 'M_Green', 'M_Color') and not (kg_ and kg_.contains(_Pt(cx, cz))): out['M_Rough'].append((t, False))   # ancien trace -> rough
                elif mat in ('M_Kiwa_F', 'M_Kiwa_R') and not (kg_ and kg_.contains(_Pt(cx, cz))): continue   # bords de l'ancien fairway
                elif mat in ('M_Kiwa_Black', 'M_Kiwa_OB') and conv.contains(_Pt(cx, cz)): continue
                else: out[mat].append((t, True))
            continue
        tgt = 'M_Rough' if mat in TO_ROUGH else mat
        if tgt not in regen: continue
        for t in tl:
            cx = sum(v['pos'][0] for v in t) / 3; cz = sum(v['pos'][2] for v in t) / 3
            if mat == 'M_Iwa' and g.get('iwa_cliff'):
                # falaises du rivage : gardees ; bassins rocheux a l'interieur (ancien lac de Nintendo) : retires
                if not core.contains(_Pt(cx, cz)): out[tgt].append((t, True))
            elif not inside.contains(_Pt(cx, cz)): out[tgt].append((t, tgt == mat))
    return out


_VT = {}
def _value_tris_cached(src):
    k = (id(src), len(src))
    if k not in _VT: _VT[k] = (src, value_tris(src))
    return _VT[k][1]


def _culls(src):
    """mode de rejet par materiau (2 = faces arriere, Nintendo ; 1 = faces avant, modele en miroir)"""
    from brres import _dict
    t = brres_tree(src); mo = t['3DModels(NW4R)'][0][1]
    secs = struct.unpack('>14i', src[mo + 16:mo + 16 + 56])
    return {n: struct.unpack('>I', src[o + 0x18:o + 0x1C])[0] for n, o in _dict(src, mo + secs[8])}


def build_model(src, g, fits_src, old_green, kind='course'):
    vt, m = _value_tris_cached(src)
    o2m = _obj2mat(m)
    CULL = _culls(src)
    arrmeta = {}
    for k in ('uv',):
        for n, v, mt in m['arr'][k]: arrmeta[mt['idx']] = mt
    V, N = g['V'], g['N']
    wmat = g.get('water_mat') or 'M_Sea'
    bmat = g.get('bank_mat', 'M_Iwa')
    regen = (REGEN - {'M_Sea'}) | ({g['water_mat']} if g.get('water_mat') else set())
    regen = regen | {'M_Iwa'}                                          # fond et berges des lacs : roche
    if g.get('nmode'): regen = regen | {'M_Kiwa_R', 'M_Kiwa_F', 'M_Kiwa_Black', 'M_Kiwa_OB', 'M_Kiwa_Bunker'}
    if g.get('pond_xf'): regen = regen | {'M_XNamiuchi'}
    by_mat = collections.defaultdict(list)
    for f, lab in g['tris']:
        by_mat[wmat if lab == 'water' else bmat if lab in ('bank', 'bed', 'seabed', 'shore') else MAT[lab]].append(f)
    hdir = np.array([g['green'][0] - g['tee'][0], g['green'][1] - g['tee'][1]]); hdir /= np.linalg.norm(hdir)
    perp = np.array([-hdir[1], hdir[0]])
    dgx, dgz = g['green'][0] - old_green[0], g['green'][1] - old_green[2]
    targets, hide, warn = {}, set(), []
    spec = special_strips(g) if kind == 'course' else {}
    pond = g.get('pond')
    outside = _outside_ground(vt, o2m, g, regen)
    xf = {}
    if g.get('pond_xf'):                                   # etangs de Nintendo deplaces (v23)
        import ponds
        for k_, tl_ in ponds.transplant(vt, o2m, g).items():
            if k_.startswith('_water_'):
                mt_ = k_[7:]; xf.setdefault(mt_, []).extend(t if CULL.get(mt_) == 1 else [t[0], t[2], t[1]] for t in tl_)
            else: xf.setdefault(k_, []).extend(tl_)
    for p in m['polys']:
        mat = o2m.get(p['name'])
        if mat in HIDE and mat not in regen: hide.add(p['name']); continue
        if mat == 'M_XNamiuchi' and (g.get('water_mat') != 'M_Sea' or g.get('ocean_keep')) and not g.get('pond_xf'): continue   # ecume du rivage : on garde
        if mat in ('M_Kiwa_OB', 'M_Kiwa_Bunker', 'M_XNamiuchi'):
            st = spec.get(mat, [])
            if g.get('nmode') and mat == 'M_Kiwa_OB': st = []           # le bord du rough reste celui de Nintendo
            if g.get('nmode') and not st and outside.get(mat): st = None
            if st is None: st = []
            elif not st and not xf.get(mat): hide.add(p['name']); continue
            slots = [a for a, _ in p['attrs']]; fit = fits_src.get(mat, {}); col = fit.get('clr', (190, 190, 190, 255))
            tris = []
            for tv in st:
                tt = []
                for vi in ((0, 1, 2) if CULL.get(mat) == 1 else (0, 2, 1)):   # sens GPU de Nintendo (inverse en miroir)
                    q = tv[vi]
                    e = {'pos': q['pos'], 'nrm': (0.0, 1.0, 0.0)}
                    if 'clr0' in slots: e['clr0'] = tuple(col[:3]) + (q['a'],)
                    if 'uv0' in slots: e['uv0'] = (q['u'], q['v'])
                    if 'uv1' in slots: e['uv1'] = (q['u'], q['v'])
                    tt.append(e)
                tris.append(tt)
            for k_, ch in enumerate(('uv0', 'uv1')):
                if ch not in slots: continue
                mt = arrmeta[p['ids'][4 + k_]]
                if not _uv_ok(mt, [v[ch] for t in tris for v in t]):
                    for t in tris:
                        mu = math.floor(min(v[ch][0] for v in t))
                        for v in t: v[ch] = (v[ch][0] - mu, v[ch][1])
                    if not _uv_ok(mt, [v[ch] for t in tris for v in t]): warn.append('%s %s hors plage' % (mat, ch))
            if g.get('nmode'): tris += [[dict(q) for q in tv0] for tv0, _ in outside.get(mat, [])]
            tris += [[dict(q) for q in t] for t in xf.get(mat, [])]
            targets[p['name']] = tris
            continue
        if mat not in regen: continue
        fl = by_mat.get(mat, [])
        slots = [a for a, _ in p['attrs']]
        fit = fits_src.get(mat, {})
        col = fit.get('clr', (190, 190, 190, 255))
        tris = []
        for f in fl:
            tv = []
            fn_ = np.cross(V[f[1]] - V[f[0]], V[f[2]] - V[f[0]]); fn_ = fn_ / (np.linalg.norm(fn_) + 1e-9)
            for vi in ((f[0], f[1], f[2]) if CULL.get(mat) == 1 else (f[0], f[2], f[1])):   # sens GPU de Nintendo (inverse en miroir)
                x, y, z = V[vi]
                e = {'pos': (float(x), float(y), float(z)), 'nrm': tuple(float(c) for c in N[vi])}
                if 'clr0' in slots:
                    shade = 0.92 + 0.08 * float(N[vi][1])
                    if mat == bmat and g.get('wl') is not None and y < g['wl'] - 5:            # fond de lac : gris sombre comme Nintendo (~70 au fond)
                        gv = int(130 - 62 * min(1.0, max(0.0, (g['wl'] - y - 12.0) / 30.0)))
                        e['clr0'] = (gv, gv, gv, 255)
                    elif mat == bmat and g.get('ocean_y') is not None and y < g['ocean_y']:     # fond du bras de mer
                        shade *= 0.55
                    if 'clr0' not in e and g.get('ncolor') is not None:
                        nc = g['ncolor'](float(x), float(z))
                        if nc is not None and nc[0] == mat: e['clr0'] = nc[1]
                    if 'clr0' not in e: e['clr0'] = tuple(int(min(255, c * shade)) for c in col[:3]) + (col[3],)
                for ch in ('uv0', 'uv1'):
                    if ch not in slots: continue
                    if mat == bmat and pond is not None and not pond.is_empty and g.get('wl') is not None and y < g['wl'] - 5:
                        # fond du lac : roche plaquee a plat (1 motif / 50 u), pas l'etirement radial de la berge
                        pc = pond.centroid; e[ch] = ((x - pc.x) / 50.0, (z - pc.y) / 50.0)
                    elif mat == bmat and bmat != 'M_Rough' and pond is not None and not pond.is_empty:
                        from shapely.geometry import Point as _Pt
                        ring_ = pond.exterior; per_ = max(1, round(ring_.length * 0.02))
                        e[ch] = (per_ * ring_.project(_Pt(x, z)) / ring_.length, 1.0 - (1.0 if bmat == 'M_Kiwa_R' else 0.68) * min(1.0, pond.distance(_Pt(x, z)) / 26.0))
                    elif mat == bmat and mat == 'M_Iwa':
                        # roche : texture plaquee dans le plan de la paroi (pas d'etirement vertical)
                        if abs(fn_[1]) > 0.8: e[ch] = (x / 80.0, z / 80.0)
                        elif abs(fn_[0]) > abs(fn_[2]): e[ch] = (z / 80.0, -y / 80.0)
                        else: e[ch] = (x / 80.0, -y / 80.0)
                    elif mat == 'M_Fairway' and ch == 'uv1':
                        rel = np.array([x - g['tee'][0], z - g['tee'][1]])
                        e[ch] = (0.00845 * float(rel @ perp), 0.0225 * float(rel @ hdir))
                    elif mat == 'M_Green' and ch == 'uv1' and ch in fit:
                        c = fit[ch]; e[ch] = tuple(float(v) for v in np.array([x - dgx, z - dgz, 1.0]) @ c)
                    elif ch in fit:
                        c = fit[ch]; e[ch] = tuple(float(v) for v in np.array([x, z, 1.0]) @ c)
                    else:
                        e[ch] = (0.0, 0.0)
                tv.append(e)
            tris.append(tv)
        if not tris:                                       # materiau absent : triangle cache
            tris = [[{s: ((0.0, -9000.0, 0.0) if s == 'pos' else (0.0, 1.0, 0.0) if s == 'nrm' else
                          (0, 0, 0, 0) if s.startswith('clr') else (0.0, 0.0)) for s in slots} for _ in range(3)]]
        if mat == bmat and bmat != 'M_Rough' and pond is not None and not pond.is_empty and not g.get('pond_xf'):
            per_ = max(1, round(pond.exterior.length * 0.02))
            for t in tris:
                for ch in ('uv0', 'uv1'):
                    if ch not in t[0]: continue
                    us = [v[ch][0] for v in t]
                    if max(us) - min(us) > per_ / 2:
                        for v in t:
                            if v[ch][0] < per_ / 2: v[ch] = (v[ch][0] + per_, v[ch][1])
        if mat == 'M_Sea' and g.get('ocean_keep'):          # lac en M_Sea : le plan d'ocean de Nintendo reste
            tris = [t for t in tris if t[0]['pos'][1] > -8000] + [[dict(q) for q in t] for t in vt[p['name']]]
        for tv0, same in outside.get(mat, []):             # terre de Nintendo hors de l'ile regeneree (ilots)
            tv = []
            for q in tv0:
                x, y, z = q['pos']; e = {'pos': q['pos'], 'nrm': q.get('nrm', (0.0, 1.0, 0.0))}
                if 'clr0' in slots:
                    e['clr0'] = q['clr0'] if same and 'clr0' in q else tuple(int(min(255, c * (0.92 + 0.08 * e['nrm'][1]))) for c in col[:3]) + (col[3],)
                for ch in ('uv0', 'uv1'):
                    if ch not in slots: continue
                    if same and ch in q: e[ch] = q[ch]
                    elif ch in fit: e[ch] = tuple(float(v) for v in np.array([x, z, 1.0]) @ fit[ch])
                    else: e[ch] = (0.0, 0.0)
                tv.append(e)
            tris.append(tv)
        tris += [[dict(q) for q in t] for t in xf.get(mat, [])]
        # verifier que les UV tiennent dans le format du tableau ; sinon decaler d'un entier
        for k_, ch in enumerate(('uv0', 'uv1')):
            if ch not in slots: continue
            mt = arrmeta[p['ids'][4 + k_]]
            vals = [v[ch] for t in tris for v in t]
            if not _uv_ok(mt, vals):
                # decalage entier par composante connexe (chaque bunker a son propre repere)
                par_ = list(range(len(tris)))
                def fd(i):
                    while par_[i] != i: par_[i] = par_[par_[i]]; i = par_[i]
                    return i
                owner = {}
                for ti, t in enumerate(tris):
                    for v in t:
                        k = (round(v['pos'][0], 2), round(v['pos'][2], 2))
                        if k in owner: par_[fd(ti)] = fd(owner[k])
                        else: owner[k] = ti
                comp = collections.defaultdict(list)
                for ti in range(len(tris)): comp[fd(ti)].append(ti)
                for lst in comp.values():
                    vv = [v[ch] for ti in lst for v in tris[ti]]
                    mu = [round(float(np.mean([x[i] for x in vv]))) for i in range(2)]
                    seen = set()
                    for ti in lst:
                        for v in tris[ti]:
                            if id(v) in seen: continue
                            seen.add(id(v)); v[ch] = (v[ch][0] - mu[0], v[ch][1] - mu[1])
                if not _uv_ok(mt, [v[ch] for t in tris for v in t]) and mt['fmt'] in (0, 2):
                    # format non signe (motif 0..1 du green) : on recadre dans [0.03, 0.97]
                    seen = {}
                    for t in tris:
                        for v in t: seen[id(v)] = v
                    allv = list(seen.values())
                    for i in range(2):
                        lo = min(v[ch][i] for v in allv); hi = max(v[ch][i] for v in allv); sp_ = max(hi - lo, 1e-6)
                        for v in allv:
                            uv = list(v[ch]); uv[i] = 0.03 + 0.94 * (uv[i] - lo) / sp_; v[ch] = tuple(uv)
                if not _uv_ok(mt, [v[ch] for t in tris for v in t]):
                    # motif repetitif (rayures du fairway) : decalage entier par triangle
                    nt = []
                    for t in tris:
                        mu = [math.floor(min(v[ch][i] for v in t)) for i in range(2)]
                        nt.append([dict(v, **{ch: (v[ch][0] - mu[0], v[ch][1] - mu[1])}) for v in t])
                    tris = nt
                if not _uv_ok(mt, [v[ch] for t in tris for v in t]): warn.append('%s %s hors plage' % (mat, ch))
        targets[p['name']] = tris
    out = replace_geometry(src, targets)
    out = sink_polygons(out, hide)
    return out, warn


OB_PLANE = (0x0805, 0x080d)          # attribut & 0x1f = 5 ou 13 : le jeu declare hors limite
                                    # toute colonne verticale qui touche un de ces triangles


def ob_plane(tpl, g):
    """Plan hors-limite invisible (sous le niveau de la mer) : tout le terrain sauf la zone jouable.
    Nintendo y laisse un trou de la forme de son parcours ; on le refait a la forme du notre."""
    import triangle as tr
    from shapely.geometry import box as _box, Polygon as _P
    from shapely.ops import unary_union as _uu
    old = [p for p in tpl.kcl['prisms'] if p[6] in OB_PLANE]
    ys = [tri_vertices(tpl.kcl, p)[0][1] for p in old] or [-1000.0]
    y = float(np.median(ys)); attr = old[0][6] if old else 0x0805
    R = g['regions']
    zone = _uu([R[k] for k in ('rough', 'fairway', 'green', 'collar', 'bunker', 'water', 'bank', 'sea', 'shore') if k in R and not R[k].is_empty])
    zone = zone.buffer(8).buffer(-3)
    if zone.geom_type != 'Polygon': zone = max(zone.geoms, key=lambda q: q.area)
    zone = _P(zone.exterior).simplify(6)
    x0, z0, x1, z1 = tpl.island.bounds
    if old:
        V_ = np.array([v for p in old for v in tri_vertices(tpl.kcl, p)])
        x0, z0, x1, z1 = min(x0, V_[:, 0].min()), min(z0, V_[:, 2].min()), max(x1, V_[:, 0].max()), max(z1, V_[:, 2].max())
    outer = _box(x0 - 200, z0 - 200, x1 + 200, z1 + 200)
    ext = list(outer.exterior.coords)[:-1]; hol = list(zone.exterior.coords)[:-1]
    verts = ext + hol
    segs = [(i, (i + 1) % len(ext)) for i in range(len(ext))]
    segs += [(len(ext) + i, len(ext) + (i + 1) % len(hol)) for i in range(len(hol))]
    hp = zone.representative_point()
    T = tr.triangulate({'vertices': np.array(verts), 'segments': np.array(segs), 'holes': np.array([[hp.x, hp.y]])}, 'p')
    out = []
    for f in T['triangles']:
        A, B, C = (tuple(map(float, (T['vertices'][i][0], y, T['vertices'][i][1]))) for i in f)
        if np.cross(np.subtract(B, A), np.subtract(C, A))[1] < 0: B, C = C, B
        out.append((A, B, C, attr))
    return out


def build_kcl(tpl, g):
    tris = []
    V = g['V']
    for f, lab in g['tris']:
        A, B, C = (tuple(float(c) for c in V[i]) for i in f)
        tris.append((A, B, C, ATTR[lab]))
    from shapely.geometry import Point as _Pt
    from shapely.prepared import prep as _prep
    nm = g.get('nmode')
    isl = _prep(tpl.island.buffer(-5))
    if nm:
        Ein = _prep(g['island'].buffer(0.5))
        kgp = _prep(g['keep_green_poly'].buffer(2)) if g.get('keep_green_poly') is not None else None
        import ponds
        drop_old, xf_new = ponds.transplant_kcl(tpl.kcl, g, tri_vertices)
    for p in tpl.kcl['prisms']:                          # decor de Nintendo hors de l'ile regeneree
        if nm:                                           # mode Nintendo : on ne retire que ce qui est entierement dans la zone
            A, B, C = tri_vertices(tpl.kcl, p)
            from shapely.geometry import Polygon as _Pg
            tp_ = _Pg([(v[0], v[2]) for v in (A, B, C)])
            if drop_old(p, tp_): continue
            if not (p[6] not in OB_PLANE and (tp_.area < 1e-6 or Ein.contains(tp_))):
                at = p[6]
                if at & 0x1f in (0x01, 0x06, 0x09) and not (kgp and kgp.contains(tp_.centroid)):
                    at = (at & ~0x1f) | 0x02                     # ancien fairway / green hors zone : rough (comme le dessin)
                tris.append((A, B, C, at))
            continue
        if p[6] in OB_PLANE: continue
        A, B, C = tri_vertices(tpl.kcl, p)
        cx, cz = (A[0] + B[0] + C[0]) / 3, (A[2] + B[2] + C[2]) / 3
        if not isl.contains(_Pt(cx, cz)):
            at = p[6]
            if at & 0x1f in (0x01, 0x06, 0x03, 0x09): at = (at & ~0x1f) | 0x02     # ancien fairway/green/bunker -> rough
            tris.append((A, B, C, at))
    tris += [(A, B, C, 0x0107) for A, B, C in g.get('sea_kcl', [])]       # eau du bras de mer
    if nm: tris += xf_new
    if not nm: tris += ob_plane(tpl, g)                  # mode Nintendo : plan hors limite d'origine garde
    return write_kcl(tris)


def _rot(dx, dz):
    n = math.hypot(dx, dz); dx, dz = dx / n, dz / n
    return (dx, 0.0, dz, 0.0, 1.0, 0.0, dz, 0.0, -dx)


def build_pmp(tpl, g, rng, avoid=None):
    import random
    from shapely.geometry import Point as _Pt
    isl_ = g['island'] if g.get('nmode') else tpl.island.buffer(-5)
    # objets decoratifs de Nintendo (palmiers 6/7...) : gardes seulement hors du terrain regenere
    def _decor_ok(o):
        if o['grp'] == 2 and o['typ'] in (6, 7): return not isl_.contains(_Pt(o['pos'][0], o['pos'][2]))
        return True
    keep = [o for o in tpl.pmp if not (o['grp'] == 2 and o['typ'] in (0, 1, 2, 3, 4, 5, 10)) and not o['grp'] == 11 and _decor_ok(o)]
    orig = {(o['grp'], o['typ']): o for o in tpl.pmp}
    V = g['V']
    # hauteur du terrain genere en (x, z) : triangles pre-calcules en tableaux numpy (meme resultat, bien plus rapide)
    _F = np.array([f for f, lab in g['tris'] if lab != 'bed']); _L = [lab for f, lab in g['tris'] if lab != 'bed']
    _A = V[_F[:, 0]]; _B = V[_F[:, 1]]; _C = V[_F[:, 2]]
    _v0 = _C[:, [0, 2]] - _A[:, [0, 2]]; _v1 = _B[:, [0, 2]] - _A[:, [0, 2]]
    _den = _v0[:, 0] * _v1[:, 1] - _v1[:, 0] * _v0[:, 1]; _ok = np.abs(_den) >= 1e-9
    _den = np.where(_ok, _den, 1.0)
    def h_at(x, z):
        v2x = x - _A[:, 0]; v2z = z - _A[:, 2]
        u = (v2x * _v1[:, 1] - _v1[:, 0] * v2z) / _den; w = (_v0[:, 0] * v2z - v2x * _v0[:, 1]) / _den
        hit = np.nonzero(_ok & (u >= -1e-6) & (w >= -1e-6) & (u + w <= 1 + 1e-6))[0]
        if len(hit):
            i = hit[0]
            return float(_A[i, 1] + u[i] * (_C[i, 1] - _A[i, 1]) + w[i] * (_B[i, 1] - _A[i, 1])), _L[i]
        return float(g['tee_h']), None
    aim = g['aim']
    # groupe depart et groupe drapeaux : copies rigides de ceux de Nintendo
    # (memes ecarts relatifs et memes orientations, juste tournes / deplaces)
    t0 = orig[(2, 0)]; T0 = np.array(t0['pos'])
    a0 = math.atan2(t0['rot'][2], t0['rot'][0]); a1 = math.atan2(aim[1], aim[0]); th_ = a1 - a0
    c_, s_ = math.cos(th_), math.sin(th_)
    def rotxz(vx, vz): return (c_ * vx - s_ * vz, s_ * vx + c_ * vz)
    tx, tz = g['tee']; th, _ = h_at(tx, tz)
    moved = {}
    for o0 in tpl.pmp:
        k = (o0['grp'], o0['typ'])
        if k in ((2, 0), (2, 10), (11, 0)):
            o = dict(o0); dx, dz = rotxz(o0['pos'][0] - T0[0], o0['pos'][2] - T0[2])
            o['pos'] = (tx + dx, th + (o0['pos'][1] - T0[1]), tz + dz)
            r = list(o0['rot']); nr = []
            for i in range(3):
                x_, z_ = rotxz(r[3 * i], r[3 * i + 2]); nr += [x_, r[3 * i + 1], z_]
            o['rot'] = tuple(nr); moved[o0['i']] = o
    G0 = [o for o in tpl.pmp if (o['grp'], o['typ']) == (11, 1)][0]['pos']
    gx, gz = g['green']
    # (11, 1) : trou principal ; (2, 1) : emplacements de drapeau alternatifs, le jeu en tire un a chaque partie.
    # Seul le trou principal a un terrain prepare (maillage fin, replat sur la Wii) : tous au meme endroit.
    # (11, 1) au centre du green ; chaque (2, 1) sur son propre emplacement prepare (le jeu en tire un et
    # bouche les autres : jamais deux au meme endroit)
    pins = g.get('pins') or [(gx, gz)]; k21 = 0
    for o0 in ([] if g.get('keep_pins') else tpl.pmp):            # green de Nintendo garde : drapeaux d'origine
        if (o0['grp'], o0['typ']) == (11, 1):
            o = dict(o0); o['pos'] = (gx, h_at(gx, gz)[0], gz); moved[o0['i']] = o
        elif (o0['grp'], o0['typ']) == (2, 1):
            k21 += 1; px, pz = pins[k21 % len(pins)] if len(pins) > 1 else pins[0]
            o = dict(o0); o['pos'] = (px, h_at(px, pz)[0], pz); moved[o0['i']] = o
    objs = []
    # arbres : bosquets dans la zone arboree, jamais dans le couloir de jeu
    ob = g['regions']['ob']; rough = g['regions']['rough']
    from shapely.geometry import Point
    from shapely.prepared import prep
    obp = prep(ob.buffer(-60))
    play = g['regions']['fairway'].union(g['regions']['green']).union(g['regions']['bunker']).union(g['regions']['rough']).buffer(120)
    if avoid is not None and not avoid.is_empty: play = play.union(avoid)
    target = 0 if g.get('nmode') or ob.is_empty else rng.randint(45, 85)
    trees, tries = [], 0
    x0, z0, x1, z1 = ob.bounds
    while len(trees) < target and tries < 6000:
        tries += 1
        cx, cz = rng.uniform(x0, x1), rng.uniform(z0, z1)
        if not obp.contains(Point(cx, cz)) or play.contains(Point(cx, cz)): continue
        for _ in range(rng.randint(1, 5)):                 # bosquet
            x, z = cx + rng.gauss(0, 110), cz + rng.gauss(0, 110)
            if not obp.contains(Point(x, z)) or play.contains(Point(x, z)): continue
            if any(math.dist((x, z), t[:2]) < 120 for t in trees): continue
            if h_at(x, z)[1] is None: continue
            trees.append((x, z, rng.choice((2, 3))))
            if len(trees) >= target: break
    # arbres en jeu : bosquets dans le rough au bord du fairway et a l'interieur des virages
    R = g['regions']
    fair = R['fairway']
    near_ok = prep(R['rough'].buffer(-25))
    keep_out = R['green'].union(R['collar']).buffer(90).union(R['bunker'].buffer(40))
    if not R['water'].is_empty: keep_out = keep_out.union(R['water'].buffer(60))
    if g.get('pond_xf') and not g['pond'].is_empty: keep_out = keep_out.union(g['pond'].buffer(50))
    tx_, tz_ = g['tee']; keep_out = keep_out.union(Point(tx_, tz_).buffer(220))
    if avoid is not None and not avoid.is_empty: keep_out = keep_out.union(avoid)
    ko = prep(keep_out)
    n_in = {3: (4, 8), 4: (10, 18), 5: (14, 24)}.get(g.get('par', 4), (10, 18))
    want = rng.randint(*n_in); tries = 0; placed = 0
    rx0, rz0, rx1, rz1 = R['rough'].bounds
    while placed < want and tries < 5000:
        tries += 1
        x, z = rng.uniform(rx0, rx1), rng.uniform(rz0, rz1); q = Point(x, z)
        if not near_ok.contains(q) or ko.contains(q): continue
        df = fair.distance(q) if not fair.is_empty else 999
        if not (25 < df < 230): continue
        if any(math.dist((x, z), t[:2]) < 75 for t in trees): continue
        if h_at(x, z)[1] is None: continue
        trees.append((x, z, rng.choice((2, 3)))); placed += 1
    # rangee d'arbres en travers du fairway (v23) : marquee (echelle 2,75 exacte) pour que la Wii ne la deplace pas
    row = [(x, z, 2, 'row') for x, z in g.get('tree_row') or [] if h_at(x, z)[1] is not None]
    if row: trees = row + [t for t in trees if all(math.dist(t[:2], r[:2]) > 70 for r in row)]
    if g.get('nmode'):          # plus d'arbres (le jeu les replace ensuite sur la Wii) : bosquets dans la zone
        n_keep = sum(1 for o_ in tpl.pmp if (o_['grp'], o_['typ']) in ((2, 2), (2, 3))
                     and not isl_.buffer(30).contains(_Pt(o_['pos'][0], o_['pos'][2])))
        # le jeu a des tableaux de taille fixe : jamais plus d'objets que Nintendo (max 132, 108 arbres)
        n_other = sum(1 for o_ in tpl.pmp if not (o_['grp'] == 2 and o_['typ'] in (2, 3, 4, 5)))
        cap = min(95, 122 - n_other - sum(1 for o_ in tpl.pmp if (o_['grp'], o_['typ']) in ((2, 4), (2, 5))))
        if len(trees) + n_keep > cap: trees = trees[:max(0, cap - n_keep)]
        want2 = max(0, cap - n_keep - len(trees)); tries = 0
        zx0, zz0, zx1, zz1 = R['rough'].bounds; far_ok = prep(R['rough'].buffer(-30))
        ko2 = prep(keep_out.union(fair.buffer(60)) if not fair.is_empty else keep_out)
        while want2 > 0 and tries < 8000:
            tries += 1
            cx, cz = rng.uniform(zx0, zx1), rng.uniform(zz0, zz1)
            if not far_ok.contains(Point(cx, cz)) or ko2.contains(Point(cx, cz)): continue
            for _ in range(rng.randint(2, 6)):
                x, z = cx + rng.gauss(0, 90), cz + rng.gauss(0, 90)
                if not far_ok.contains(Point(x, z)) or ko2.contains(Point(x, z)): continue
                if any(math.dist((x, z), t[:2]) < 60 for t in trees): continue
                if h_at(x, z)[1] is None: continue
                trees.append((x, z, rng.choice((2, 3)))); want2 -= 1
                if want2 <= 0: break
    tree_objs = []
    for x, z, typ, *_ in sorted(trees, key=lambda t: t[2]):
        o = dict(orig.get((2, typ), orig[(2, 2)])); sc = rng.uniform(2.0, 2.9) if typ == 2 else rng.uniform(2.4, 3.2)
        if (x, z, typ, 'row') in row: sc = 2.75
        a = rng.uniform(0, 6.28)
        o['pos'] = (x, h_at(x, z)[0], z); o['scl'] = (sc * 0.92, sc, sc * 0.92)
        o['rot'] = (math.cos(a), 0.0, -math.sin(a), 0.0, 1.0, 0.0, math.sin(a), 0.0, math.cos(a))
        tree_objs.append(o)
    # palmiers (types 6 + 7 associe, sous le sol) pres du rivage, si le trou de Nintendo en a
    palms6, palms7 = [], []
    o6 = orig.get((2, 6)); o7 = orig.get((2, 7))
    if o6 is not None:
        coast = tpl.island.exterior
        n_p, tries = rng.randint(14, 26), 0
        pl = []
        while len(pl) < n_p and tries < 4000:
            tries += 1
            x, z = rng.uniform(x0, x1), rng.uniform(z0, z1)
            q = Point(x, z)
            dc = coast.distance(q)
            if not (90 < dc < 420) or not obp.contains(q) or play.contains(q): continue
            if any(math.dist((x, z), t) < 140 for t in pl) or any(math.dist((x, z), t[:2]) < 110 for t in trees): continue
            hy, lab = h_at(x, z)
            if lab is None: continue
            pl.append((x, z))
            sc = rng.uniform(1.4, 2.2); a = rng.uniform(0, 6.28)
            rot = (math.cos(a), 0.0, -math.sin(a), 0.0, 1.0, 0.0, math.sin(a), 0.0, math.cos(a))
            p6 = dict(o6); p6.update(pos=(x, hy, z), scl=(sc, sc, sc), rot=rot); palms6.append(p6)
            if o7 is not None:
                p7 = dict(o7); p7.update(pos=(x, hy - 100 * sc / 1.6, z), scl=(sc, sc, sc), rot=rot); palms7.append(p7)
    # meme ordre que le fichier de Nintendo : 23, arbres 2 puis 3, 8, (4/5 retires), 22, 24, 10, 25, 0, 1x3, 11/0, 11/1
    out = []
    for o0 in tpl.pmp:
        k = (o0['grp'], o0['typ'])
        if k in ((2, 2), (2, 3)):
            if tree_objs: out += tree_objs; tree_objs = []
            if g.get('nmode') and not isl_.buffer(30).contains(_Pt(o0['pos'][0], o0['pos'][2])): out.append(o0)
            continue
        if g.get('nmode') and k in ((2, 4), (2, 5)):    # mode Nintendo : arbres d'origine hors zone gardes
            if not isl_.buffer(30).contains(_Pt(o0['pos'][0], o0['pos'][2])): out.append(o0)
            continue
        if k in ((2, 4), (2, 5)): continue
        if k == (2, 6) and palms6: out += palms6; palms6 = []
        if k == (2, 7) and palms7: out += palms7; palms7 = []
        if not _decor_ok(o0): continue
        out.append(moved.get(o0['i'], o0))
    g['trees_xz'] = [(t[0], t[1]) for t in trees]
    return write_pmp(tpl.pmp_raw, out), len(trees)


CAM_ERR = {}
CAM_SEGS = []
TAN_P = math.tan(math.radians(11))


def build_cameras(tpl, g, brres):
    """Cameras de presentation recreees sur le nouveau trace (on garde seulement la duree
    et le budget de cles de Nintendo) :
      glf_cam   : survol du depart vers le green, regard vers l'avant puis sur le drapeau
      camL1     : travelling lent derriere le depart, regard vers le fairway
      camL2     : vue depuis derriere le green, regard vers le green
    Trajectoires lissees, toujours au-dessus du parcours, hauteur constante au-dessus du relief."""
    import scn0cam
    from scipy.ndimage import gaussian_filter1d
    from shapely.geometry import LineString as _LS
    from shapely.ops import unary_union
    CAM_SEGS.clear()
    global ISL_SAFE, _PtC
    from shapely.geometry import Point as _PtC
    from shapely.prepared import prep as _prepC
    ISL_SAFE = _prepC(tpl.island.buffer(-150))
    h = _ground(g)
    P = np.array(g['path'], float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1); cum = np.r_[0, np.cumsum(seg)]; Lt = cum[-1]
    gx, gz = g['green']; gy = float(g['gh'])
    def at(d):                                   # point du trace a la distance d (prolonge aux bouts)
        if d <= 0: t = P[1] - P[0]; t /= np.linalg.norm(t); return P[0] + t * d, t
        if d >= Lt: t = P[-1] - P[-2]; t /= np.linalg.norm(t); return P[-1] + t * (d - Lt), t
        i = max(0, min(np.searchsorted(cum, d) - 1, len(P) - 2)); f = (d - cum[i]) / max(seg[i], 1e-9)
        t = (P[i + 1] - P[i]) / max(seg[i], 1e-9); return P[i] + (P[i + 1] - P[i]) * f, t
    # hauteur de vol : max du relief sur +-150 le long du trace, lissee
    ds = np.arange(-0.15 * Lt, 1.1 * Lt, 20.0)
    hg = np.array([h(*at(d)[0]) for d in ds])
    win = int(150 / 20)
    hmax = np.array([hg[max(0, i - win): i + win + 1].max() for i in range(len(hg))])
    hfly = gaussian_filter1d(hmax, 8)
    def fly(d, clear): return float(np.interp(d, ds, hfly)) + clear
    def smooth(t): t = min(1.0, max(0.0, t)); return t * t * (3 - 2 * t)

    b = bytearray(brres)
    t = brres_tree(bytes(b))
    for name, o, _ in t.get('AnmScn(NW4R)', []):
        if '_cam' not in name: continue
        size = struct.unpack('>I', bytes(b[o + 4:o + 8]))[0]
        blk = bytes(b[o:o + size])
        nfr, tr, where = scn0cam.read_cam(blk)
        frames = list(range(0, nfr, max(1, nfr // 90))) + [nfr - 1]
        newv = {k: [] for k in scn0cam.ANIM}
        for f in frames:
            u = f / max(1, nfr - 1)
            if name.startswith('glf_cam_'):
                k = smooth(u / 0.92)                                  # tenue sur la fin
                d_end = Lt - max(430.0, 0.17 * Lt)
                d = -0.07 * Lt + k * (d_end + 0.07 * Lt)
                c, tg = at(d)
                pos = (c[0], fly(d, 105), c[1])
                look = min(d + max(400.0, 0.16 * Lt), Lt)
                la, _ = at(look)
                aim = np.array([la[0], pos[1] - TAN_P * np.hypot(la[0] - c[0], la[1] - c[1]), la[1]])
                w = smooth((u - 0.5) / 0.4)                           # puis regard sur le drapeau
                aim = aim * (1 - w) + np.array([gx, gy + 8, gz]) * w
            elif 'camL1' in name:
                d = -0.06 * Lt + u * 0.28 * Lt
                c, tg = at(d)
                pos = (c[0], fly(d, 95), c[1])
                la, _ = at(d + max(300.0, 0.2 * Lt))
                aim = np.array([la[0], pos[1] - TAN_P * np.hypot(la[0] - c[0], la[1] - c[1]), la[1]])
            else:                                                     # camL2 : derriere le green
                back = max(260.0, 0.09 * Lt)
                while back > 60 and not ISL_SAFE.contains(_PtC(*at(Lt + back)[0])): back -= 20
                d = Lt + back
                c, tg = at(d)
                nv = np.array([-tg[1], tg[0]])
                c = c + nv * (u - 0.5) * 0.12 * Lt                    # lent travelling lateral
                pos = (c[0], max(fly(Lt, 60), h(*c) + 70), c[1])
                aim = np.array([gx, gy + 5, gz])
            for i_, ax in enumerate('XYZ'):
                newv['pos' + ax].append(float(pos[i_])); newv['aim' + ax].append(float(aim[i_]))
        # lissage (virages serres) : le regard tourne en douceur
        for k_, sg in (('aimX', 5), ('aimZ', 5), ('aimY', 4), ('posX', 2), ('posZ', 2), ('posY', 3)):
            v_ = np.array(newv[k_]); newv[k_] = list(gaussian_filter1d(v_, sg, mode='nearest'))
        total = sum(where[k][2] for k in tr)
        share = {'posX': 3, 'posZ': 3, 'aimX': 3, 'aimZ': 3, 'posY': 2, 'aimY': 2}
        an = [k for k in share if where[k][1] is not None]
        wsum = sum(share[k] for k in an)
        cnt = {k: (max(2, int(total * share[k] / wsum)) if k in an else 1) for k in share}
        while sum(cnt[k] for k in an) > total: cnt[max(an, key=lambda k: cnt[k])] -= 1
        new_tracks = {k: (scn0cam.fit_keys(frames, newv[k], cnt[k]) if where[k][1] is not None
                          else [(0.0, float(np.mean(newv[k])), 0.0)]) for k in scn0cam.ANIM}
        b[o:o + size] = scn0cam.write_cam(blk, new_tracks)
        errs = [max(abs(scn0cam.hermite(new_tracks[k], f) - v) for f, v in zip(frames, newv[k])) for k in an]
        CAM_ERR[name] = round(float(max(errs)), 1) if errs else 0
        CAM_SEGS.append([(scn0cam.hermite(new_tracks['posX'], f), scn0cam.hermite(new_tracks['posZ'], f)) for f in frames])
    avoid = unary_union([_LS(c).buffer(170) for c in CAM_SEGS if len(c) > 1]) if CAM_SEGS else None
    return bytes(b), avoid



def build_map_trees(mp, g, seed=0):
    """Icones d'arbres de la mini-carte (modele glf_tree_*) : un carre par bosquet genere."""
    import random
    from meshio import value_tris as _vt
    t = brres_tree(mp)
    names = [n for n, o, m in t['3DModels(NW4R)']]
    k = next((i for i, n in enumerate(names) if n.startswith('glf_tree')), None)
    if k is None or not g.get('trees_xz'): return mp
    vt, m = _vt(mp, k)
    polys = list(vt.keys())
    y = float(np.mean([v['pos'][1] for tl in vt.values() for tr in tl for v in tr]))
    # regroupement des arbres en bosquets
    # seulement les arbres visibles dans le cadre de la mini-carte (autour du trou)
    from shapely.geometry import Point as _Pm
    from shapely.ops import unary_union as _uum
    R = g['regions']
    near = _uum([R[k] for k in ('rough', 'fairway', 'green') if not R[k].is_empty]).buffer(320)
    tx, tz = g['tee']; gx, gz = g['green']; D_ = math.dist((tx, tz), (gx, gz)); u_ = ((gx - tx) / D_, (gz - tz) / D_)
    def in_frame(p):
        lat = (p[0] - tx) * -u_[1] + (p[1] - tz) * u_[0]; lon = (p[0] - tx) * u_[0] + (p[1] - tz) * u_[1]
        return abs(lat) < 0.32 * D_ + 200 and -250 < lon < D_ + 250
    pts = [p for p in g['trees_xz'] if near.contains(_Pm(p)) and in_frame(p)]; groups = []
    for p in pts:
        for gr in groups:
            if math.dist(p, gr[0]) < 380: gr[1].append(p); break
        else: groups.append([p, [p]])
    rng = random.Random(seed)
    quads = {pn: [] for pn in polys}
    for i, (c, members) in enumerate(groups):
        if len(members) < 2: continue
        cx = float(np.mean([q[0] for q in members])); cz = float(np.mean([q[1] for q in members]))
        hs = min(200.0, 120 + 0.5 * max(math.dist((cx, cz), q) for q in members))
        pn = polys[i % len(polys)]
        col = vt[pn][0][0].get('clr0', (255, 255, 255, 255))
        def V(x, z, u, v): return {'pos': (x, y, z), 'clr0': col, 'uv0': (u, v)}
        a, b, c2, d = V(cx - hs, cz + hs, 0, 1), V(cx - hs, cz - hs, 0, 0), V(cx + hs, cz + hs, 1, 1), V(cx + hs, cz - hs, 1, 0)
        quads[pn] += [[a, b, c2], [c2, b, d]]
    for pn in polys:
        if not quads[pn]:                                   # rien a afficher : un triangle invisible
            quads[pn] = [[{'pos': (0.0, -9000.0, 0.0), 'clr0': (0, 0, 0, 0), 'uv0': (0.0, 0.0)}] * 3]
        else:
            # ne garder que les attributs de l'objet d'origine
            keys = set(vt[pn][0][0].keys())
            quads[pn] = [[{kk: vv for kk, vv in v.items() if kk in keys} for v in tr] for tr in quads[pn]]
    return replace_geometry(mp, quads, model=k)
