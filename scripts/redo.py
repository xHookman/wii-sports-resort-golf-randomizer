import sys,os; sys.path.insert(0,'/home/user/wsr/ingame'); sys.path.insert(0,'/home/user/wsr/tools')
import build_pool3 as B
from multiprocessing import Pool
h=sys.argv[1]; par=dict(B.HOLES)[h]; seed=int(sys.argv[2])
with Pool(2) as P:
    for name,i,log in P.imap_unordered(B.job,[(h,par,i,seed,'/home/user/wsr/out/pool23') for i in range(16)]): print(name,i,log[-1],flush=True)
