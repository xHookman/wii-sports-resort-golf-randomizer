import sys,os; sys.path.insert(0,'/home/user/wsr/tools'); sys.path.insert(0,'/home/user/wsr/scripts')
os.environ['NMODE']='2'; os.environ['MIRROR']='1'
import make_hole; from render import render
h,par,seed=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])
r=make_hole.make(h,par,seed,'/home/user/wsr/scripts/z.carc'); g=r['g']
print(r['problems'], g['cut'], g['style'], g['feature'])
x0,z0,x1,z1=g['pond'].buffer(150).bounds
render('/home/user/wsr/scripts/z.carc',sys.argv[4],W=700,box=(x0,z0,x1,z1))
