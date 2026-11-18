"""Version miroir (gauche <-> droite, x -> -x) d'un trou de Nintendo : dessin, minimap, collision, objets.
   python3 mirror.py fcJP3   ->  x/glf_course_fcJP3_M/ (memes noms de fichiers que l'original)
Le generateur l'utilise ensuite comme un modele ordinaire (make_hole.template(nom, miroir=True))."""
import sys, os, struct
sys.path.insert(0, '/home/user/wsr/tools')
from meshio import value_tris
from mdl0write import replace_geometry
from kcl import read_kcl
from kcltri import tri_vertices
from kclwrite import write_kcl
from pmp import read_pmp
from pack import write_pmp

ROOT = '/home/user/wsr'


def mirror_brres(src):
    """Miroir SUR PLACE (meme taille) : x -> -x dans les tableaux de positions et de normales, boites
    englobantes ajustees, sens des faces compense par le mode de rejet des materiaux (arriere <-> avant)."""
    from brres import brres_tree, _dict
    from mdl0 import read_mdl0
    d = bytearray(src)
    t = brres_tree(bytes(d))
    CH = {0: ('B', 1), 1: ('b', 1), 2: ('H', 2), 3: ('h', 2), 4: ('f', 4)}
    for _, mo, _s in t.get('3DModels(NW4R)', []):
        m = read_mdl0(bytes(d), mo)
        secs = struct.unpack('>14i', bytes(d[mo + 16:mo + 16 + 56]))
        for kind, si in (('pos', 2), ('nrm', 3)):
            if not secs[si]: continue                                 # section absente (minimap sans normales)
            for _, o in _dict(bytes(d), mo + secs[si]):
                size, mdl, doff, noff, idx, comp, fmt = struct.unpack('>IiiiIII', bytes(d[o:o + 28]))
                div, stride, count = struct.unpack('>BBH', bytes(d[o + 28:o + 32]))
                c, sz = CH[fmt]
                if fmt in (0, 2): raise ValueError('tableau non signe : miroir impossible sur place')
                per = (3 if comp == 1 else 2) if kind == 'pos' else (3 if comp == 0 else 9)
                step = 3 if kind == 'nrm' else per
                for i in range(count):
                    base = o + doff + stride * i
                    for k in range(0, per, step):
                        q = base + sz * k
                        v = struct.unpack('>' + c, bytes(d[q:q + sz]))[0]
                        nv = -v
                        if fmt == 1: nv = max(-128, min(127, nv))
                        if fmt == 3: nv = max(-32768, min(32767, nv))
                        struct.pack_into('>' + c, d, q, nv)
                if kind == 'pos' and per == 3:
                    mn = list(struct.unpack('>3f', bytes(d[o + 0x20:o + 0x2C]))); mx = list(struct.unpack('>3f', bytes(d[o + 0x2C:o + 0x38])))
                    mn[0], mx[0] = -mx[0], -mn[0]
                    struct.pack_into('>6f', d, o + 0x20, *mn, *mx)
        for _, o in (_dict(bytes(d), mo + secs[8]) if secs[8] else []):   # materiaux : rejet arriere <-> avant
            cull = struct.unpack('>I', bytes(d[o + 0x18:o + 0x1C]))[0]
            if cull in (1, 2): struct.pack_into('>I', d, o + 0x18, 3 - cull)
        for _, o in (_dict(bytes(d), mo + secs[1]) if secs[1] else []):   # os : translation et boite
            tx = struct.unpack('>f', bytes(d[o + 0x38:o + 0x3C]))[0]; struct.pack_into('>f', d, o + 0x38, -tx)
            b6 = list(struct.unpack('>6f', bytes(d[o + 0x44:o + 0x5C]))); b6[0], b6[3] = -b6[3], -b6[0]
            struct.pack_into('>6f', d, o + 0x44, *b6)
    return bytes(d)


def mirror_brres_rewrite(src):
    vt, m = value_tris(src)
    targets = {}
    for name, tl in vt.items():
        out = []
        for t in tl:
            tt = []
            for v in (t[0], t[2], t[1]):                     # sens inverse : la face reste vers le haut
                e = dict(v)
                x, y, z = v['pos']; e['pos'] = (-x, y, z)
                if 'nrm' in v: nx, ny, nz = v['nrm']; e['nrm'] = (-nx, ny, nz)
                tt.append(e)
            out.append(tt)
        targets[name] = out
    return replace_geometry(src, targets)


def mirror_kcl(path):
    k = read_kcl(path)
    tris = []
    for p in k['prisms']:
        A, B, C = tri_vertices(k, p)
        f = lambda v: (-v[0], v[1], v[2])
        tris.append((f(A), f(C), f(B), p[6]))
    return write_kcl(tris)


def mirror_pmp(path):
    raw = open(path, 'rb').read()
    objs = []
    for o in read_pmp(path):
        o = dict(o)
        x, y, z = o['pos']; o['pos'] = (-x, y, z)
        r = list(o['rot'])
        for i in (1, 2, 3, 6): r[i] = -r[i]              # S R S avec S = diag(-1, 1, 1)
        o['rot'] = tuple(r)
        objs.append(o)
    return write_pmp(raw, objs)


def make(name):
    src = '%s/x/glf_course_%s' % (ROOT, name); dst = src + '_M'
    os.makedirs(dst + '/G3D', exist_ok=True)
    for kind in ('course', 'map'):
        b = open('%s/G3D/glf_%s_%s.brres' % (src, kind, name), 'rb').read()
        open('%s/G3D/glf_%s_%s.brres' % (dst, kind, name), 'wb').write(mirror_brres(b))
    open('%s/WS2_glf_course_%s.kcl' % (dst, name), 'wb').write(mirror_kcl('%s/WS2_glf_course_%s.kcl' % (src, name)))
    open('%s/WS2_glf_course_%s.pmp' % (dst, name), 'wb').write(mirror_pmp('%s/WS2_glf_course_%s.pmp' % (src, name)))
    return dst


if __name__ == '__main__':
    for n in sys.argv[1:]: print(make(n))
