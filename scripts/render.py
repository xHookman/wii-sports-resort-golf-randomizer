import sys; sys.path.insert(0,'/home/user/wsr/tools')
import nintendo, numpy as np
from meshio import value_tris; from gen import _obj2mat
from PIL import Image, ImageDraw
COL={'M_Fairway':(120,200,90),'M_Rough':(70,140,55),'M_Green':(170,230,120),'M_Color':(140,210,100),'M_Bunker':(235,215,160),
     'M_OB':(50,105,45),'M_Iwa':(130,120,110),'M_Sea':(40,90,170),'M_Lake':(60,140,210),'M_XNamiuchi':(220,235,255),
     'M_Kiwa_R':(80,150,60),'M_Kiwa_F':(110,190,85),'M_Kiwa_OB':(60,120,50),'M_Kiwa_Bunker':(215,195,140),'M_Beach':(230,220,180)}
def render(carc, out, W=900, box=None, tex=True):
    d=nintendo.load_carc(carc)
    br=[d[a:a+s] for n,a,s in nintendo.u8_list(d) if n.endswith('.brres') and 'course' in n][0]
    vt,m=value_tris(br); o2m=_obj2mat(m)
    T=[]
    for n,tl in vt.items():
        mt=o2m.get(n)
        for t in tl:
            P=np.array([v['pos'] for v in t])
            if P[:,1].min()<-8000: continue
            c=COL.get(mt,(150,150,150))
            if 'clr0' in t[0] and mt not in ('M_Sea','M_Lake','M_XNamiuchi'):
                k=np.mean([v['clr0'][:3] for v in t],0)/255.0; c=tuple(int(a*(0.55+0.45*kk)) for a,kk in zip(c,k))
            T.append((P[:,1].mean(),P,c,mt))
    allP=np.concatenate([t[1] for t in T if t[3] not in ('M_Sea',) or np.ptp(t[1][:,0])<3000])
    x0,z0,x1,z1=box or (allP[:,0].min(),allP[:,2].min(),allP[:,0].max(),allP[:,2].max())
    s=W/max(x1-x0,z1-z0); img=Image.new('RGB',(int((x1-x0)*s)+1,int((z1-z0)*s)+1),(0,0,0)); dr=ImageDraw.Draw(img)
    for y,P,c,mt in sorted(T,key=lambda t:(t[3] not in ('M_Sea',), t[0])):
        dr.polygon([((p[0]-x0)*s,(p[2]-z0)*s) for p in P],fill=c)
    img.save(out); return (x0,z0,x1,z1)
if __name__=='__main__':
    render(sys.argv[1],sys.argv[2])
