"""Verifie une archive produite par le generateur C : collisions (requetes), arbres sur le sol, rendu vue de dessus."""
import sys, os, random, struct, math
sys.path.insert(0, '/home/user/wsr/tools')
import nintendo, kcl, kclwrite, pmp
from kcltri import tri_vertices
from PIL import Image, ImageDraw
COL = {1: (90, 170, 70), 2: (50, 110, 40), 3: (220, 200, 140), 4: (60, 60, 60), 6: (130, 220, 110), 7: (60, 120, 220), 9: (110, 200, 90), 12: (120, 100, 80)}
def files(path):
    d = open(path, 'rb').read(); out = {}
    for e in nintendo.u8_list(d):
        nm = e[0].split('/')[-1]
        if nm.startswith('glf_map'): continue
        out[nm.split('.')[-1]] = d[e[1]:e[1] + e[2]]
    return out
def check(path, png, title=''):
    f = files(path)
    import os
    tk, tp = '/tmp/c_%d.kcl' % os.getpid(), '/tmp/c_%d.pmp' % os.getpid()
    open(tk, 'wb').write(f['kcl']); open(tp, 'wb').write(f['pmp'])
    k = kcl.read_kcl(tk); raw = f['kcl']
    tris = [(tri_vertices(k, p), p[6]) for p in k['prisms']]
    random.seed(3); miss = 0
    for _ in range(int(os.environ.get('KCL_SAMPLES', '400'))):
        i = random.randrange(len(tris)); t = tris[i][0]; w = [random.random() for _ in range(3)]; s = sum(w)
        pt = tuple(sum(w[j] * t[j][c] for j in range(3)) / s for c in range(3))
        q = kclwrite.query(raw, pt)
        if i and k['prisms'][i] == k['prisms'][0]: continue        # case de remplissage (prisme ecarte)
        if q is None or i + 1 not in q: miss += 1
    land = [(t, a) for t, a in tris if (a & 0x1f) in COL and a < 0x800]
    xs = [v[0] for t, a in land for v in t]; zs = [v[2] for t, a in land for v in t]; ys = [v[1] for t, a in land for v in t]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs); S = 700 / max(x1 - x0, z1 - z0)
    W, H = int((x1 - x0) * S) + 1, int((z1 - z0) * S) + 1
    img = Image.new('RGB', (W, H), (0, 0, 40)); dr = ImageDraw.Draw(img)
    y0, y1 = min(ys), max(ys)
    for t, a in sorted(land, key=lambda ta: sum(v[1] for v in ta[0])):
        c = COL[a & 0x1f]; ym = sum(v[1] for v in t) / 3; sh = 0.6 + 0.6 * (ym - y0) / max(1, y1 - y0)
        dr.polygon([((v[0] - x0) * S, (v[2] - z0) * S) for v in t], fill=tuple(min(255, int(ch * sh)) for ch in c))
    objs = pmp.read_pmp(tp); bad = 0
    def ground(x, z):
        best = None
        for t, a in land:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
            den = (cx - ax) * (bz - az) - (bx - ax) * (cz - az)
            if abs(den) < 1e-9: continue
            u = ((x - ax) * (bz - az) - (bx - ax) * (z - az)) / den; w = ((cx - ax) * (z - az) - (x - ax) * (cz - az)) / den
            if u >= -1e-4 and w >= -1e-4 and u + w <= 1.0001:
                h = ay + u * (cy - ay) + w * (by - ay)
                if best is None or h > best[0]: best = (h, a & 0x1f)
        return best
    for o in objs:
        x, y, z = o['pos']
        if o['grp'] == 2 and o['typ'] in (2, 3):
            g = ground(x, z)
            if g is not None and y < g[0] - 1000: continue   # arbre enterre volontairement
            if g is None or abs(g[0] - y) > 3: bad += 1
            dr.ellipse([(x - x0) * S - 3, (z - z0) * S - 3, (x - x0) * S + 3, (z - z0) * S + 3], fill=(255, 40, 40))
        elif (o['grp'], o['typ']) in ((2, 0), (11, 1)):
            dr.rectangle([(x - x0) * S - 5, (z - z0) * S - 5, (x - x0) * S + 5, (z - z0) * S + 5], fill=(255, 255, 0))
    # cameras : marge minimale au-dessus du sol (max du sol dans un rayon de 100 sous la camera)
    import scn0cam, brres as _br
    b = f['brres']; t = _br.brres_tree(b); clr = []
    import numpy as _np
    cell = {}
    for tt, a in land:
        xs_ = [v[0] for v in tt]; zs_ = [v[2] for v in tt]
        for i in range(int(min(xs_) // 200), int(max(xs_) // 200) + 1):
            for j in range(int(min(zs_) // 200), int(max(zs_) // 200) + 1): cell.setdefault((i, j), []).append(tt)
    def gmax(x, z):
        m = -1e9
        for tt in cell.get((int(x // 200), int(z // 200)), []):
            if min(v[0] for v in tt) - 100 <= x <= max(v[0] for v in tt) + 100 and min(v[2] for v in tt) - 100 <= z <= max(v[2] for v in tt) + 100:
                m = max(m, max(v[1] for v in tt))
        return m
    for name, o, _ in t.get('AnmScn(NW4R)', []):
        if '_cam' not in name: continue
        size = struct.unpack('>I', b[o + 4:o + 8])[0]
        nfr, tr, where = scn0cam.read_cam(b[o:o + size])
        for fr in range(0, nfr, 3):
            px, py, pz = (scn0cam.hermite(tr[k], fr) for k in ('posX', 'posY', 'posZ'))
            g_ = gmax(px, pz)
            if g_ > -1e8: clr.append(py - g_)
    cam_min = round(min(clr)) if clr else None
    dr.text((5, 5), '%s  relief %d..%d' % (title, y0, y1), fill=(255, 255, 255))
    img.save(png)
    print(path, 'manques', miss, 'arbres hors-sol', bad, 'relief', round(y0), round(y1), 'camera marge min', cam_min)
if __name__ == '__main__':
    check(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '')
