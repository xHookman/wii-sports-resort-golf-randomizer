import sys,os; sys.path.insert(0,'/home/user/wsr/tools'); sys.path.insert(0,'/home/user/wsr/scripts')
os.environ['NMODE']='2'; os.environ['MIRROR']='1'
import numpy as np, make_hole, nintendo, shapely as sh
from meshio import value_tris; from gen import _obj2mat
from kcl import read_kcl; from kcltri import tri_vertices
from multiprocessing import Pool
exec(open('/home/user/wsr/scripts/seam.py').read().split('def one')[0].split('from multiprocessing')[1].split('\n',1)[1])
def one(a):
    h,par,seed=a; out='/home/user/wsr/scripts/ps_%s_%d.carc'%(h,seed)
    r=make_hole.make(h,par,seed,out); g=r['g']
    if not g.get('pond_xf'): return h,seed,'pas d etang',r['problems']
    d=nintendo.load_carc(out); F={n:d[x:x+s] for n,x,s in nintendo.u8_list(d)}
    br=[v for n,v in F.items() if n.endswith('.brres') and 'course' in n][0]
    vt,m=value_tris(br)
    G=np.array([[(v['pos'][0],v['pos'][2]) for v in t] for n,tl in vt.items() for t in tl if min(v['pos'][1] for v in t)>-8000])
    P=[]
    for off in (2.0,-2.0):
        ring=g['pond'].buffer(off).boundary; L=ring.length; ts=np.linspace(0,L,max(200,int(L/6)))
        P+=[(ring.interpolate(t).x,ring.interpolate(t).y) for t in ts]
    P=np.array(P)
    open('/tmp/pk_%d.kcl'%os.getpid(),'wb').write([v for n,v in F.items() if n.endswith('.kcl')][0])
    k=read_kcl('/tmp/pk_%d.kcl'%os.getpid())
    K=np.array([[(v[0],v[2]) for v in tri_vertices(k,p)] for p in k['prisms'] if p[6] not in (0x805,0x80d)])
    return h,seed,'rive: sans dessin %d, sans collision %d / %d'%(int((tri_cover(G,P)==0).sum()),int((tri_cover(K,P)==0).sum()),len(P)),r['problems'],g['cut'],g['style']
jobs=[(h,int(p),int(s)) for h,p in [x.split(':') for x in sys.argv[2:]] for s in sys.argv[1].split(',')]
with Pool(6) as P_:
    for r in P_.imap_unordered(one,jobs): print(*r,flush=True)
