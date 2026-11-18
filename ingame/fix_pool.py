"""Valide le mode complet (generateur Wii sur PC, 3 graines, en parallele) et regenere les variantes en defaut.
Seules les variantes refaites sont reconstruites et revalidees. python3 fix_pool.py <pool> <full> <titre>"""
import sys, os, subprocess, re
from multiprocessing import Pool
sys.path.insert(0, '/home/user/wsr/ingame'); sys.path.insert(0, '/home/user/wsr/ingame/gen')
os.chdir('/home/user/wsr/ingame/gen')
import build_pool3 as B, validate_all as V
PAR = dict(B.HOLES)

def verdict(path):
    out = V.one(path)
    m = [int(x) for x in re.findall(r'marge min (-?\d+)', out)]
    bad = 'ECHEC' in out or (m and min(m) < 5) or re.search(r'(manques|hors-sol) [1-9]', out)
    return os.path.basename(path)[11:-5], bool(bad)

if __name__ == '__main__':
    pool, full, title = sys.argv[1:4]
    D = '/home/user/wsr/out/' + full
    todo = sorted(D + '/' + f for f in os.listdir(D) if f.endswith('.carc'))
    for rnd in range(5):
        with Pool(os.cpu_count()) as P: bad = [k for k, b in P.map(verdict, todo) if b]
        print('tour %d : %d controles, en defaut : %s' % (rnd, len(todo), bad or 'aucun'), flush=True)
        if not bad: break
        with Pool(os.cpu_count()) as P:
            for name, i, log in P.imap_unordered(B.job, [(k.rsplit('_', 1)[0], PAR[k.rsplit('_', 1)[0]], int(k.rsplit('_', 1)[1]), 30000 + 7000 * rnd, '/home/user/wsr/out/' + pool) for k in bad]):
                print('  refait', name, i, log[-1], flush=True)
        subprocess.run(['python3', 'make_full.py', '16', pool, full, title], check=True, capture_output=True, env=dict(os.environ, ONLY=' '.join(bad)))
        todo = [D + '/glf_course_%s.carc' % k for k in bad]
