import sys; sys.path.insert(0,'/home/user/wsr/tools')
import nintendo
from meshio import value_tris; from gen import _obj2mat
from shapely.geometry import Polygon
from shapely.ops import unary_union
for i in range(16):
    f='/home/user/wsr/out/full23/glf_course_fcJP6_%d.carc'%i
    d=nintendo.load_carc(f); F={n:d[a:a+s] for n,a,s in nintendo.u8_list(d)}
    br=[v for n,v in F.items() if n.endswith('.brres') and 'course' in n][0]
    vt,m=value_tris(br); o2m=_obj2mat(m)
    P=lambda t: Polygon([(v['pos'][0],v['pos'][2]) for v in t])
    lake=unary_union([P(t) for n,tl in vt.items() if o2m.get(n)=='M_Lake' for t in tl if P(t).area>1])
    sea=unary_union([P(t) for n,tl in vt.items() if o2m.get(n)=='M_Sea' for t in tl if P(t).area>1])
    print(i, 'lac', int(lake.area), 'mer sous le lac', round(lake.intersection(sea).area,1))
