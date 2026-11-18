import sys, os, subprocess
from multiprocessing import Pool
HOLES=dict([('fc1', 4), ('fc3', 3), ('fc5', 4), ('fc8', 5), ('fc9', 3), ('fc12', 4), ('fc13', 5), ('fc14', 3), ('fc16', 4), ('fcJP11', 4), ('fcJP6', 3), ('fcJP12', 5), ('fcJP16', 3), ('fcJP7', 5), ('fcJP10', 4), ('fcJP9', 4), ('fcJP13', 3), ('fcJP3', 5)])
def one(a):
    h,seed=a; out='/home/user/wsr/scripts/%s_%d.carc'%(h,seed)
    r=subprocess.run(['python3','/home/user/wsr/tools/make_hole.py',h,str(HOLES[h]),str(seed),out],capture_output=True,text=True,env=dict(os.environ,NMODE=os.environ.get('NMODE','1')),timeout=240)
    last=(r.stdout.strip().splitlines() or [''])[-1]; err=(r.stderr.strip().splitlines() or [''])[-1]
    return h,seed,('OK '+last[-140:]) if r.returncode==0 else 'ERREUR '+err[-200:]
jobs=[(h,int(s)) for h in sys.argv[2:] for s in sys.argv[1].split(',')]
with Pool(min(8,len(jobs))) as P:
    for r in P.imap_unordered(one,jobs): print(*r, flush=True)
