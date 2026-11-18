import sys, os, subprocess, math
sys.path.insert(0,'/home/user/wsr/tools')
from multiprocessing import Pool
import nintendo
from kcl import read_kcl; from kcltri import tri_vertices; from pmp import read_pmp
exec(open('/tmp/cupcheck.py').read().split('def check')[0].split('from kcl')[0])
def dseg(px,pz,a,b): return dist_pt_seg(px,pz,a,b)
exec('\n'.join(l for l in open('/tmp/cupcheck.py').read().split('def check')[0].splitlines() if l.startswith(('def','    ','    '))))
def one(path):
    pid=os.getpid(); d=nintendo.load_carc(path); i='/tmp/ac_%d_in'%pid; o='/tmp/ac_%d_out'%pid
    open(i,'wb').write(d); subprocess.run(['/home/user/wsr/ingame/gen/gen_host',i,o,'7'],capture_output=True)
    od=open(o,'rb').read(); f={}
    for n,a,s in nintendo.u8_list(od):
        if n.endswith(('.kcl','.pmp')): open('/tmp/ac_%d.%s'%(pid,n[-3:]),'wb').write(od[a:a+s])
    k=read_kcl('/tmp/ac_%d.kcl'%pid); T=[tri_vertices(k,p) for p in k['prisms'] if p[6]&0x1f==6]
    worst=99
    for ob in read_pmp('/tmp/ac_%d.pmp'%pid):
        if (ob['grp'],ob['typ'])!=(2,1): continue
        x,y,z=ob['pos']; n=0; m=0
        for A,B,C in T:
            if abs(A[1]-y)>20: continue
            dm=min(dseg(x,z,A,B),dseg(x,z,B,C),dseg(x,z,C,A))
            if inside(x,z,A,B,C) or dm<2: n+=1; m=dm
        worst=min(worst, m if n==1 else -n)
    return os.path.basename(path), worst
D='/home/user/wsr/out/full23'
with Pool(os.cpu_count()) as P: r=P.map(one, sorted(D+'/'+f for f in os.listdir(D) if f.endswith('.carc')))
bad=[x for x in r if x[1]<3.5]; print(len(r),'archives ; marge min',round(min(x[1] for x in r),2),'; en defaut :',bad or 'aucune')

# regle permanente : normales de la collision de longueur 1 apres passage Wii (sinon eau fantome)
import numpy as _np
def _nrm(path):
    pid=os.getpid(); d=nintendo.load_carc(path); i='/tmp/an_%d_in'%pid; o='/tmp/an_%d_out'%pid
    open(i,'wb').write(d); subprocess.run(['/home/user/wsr/ingame/gen/gen_host',i,o,'7'],capture_output=True)
    od=open(o,'rb').read()
    for n,a,s in nintendo.u8_list(od):
        if n.endswith('.kcl'): open('/tmp/an_%d.kcl'%pid,'wb').write(od[a:a+s])
    k=read_kcl('/tmp/an_%d.kcl'%pid); N=_np.array(k['nrms']); used=sorted({j for p in k['prisms'] for j in p[2:6]})
    L=_np.linalg.norm(N[used],axis=1); return os.path.basename(path), float(abs(L-1).max())
with Pool(os.cpu_count()) as P: rn=P.map(_nrm, sorted(D+'/'+f for f in os.listdir(D) if f.endswith('.carc')))
badn=[x for x in rn if x[1]>1e-3]; print('normales : ecart max %.2e ; en defaut :'%max(x[1] for x in rn), badn or 'aucune')
