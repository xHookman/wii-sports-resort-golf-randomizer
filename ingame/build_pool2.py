"""Pool v2 : variantes pour un emplacement de trou, generees sur l'ile d'un autre trou du Resort si besoin.
python3 build_pool2.py <emplacement> <par> <ile modele> <premier indice> <nombre> <graine de depart>
L'identifiant du modele est remplace par celui de l'emplacement partout (meme longueur obligatoire)."""
import sys, os, json
sys.path.insert(0, '/home/user/wsr/tools')
import make_hole, nintendo
from pack import u8_build, yaz0_compress
slot, par, tpl, start, n, seed = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
assert len(slot) == len(tpl), 'identifiants de longueurs differentes'
out = os.environ.get('POOL_OUT', '/home/user/wsr/out/pool2')
done, log, tries = start, [], 0
while done < start + n and tries < 4 * n + 10:
    seed += 1; tries += 1
    tmp = '/tmp/p2_%s_%s_%d.carc' % (slot, tpl, seed)
    try:
        r = make_hole.make(tpl, par, seed, tmp, '/home/user/wsr/out/pool2_%s_%d.png' % (slot, done))
    except Exception as e:
        log.append((tpl, seed, 'echec', str(e)[:60])); continue
    if r['problems']:
        log.append((tpl, seed, 'rejete', r['problems'])); os.remove(tmp); continue
    d = nintendo.yaz0_decompress(open(tmp, 'rb').read()); os.remove(tmp)
    a, b = tpl.encode(), slot.encode()
    ents = [(p.replace(tpl, slot), d[o:o + s].replace(a, b)) for p, o, s in nintendo.u8_list(d)]
    open('%s/glf_course_%s_%d.carc' % (out, slot, done), 'wb').write(yaz0_compress(u8_build(ents)))
    log.append((tpl, seed, 'ok', done, r['g']['style'], r['g'].get('form'), r['g']['feature'] if not r['g']['pond'].is_empty else '-')); done += 1
    print(slot, tpl, done, flush=True)
json.dump(log, open('/home/user/wsr/ingame/pool2_%s_%s.json' % (slot, tpl), 'w'))
print(slot, tpl, 'fini', done)
