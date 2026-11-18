import sys, os; sys.path.insert(0,'/home/user/wsr/tools'); sys.path.insert(0,'/tmp')
import numpy as np, nintendo, make_hole, nvar, shapely as sh
from meshio import value_tris; from gen import _obj2mat
from kcl import read_kcl; from kcltri import tri_vertices
from multiprocessing import Pool
def tri_cover(T, P):
    # T (n,3,2) ; P (m,2) -> nombre de triangles contenant chaque point
    A,B,C=T[:,0],T[:,1],T[:,2]
    out=np.zeros(len(P),int)
    for k in range(0,len(P),200):
        p=P[k:k+200][:,None,:]
        def s(a,b): return (b[None,:,0]-a[None,:,0])*(p[...,1]-a[None,:,1])-(b[None,:,1]-a[None,:,1])*(p[...,0]-a[None,:,0])
        d1,d2,d3=s(A,B),s(B,C),s(C,A)
        ins=((d1>=-1e-6)&(d2>=-1e-6)&(d3>=-1e-6))|((d1<=1e-6)&(d2<=1e-6)&(d3<=1e-6))
        out[k:k+200]=ins.sum(1)
    return out
def one(f):
    h=os.path.basename(f).rsplit('_',1)[0].replace('glf_course_','')
    idx=int(os.path.basename(f).rsplit('_',1)[1].split('.')[0])
    tpl=make_hole.template(h, True); E,_,_=nvar.zone(tpl)
    d=nintendo.load_carc(f); F={n:d[a:a+s] for n,a,s in nintendo.u8_list(d)}
    br=[v for n,v in F.items() if n.endswith('.brres') and 'course' in n][0]
    vt,m=value_tris(br); o2m=_obj2mat(m)
    G=np.array([[(v['pos'][0],v['pos'][2]) for v in t] for n,tl in vt.items() if o2m.get(n) in nvar.GROUND|{'M_Iwa','M_Sea','M_Lake','M_Beach'} for t in tl if min(v['pos'][1] for v in t)>-8000])
    P=[]
    for off in (1.5,-1.5):
        ring=E.buffer(off).boundary; L=ring.length; ts=np.linspace(0,L,max(200,int(L/7)))
        P+= [(ring.interpolate(t).x,ring.interpolate(t).y) for t in ts]
    P=np.array(P)
    # decale de +-1 unite perpendiculairement
    Pin=np.array([q for q in P]); 
    cov_m=tri_cover(G,P)
    open('/tmp/sk_%d.kcl'%os.getpid(),'wb').write([v for n,v in F.items() if n.endswith('.kcl')][0])
    k=read_kcl('/tmp/sk_%d.kcl'%os.getpid())
    K=np.array([[(v[0],v[2]) for v in tri_vertices(k,p)] for p in k['prisms'] if p[6] not in (0x805,0x80d)])
    cov_k=tri_cover(K,P)
    return os.path.basename(f), int((cov_m==0).sum()), int((cov_k==0).sum()), len(P)
if __name__=='__main__':
    fs=sys.argv[1:]
    with Pool(6) as Pp:
        for r in Pp.imap_unordered(one,fs): print('%-22s points sans dessin %d, sans collision %d / %d'%r, flush=True)
