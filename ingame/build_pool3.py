"""Pool v3 : toutes les variantes de tous les trous en une commande, sur tous les coeurs.
python3 build_pool3.py <dossier de sortie> <variantes par trou> <graine de depart>
Chaque trou est genere sur sa propre ile. Les variantes qui enfreignent une regle de coherence
(gen.validate) sont rejetees et remplacees."""
import sys, os, json, time
from multiprocessing import Pool
sys.path.insert(0, '/home/user/wsr/tools')

def ORIG_SIZE(name):
    d = open('/home/user/wsr/files/Stage/Shared2/glf_course_%s.carc' % name, 'rb').read(8)
    return int.from_bytes(d[4:8], 'big')
MAX_BYTES = 2650000    # decompresse, avant le rembourrage KCL + wsrgen (~0,3 Mo) : <= ~3 Mo en jeu
LIMIT = 150      # secondes par essai : une graine qui bloque (triangulation...) est abandonnee
HOLES = [('fcJP11', 4), ('fcJP6', 3), ('fcJP12', 5), ('fcJP16', 3), ('fcJP7', 5), ('fcJP10', 4), ('fcJP9', 4), ('fcJP13', 3), ('fcJP3', 5),
         # Classic (18 trous) : par deduit de la distance depart -> drapeau de Nintendo
         ('fc1', 4), ('fc3', 3), ('fc5', 4), ('fc8', 5), ('fc9', 3), ('fc12', 4), ('fc13', 5), ('fc14', 3), ('fc16', 4)]


def job(a):
    name, par, i, seed0, out = a
    import make_hole
    # miroir par partie : la seconde moitie des variantes (i >= N/2) est en miroir
    if os.environ.get('MIRROR_POOL'): os.environ['MIRROR'] = '1' if i >= int(os.environ.get('POOL_N', '16')) // 2 else ''
    log = []
    for k in range(60):
        seed = seed0 + 1000 * i + k
        tmp = '%s/.tmp_%s_%d.carc' % (out, name, i)
        import signal
        def _late(*a): raise TimeoutError('trop long (> %d s)' % LIMIT)
        signal.signal(signal.SIGALRM, _late); signal.alarm(LIMIT)
        try:
            r = make_hole.make(name, par, seed, tmp)
            signal.alarm(0)
        except Exception as e:
            signal.alarm(0)
            log.append((seed, 'echec', str(e)[:60])); continue
        usz = int.from_bytes(open(tmp, 'rb').read()[4:8], 'big')
        lim = max(MAX_BYTES, 1.3 * ORIG_SIZE(name))
        if usz > lim: r['problems'].append('archive trop grosse (%.2f Mo)' % (usz / 1e6))
        if r['problems']:
            log.append((seed, 'rejete', r['problems'])); continue
        os.replace(tmp, '%s/glf_course_%s_%d.carc' % (out, name, i))
        g = r['g']
        log.append((seed, 'ok', g['style'], g.get('form'), g['feature'] if (not g['pond'].is_empty or g['feature'] == 'ile-mer') else '-'))
        return name, i, log
    return name, i, log + [('abandon',)]


if __name__ == '__main__':
    out, n, seed0 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    jobs = [(h, p, i, seed0, out) for i in range(n) for h, p in HOLES]
    t = time.time(); logs = {}
    with Pool(os.cpu_count()) as P:
        for name, i, log in P.imap_unordered(job, jobs):
            logs['%s_%d' % (name, i)] = log
            print('%-8s %2d %s  %.0fs' % (name, i, log[-1][1] if len(log[-1]) > 1 else log[-1][0], time.time() - t), flush=True)
    json.dump(logs, open(out + '/pool.json', 'w'), indent=0)
    bad = [k for k, l in logs.items() if l[-1][1:2] != ('ok',)]
    print('fini en %.0f s, %d variantes, manquantes : %s' % (time.time() - t, len(logs) - len(bad), bad or 'aucune'))
