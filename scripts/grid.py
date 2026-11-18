import sys; sys.path.insert(0,'/home/user/wsr/scripts'); sys.path.insert(0,'/home/user/wsr/tools')
from render import render, COL
import nintendo, numpy as np
from meshio import value_tris; from gen import _obj2mat
from PIL import Image, ImageDraw, ImageFont
from multiprocessing import Pool
S='/home/user/wsr/files/Stage/Shared2/glf_course_%s.carc'
NAMES=[('fcJP11','Resort A1'),('fcJP6','Resort A2'),('fcJP12','Resort A3'),('fcJP16','Resort B4'),('fcJP7','Resort B5'),('fcJP10','Resort B6'),
 ('fcJP9','Resort C7'),('fcJP13','Resort C8'),('fcJP3','Resort C9'),('fcJP2','Special (inutilisé)'),('fcJP14','Special (inutilisé)'),('fcJP19','Special (inutilisé)'),
 ('fc1','Classic'),('fc3','Classic'),('fc5','Classic'),('fc8','Classic'),('fc9','Classic'),('fc12','Classic'),('fc13','Classic'),('fc14','Classic'),('fc16','Classic')]
def one(a):
    h,_=a
    d=nintendo.load_carc(S%h)
    br=[d[x:x+s] for n,x,s in nintendo.u8_list(d) if n.endswith('.brres') and 'course' in n][0]
    vt,m=value_tris(br); o2m=_obj2mat(m)
    P=np.concatenate([np.array([v['pos'] for v in t]) for n,tl in vt.items() if o2m.get(n) in ('M_Fairway','M_Green','M_Rough','M_Bunker','M_Lake') for t in tl])
    pad=250; box=(P[:,0].min()-pad,P[:,2].min()-pad,P[:,0].max()+pad,P[:,2].max()+pad)
    lake=any(o2m.get(n)=='M_Lake' for n in vt)
    render(S%h,'/home/user/wsr/scripts/g_%s.png'%h,W=420,box=box)
    return h,lake
with Pool(7) as p: R=dict(p.map(one,NAMES))
W,H=440,500; cols=7
img=Image.new('RGB',(cols*W,3*H),(25,25,25)); dr=ImageDraw.Draw(img)
try: F=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',20); F2=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
except: F=F2=None
for i,(h,lab) in enumerate(NAMES):
    t=Image.open('/home/user/wsr/scripts/g_%s.png'%h); t.thumbnail((420,420))
    x,y=(i%cols)*W,(i//cols)*H
    img.paste(t,(x+10+(420-t.width)//2,y+60+(420-t.height)//2))
    dr.text((x+10,y+8),'%d. %s'%(i+1,h),fill=(255,255,255),font=F)
    dr.text((x+10,y+34),lab+('  · lac' if R[h] else ''),fill=(200,220,255) if R[h] else (190,190,190),font=F2)
img.save('/home/user/wsr/out/trous_nintendo.png'); print(R)
