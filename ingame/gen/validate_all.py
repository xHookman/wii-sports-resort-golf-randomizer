"""Fait tourner le generateur (version PC) sur toutes les archives du mode complet avec 3 graines et verifie."""
import sys, subprocess, glob, os
sys.path.insert(0, '/home/user/wsr/ingame/gen'); sys.path.insert(0, '/home/user/wsr/tools')
import nintendo
from check import check
from concurrent.futures import ProcessPoolExecutor
def one(path):
    name = os.path.basename(path)[:-5]; out = []
    u8 = '/tmp/va_%s.u8' % name
    open(u8, 'wb').write(nintendo.yaz0_decompress(open(path, 'rb').read()))
    for sd in (11, 222, 3333):
        o = '/tmp/va_%s_%d.u8' % (name, sd)
        r = subprocess.run(['./gen_host', u8, o, str(sd)], capture_output=True, text=True)
        out.append('%s graine %d : %s' % (name, sd, r.stdout.strip()))
        if r.returncode: out.append('  ECHEC'); continue
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): check(o, '/tmp/viz/va_%s_%d.png' % (name, sd), '%s %d' % (name, sd))
        out.append('  ' + buf.getvalue().strip().split(' ', 1)[1])
        os.remove(o)
    os.remove(u8)
    return '\n'.join(out)
if __name__ == '__main__':
    files = sorted(glob.glob('/home/user/wsr/out/%s/*.carc' % os.environ.get('FULL', 'full5')))
    with ProcessPoolExecutor(8) as ex:
        for res in ex.map(one, files): print(res, flush=True)
