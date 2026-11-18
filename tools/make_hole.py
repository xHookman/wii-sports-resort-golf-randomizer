import os
"""Genere un trou complet a la place d'un trou de Nintendo.
   python3 make_hole.py CRENEAU PAR GRAINE SORTIE.carc [APERCU.png]
   ex. : python3 make_hole.py fcJP11 4 12 out/a.carc out/a.png"""
import sys, os, pickle, random, tempfile
sys.path.insert(0, '/home/user/wsr/tools')
from nintendo import load_carc, u8_list
from build import build_model, build_kcl, build_pmp, build_cameras, build_map_trees
from pack import u8_build, yaz0_compress
from gen import generate, Template, validate
from pmp import read_pmp
from preview import topview

ROOT = '/home/user/wsr'
ORIG = '/home/user/wsr/files/Stage/Shared2/glf_course_%s.carc'


_TPL, _ORIG = {}, {}
def template(name, miroir=None):
    if miroir is None: miroir = bool(os.environ.get('MIRROR'))
    k = name + ('_M' if miroir else '')
    if k in _TPL: return _TPL[k]
    _TPL[k] = _template(name, miroir); return _TPL[k]


def _template(name, miroir=False):
    sfx = '_M' if miroir else ''
    p = '%s/tpl_%s%s.pkl' % (ROOT, name, sfx)
    if os.path.exists(p): return pickle.load(open(p, 'rb'))
    if miroir and not os.path.isdir('%s/x/glf_course_%s_M' % (ROOT, name)):
        import mirror; mirror.make(name)
    tpl = Template('%s/x/glf_course_%s%s' % (ROOT, name, sfx), name)
    pickle.dump(tpl, open(p, 'wb'))
    return tpl


def make(name, par, seed, out, png=None, **kw):
    tpl = template(name)
    if os.environ.get('NMODE'):
        import nvar; g = nvar.generate_n(tpl, seed, par)
    else:
        g = generate(tpl, seed, par, **kw)
    problems = validate(tpl, g)
    old_green = [o for o in tpl.pmp if (o['grp'], o['typ']) == (11, 1)][0]['pos']
    course, w1 = build_model(tpl.course, g, tpl.uvfit, old_green)
    course, cam_avoid = build_cameras(tpl, g, course)
    pmp, ntrees = build_pmp(tpl, g, random.Random(seed * 7 + 1), cam_avoid)
    mp, w2 = build_model(tpl.map, g, tpl.uvfit, old_green, 'map')
    mp = build_map_trees(mp, g, seed)
    kcl = build_kcl(tpl, g)
    d = _ORIG.get(name) or _ORIG.setdefault(name, load_carc(ORIG % name))
    rep = {'G3D/glf_course_%s.brres' % name: course, 'G3D/glf_map_%s.brres' % name: mp,
           'WS2_glf_course_%s.kcl' % name: kcl, 'WS2_glf_course_%s.pmp' % name: pmp}
    entries = [(p.lstrip('/'), rep.get(p.lstrip('./'), d[off:off + sz])) for p, off, sz in u8_list(d)]
    assert all(k in [e[0] for e in entries] for k in rep), 'fichier manquant dans l\'archive'
    open(out, 'wb').write(yaz0_compress(u8_build(entries)))
    if png:
        f = tempfile.NamedTemporaryFile(suffix='.pmp', delete=False); f.write(pmp); f.close()
        topview(g, read_pmp(f.name), 420, '%s graine %d  par %d  %.0f u' % (name, seed, par, g['Ltot'])).save(png)
    import build as _b
    return dict(warn=w1 + w2, tris=len(g['tris']), L=round(g['Ltot']), cam_err=dict(_b.CAM_ERR), problems=problems, g=g)


if __name__ == '__main__':
    r = make(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    r.pop('g'); print(r)
