"""Test rapide avant un pool complet : 3 graines par trou demande, en parallele, avec limite de temps.
Affiche regles enfreintes, types de variantes, temps ; planche d'apercus dans /home/user/wsr/out/quick.png
python3 quick_test.py [trou ...]   (defaut : les 9 trous)"""
import sys, os, time, collections
from multiprocessing import Pool
sys.path.insert(0, '/home/user/wsr/ingame'); sys.path.insert(0, '/home/user/wsr/tools')
import build_pool3 as B

def one(a):
    name, par, seed = a
    import signal, make_hole
    def _late(*x): raise TimeoutError('bloque')
    signal.signal(signal.SIGALRM, _late); signal.alarm(B.LIMIT)
    t = time.time()
    try:
        r = make_hole.make(name, par, seed, '/tmp/qt_%s_%d.carc' % (name, seed), '/tmp/qt_%s_%d.png' % (name, seed))
        signal.alarm(0); g = r['g']
        feat = g['feature'] if (not g['pond'].is_empty or g['feature'] == 'ile-mer') else '-'
        usz = int.from_bytes(open('/tmp/qt_%s_%d.carc' % (name, seed), 'rb').read()[4:8], 'big')
        if usz > max(B.MAX_BYTES, 1.3 * B.ORIG_SIZE(name)): r['problems'].append('archive trop grosse %.2f Mo' % (usz / 1e6))
        return name, seed, r['problems'], feat, g.get('form'), round(usz / 1e6, 2)
    except Exception as e:
        signal.alarm(0); return name, seed, ['ECHEC ' + str(e)[:50]], None, None, round(time.time() - t, 1)

if __name__ == '__main__':
    want = sys.argv[1:] or [h for h, _ in B.HOLES]
    jobs = [(h, p, s) for h, p in B.HOLES if h in want for s in (101, 202, 303)]
    with Pool(os.cpu_count()) as P: res = P.map(one, jobs)
    for r in res: print(*r)
    print('types :', dict(collections.Counter((r[0], r[3]) for r in res)))
    from PIL import Image
    ims = [Image.open('/tmp/qt_%s_%d.png' % (r[0], r[1])) for r in res if r[3] is not None]
    if ims:
        w = 300; rows = [ims[i:i + 6] for i in range(0, len(ims), 6)]
        sheet = Image.new('RGB', (w * 6, max(int(im.height * w / im.width) for im in ims) * len(rows)), (20, 30, 50))
        hmax = sheet.height // len(rows)
        for ri, row in enumerate(rows):
            for ci, im in enumerate(row): sheet.paste(im.resize((w, int(im.height * w / im.width))), (ci * w, ri * hmax))
        sheet.save('/home/user/wsr/out/quick.png')
