"""Ajoute des variantes au pool : python3 make_pool_more.py <trou> <par> <premier indice> <nombre> <graine de depart>"""
import sys, os, json
sys.path.insert(0, '/home/user/wsr/tools')
import make_hole
name, par, start, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
out = '/home/user/wsr/out/pool'
done, log = start, []
while done < start + n and seed < 400:
    seed += 1
    p = '%s/glf_course_%s_%d.carc' % (out, name, done)
    try:
        r = make_hole.make(name, par, seed, p, '/home/user/wsr/out/pool_%s_%d.png' % (name, done))
    except Exception as e:
        log.append((seed, 'echec', str(e)[:60])); continue
    if r['problems']:
        log.append((seed, 'rejete', r['problems'])); os.path.exists(p) and os.remove(p); continue
    log.append((seed, 'ok', done, r['g']['style'], r['g']['feature'] if not r['g']['pond'].is_empty else '-')); done += 1
    print(name, done, flush=True)
json.dump(log, open('/home/user/wsr/ingame/pool_more_%s.json' % name, 'w'))
print(name, 'fini', done)
