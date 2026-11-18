import sys, math
sys.path.insert(0, '/home/user/wsr/tools')
from brres import brres_tree
from mdl0 import read_mdl0
from PIL import Image, ImageDraw
BASE = {'M_Fairway': (125, 190, 80), 'M_Green': (150, 215, 100), 'M_Rough': (80, 150, 60), 'M_OB': (55, 115, 45),
        'M_Bunker': (230, 210, 150), 'M_Sea': (50, 110, 180), 'M_XNamiuchi': (210, 230, 240), 'M_Iwa': (130, 120, 105),
        'M_Hayashi': (35, 80, 35), 'M_Hahashi2': (35, 80, 35), 'M_OtherCourse': (70, 130, 60), 'M_Color': (160, 160, 150),
        'M_Kiwa_Black': (40, 50, 40), 'M_Kiwa_OB': (70, 120, 55), 'M_Kiwa_R': (95, 155, 65), 'M_Kiwa_F': (115, 180, 75),
        'M_Kiwa_Bunker': (200, 185, 135)}
def mesh(path):
    d = open(path, 'rb').read(); t = brres_tree(d)
    m = read_mdl0(d, t['3DModels(NW4R)'][0][1])
    pos = {meta['idx']: v for n, v, meta in m['arr']['pos']}
    clr = {meta['idx']: v for n, v, meta in m['arr']['clr']}
    obj2mat = {}
    for lst in m['links'].values():
        for mat, obj, bone in lst: obj2mat[obj] = m['mats'][mat]
    out = []
    for oi, p in enumerate(m['polys']):
        mat = obj2mat.get(oi, '?'); P = pos[p['ids'][0]]; C = clr.get(p['ids'][2])
        for t3 in p['tris']:
            vs = [P[v['pos']] for v in t3]
            cs = [C[v['clr0']] for v in t3] if C and 'clr0' in t3[0] else None
            out.append((mat, vs, cs))
    return out
def render(tris, W=900, H=600, eye=(0, 5200, 7600), target=(0, -200, -600), fov=50, title=None):
    ex, ey, ez = eye; tx, ty, tz = target
    f = [tx - ex, ty - ey, tz - ez]; fl = math.sqrt(sum(c * c for c in f)); f = [c / fl for c in f]
    up = [0, 1, 0]; r = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]]
    rl = math.sqrt(sum(c * c for c in r)); r = [c / rl for c in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    k = (H / 2) / math.tan(math.radians(fov) / 2)
    L = [0.4, 0.8, 0.45]; ll = math.sqrt(sum(c * c for c in L)); L = [c / ll for c in L]
    items = []
    for mat, vs, cs in tris:
        pr = []; depth = 0; ok = True
        for v in vs:
            dx, dy, dz = v[0] - ex, v[1] - ey, v[2] - ez
            z = dx * f[0] + dy * f[1] + dz * f[2]
            if z < 10: ok = False; break
            pr.append((W / 2 + k * (dx * r[0] + dy * r[1] + dz * r[2]) / z, H / 2 - k * (dx * u[0] + dy * u[1] + dz * u[2]) / z)); depth += z
        if not ok: continue
        a = [vs[1][i] - vs[0][i] for i in range(3)]; b = [vs[2][i] - vs[0][i] for i in range(3)]
        n = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
        nl = math.sqrt(sum(c * c for c in n)) or 1; n = [c / nl for c in n]
        if n[1] < 0: n = [-c for c in n]
        sh = 0.55 + 0.45 * max(0, sum(n[i] * L[i] for i in range(3)))
        base = BASE.get(mat, (255, 0, 255))
        if cs:
            avg = [sum(c[i] for c in cs) / 3 / 255 for i in range(3)]
            base = tuple(base[i] * (0.5 + 0.5 * avg[i]) for i in range(3))
        col = tuple(int(min(255, c * sh)) for c in base)
        items.append((depth / 3, pr, col))
    items.sort(key=lambda t: -t[0])
    im = Image.new('RGB', (W, H), (150, 195, 235)); dr = ImageDraw.Draw(im)
    for _, pr, col in items: dr.polygon(pr, fill=col, outline=col)
    return im
