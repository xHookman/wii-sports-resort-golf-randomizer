import sys
sys.path.insert(0, '/home/user/wsr/tools')
from brres import brres_tree
from mdl0 import read_mdl0
def value_tris(d, model=0):
    """Triangles de chaque objet avec les valeurs reelles des attributs."""
    t = brres_tree(d); m = read_mdl0(d, t['3DModels(NW4R)'][model][1])
    A = {}
    for kind in ('pos', 'nrm', 'clr', 'uv'):
        for n, v, meta in m['arr'][kind]: A[(kind, meta['idx'])] = v
    out = {}
    for p in m['polys']:
        ids = dict(zip(['pos', 'nrm', 'clr0', 'clr1'] + ['uv%d' % k for k in range(8)], p['ids']))
        tl = []
        for tri in p['tris']:
            tv = []
            for v in tri:
                e = {}
                for s, i in v.items():
                    kind = 'uv' if s.startswith('uv') else ('clr' if s.startswith('clr') else s)
                    e[s] = A[(kind, ids[s])][i]
                tv.append(e)
            tl.append(tv)
        out[p['name']] = tl
    return out, m
