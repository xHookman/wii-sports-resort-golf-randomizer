import sys; sys.path.insert(0,'/home/user/wsr/tools'); sys.path.insert(0,'/home/user/wsr/scripts')
from render import render
import make_hole, nvar, os
from PIL import Image, ImageDraw
from multiprocessing import Pool
os.environ['MIRROR']='1'
def one(h):
    tpl=make_hole.template(h,True); E,t0,g0=nvar.zone(tpl); x0,z0,x1,z1=E.bounds; b=(x0-300,z0-300,x1+300,z1+300)
    ims=[]
    for i,f in enumerate(['/home/user/wsr/scripts/%s_%d.carc'%(h,s) for s in (1,2)]):
        render(f,'/home/user/wsr/scripts/_%s_%d.png'%(h,i),W=420,box=b); ims.append(Image.open('/home/user/wsr/scripts/_%s_%d.png'%(h,i)))
    return h,ims
hs=sys.argv[2:]
with Pool(6) as P: R=P.map(one,hs)
W=sum(max(a.width for a in ims)*2+30 for h,ims in R); Hh=max(a.height for h,ims in R for a in ims)+30
im=Image.new('RGB',(W,Hh),(25,25,25)); d=ImageDraw.Draw(im); x=0
for h,ims in R:
    d.text((x+5,5),h,fill=(255,255,255))
    for a in ims: im.paste(a,(x,28)); x+=a.width+6
    x+=18
im.save(sys.argv[1])
