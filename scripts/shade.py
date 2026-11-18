import sys; sys.path.insert(0,'/home/user/wsr/tools')
import numpy as np, subprocess, nintendo
from kcl import read_kcl; from kcltri import tri_vertices
from pack import u8_build
from PIL import Image
def wii(carc, seed=7):
    d=nintendo.load_carc(carc); ents=[]
    for n,a,s in nintendo.u8_list(d):
        data=d[a:a+s]
        if n.endswith('.kcl'): data+=b'\0'*0x40000
        ents.append((n,data))
    ents.append(('wsrgen.bin',open('/home/user/wsr/ingame/gen/wsrgen.bin','rb').read()))
    open('/tmp/sh_i.u8','wb').write(u8_build(ents))
    subprocess.run(['/home/user/wsr/ingame/gen/gen_host','/tmp/sh_i.u8','/tmp/sh_o.u8',str(seed)],capture_output=True)
    o=open('/tmp/sh_o.u8','rb').read()
    for n,a,s in nintendo.u8_list(o):
        if n.endswith('.kcl'): open('/tmp/sh.kcl','wb').write(o[a:a+s])
    return read_kcl('/tmp/sh.kcl')
def kcl_of(carc):
    d=nintendo.load_carc(carc)
    for n,a,s in nintendo.u8_list(d):
        if n.endswith('.kcl'): open('/tmp/sh0.kcl','wb').write(d[a:a+s])
    return read_kcl('/tmp/sh0.kcl')
def shade(k, box, W=420):
    x0,z0,x1,z1=box; s=W/(x1-x0); H=int((z1-z0)*s)
    Z=np.full((H,W),np.nan); C=np.zeros((H,W,3))
    COL={1:(120,200,90),2:(70,140,55),3:(235,215,160),4:(50,105,45),6:(170,230,120),7:(40,90,170),9:(140,210,100),12:(130,120,110)}
    for p in k['prisms']:
        if p[6] in (0x805,0x80d): continue
        A,B,Cc=[np.array(v) for v in tri_vertices(k,p)]
        P=np.array([[(v[0]-x0)*s,(v[2]-z0)*s] for v in (A,B,Cc)]); Y=np.array([A[1],B[1],Cc[1]])
        i0,j0=np.floor(P.min(0)).astype(int); i1,j1=np.ceil(P.max(0)).astype(int)
        i0,j0=max(i0,0),max(j0,0); i1,j1=min(i1,W-1),min(j1,H-1)
        if i1<i0 or j1<j0: continue
        xs,ys=np.meshgrid(np.arange(i0,i1+1)+0.5,np.arange(j0,j1+1)+0.5)
        v0=P[2]-P[0]; v1=P[1]-P[0]; den=v0[0]*v1[1]-v1[0]*v0[1]
        if abs(den)<1e-9: continue
        v2x=xs-P[0,0]; v2y=ys-P[0,1]; u=(v2x*v1[1]-v1[0]*v2y)/den; w=(v0[0]*v2y-v2x*v0[1])/den
        m=(u>=-1e-3)&(w>=-1e-3)&(u+w<=1.001)
        h=Y[0]+u*(Y[2]-Y[0])+w*(Y[1]-Y[0])
        cur=Z[j0:j1+1,i0:i1+1]; upd=m&(np.isnan(cur)|(h>cur))
        cur[upd]=h[upd]; C[j0:j1+1,i0:i1+1][upd]=COL.get(p[6]&0x1f,(150,150,150))
    Zf=np.nan_to_num(Z,nan=np.nanmin(Z))
    gy,gx=np.gradient(Zf, 1/s); nx,ny,nz=-gx,-gy,np.ones_like(gx)*1.0
    L=np.array([-0.5,-0.6,0.62]); L/=np.linalg.norm(L)
    sh_=(nx*L[0]+ny*L[1]+nz*L[2])/np.sqrt(nx*nx+ny*ny+nz*nz)
    img=np.clip(C*(0.35+0.9*np.clip(sh_,0,1))[...,None],0,255).astype(np.uint8)
    return Image.fromarray(img)
