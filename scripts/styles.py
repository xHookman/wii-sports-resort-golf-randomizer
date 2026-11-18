import sys,os; sys.path.insert(0,'/home/user/wsr/tools')
os.environ['NMODE']='2'; os.environ['MIRROR']='1'
import make_hole, nvar, collections
from gen import validate
from multiprocessing import Pool
H=[('fcJP11', 4), ('fcJP6', 3), ('fcJP12', 5), ('fcJP16', 3), ('fcJP7', 5), ('fcJP10', 4), ('fcJP9', 4), ('fcJP13', 3), ('fcJP3', 5),('fc1', 4), ('fc3', 3), ('fc5', 4), ('fc8', 5), ('fc9', 3), ('fc12', 4), ('fc13', 5), ('fc14', 3), ('fc16', 4)]
def one(a):
    h,p,s=a
    try:
        tpl=make_hole.template(h,True); g=nvar.generate_n(tpl,s,p); pb=validate(tpl,g)
        return h,g['style'],g['cut'],len(pb)==0,bool(g.get('pond_xf')),pb
    except Exception as e: return h,'ERR '+str(e)[:40],None,False,False
jobs=[(h,p,s) for h,p in H for s in range(1,7)]
R=collections.defaultdict(list)
with Pool(8) as P:
    for r in P.imap_unordered(one,jobs): R[r[0]].append(r[1:])
for h,_ in H: print(h, collections.Counter(x[0] for x in R[h]), collections.Counter(x[1] for x in R[h]), 'ok %d/6'%sum(x[2] for x in R[h]))
for h,_ in H:
    for x in R[h]:
        if not x[2] and len(x)>4: print(h, x[0], x[1], x[4][:3])
