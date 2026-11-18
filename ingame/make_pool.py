import sys, os, json
sys.path.insert(0, '/home/user/wsr/tools')
import make_hole
name, par, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
out = '/home/user/wsr/out/pool'
done, seed, log = 0, 100, []
while done < n and seed < 200:
    seed += 1
    p = '%s/glf_course_%s_%d.carc' % (out, name, done)
    try:
        r = make_hole.make(name, par, seed, p, '/home/user/wsr/out/pool_%s_%d.png' % (name, done))
    except Exception as e:
        log.append((seed, 'echec', str(e)[:60])); continue
    if r['problems']:
        log.append((seed, 'rejete', r['problems'])); os.remove(p); continue
    log.append((seed, 'ok', done, r['g']['style'], r['g']['feature'] if not r['g']['pond'].is_empty else '-')); done += 1
json.dump(log, open('/home/user/wsr/ingame/pool_%s.json' % name, 'w'))
print(name, 'fini', done)
