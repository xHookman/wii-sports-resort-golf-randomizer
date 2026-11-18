"""Lit une sauvegarde d'etat Dolphin (2609b, LZ4) : MEM1/MEM2, journaux du chargeur et du generateur,
archive du trou chargee et variante correspondante. python3 state_read.py <fichier .sNN> <dossier full>"""
import sys, struct, re, os
sys.path.insert(0, '/home/user/wsr/tools')
import lz4.block, nintendo
from pmp import read_pmp
raw = open(sys.argv[1], 'rb').read()
usize = struct.unpack('<Q', raw[53:61])[0]; p = 61; out = bytearray()
while p < len(raw):
    n = struct.unpack('<i', raw[p:p + 4])[0]; p += 4
    out += lz4.block.decompress(raw[p:p + n], uncompressed_size=usize - len(out)); p += n
d = bytes(out)
dol = open('/home/user/wsr/main.dol', 'rb').read()
toff = struct.unpack('>18I', dol[0:72]); taddr = struct.unpack('>18I', dol[72:144]); tsz = struct.unpack('>18I', dol[144:216])
m1 = None
for k in range(18):
    if tsz[k] > 0x1000:
        i = d.find(dol[toff[k] + 0x400:toff[k] + 0x500])
        if i >= 0: m1 = i - 0x400 - (taddr[k] - 0x80000000); break
M1 = d[m1:m1 + 0x1800000]
print('MEM1 a', hex(m1))
print('chargeur', [hex(struct.unpack('>I', M1[0x3200 + 16 * i:0x3204 + 16 * i])[0]) for i in range(8)])
print('generateur', [hex(struct.unpack('>I', M1[0x3300 + 16 * i:0x3304 + 16 * i])[0]) for i in range(16)])
# archive du trou (U8 contenant WS2_glf_course_)
for mm in re.finditer(re.escape(b'WS2_glf_course_fc'), d):
    u = d.rfind(bytes.fromhex('55aa382d'), 0, mm.start())
    if u < 0 or mm.start() - u > 0x2000: continue
    blob = d[u:u + 0x600000]
    try: ents = nintendo.u8_list(blob)
    except Exception: continue
    F = {q: blob[o:o + s] for q, o, s in ents}
    pm = [q for q in F if q.endswith('.pmp')]
    if not pm: continue
    nm = pm[0].split('course_')[1][:-4]
    open('/tmp/st.pmp', 'wb').write(F[pm[0]])
    cup = [o['pos'] for o in read_pmp('/tmp/st.pmp') if (o['grp'], o['typ']) == (11, 1)][0]
    print('archive en memoire', nm, 'trou', [round(c, 1) for c in cup], 'wsrgen' , any('wsrgen' in q for q in F))
    full = sys.argv[2] if len(sys.argv) > 2 else None
    if full:
        for i in range(16):
            f = '/home/user/wsr/out/%s/glf_course_%s_%d.carc' % (full, nm, i)
            if not os.path.exists(f): continue
            dd = nintendo.yaz0_decompress(open(f, 'rb').read())
            G = {q: dd[o:o + s] for q, o, s in nintendo.u8_list(dd)}
            open('/tmp/st2.pmp', 'wb').write(G[pm[0]])
            c2 = [o['pos'] for o in read_pmp('/tmp/st2.pmp') if (o['grp'], o['typ']) == (11, 1)][0]
            if abs(c2[0] - cup[0]) < 0.5 and abs(c2[2] - cup[2]) < 0.5: print('  = variante', i, 'dy trou %.2f' % (cup[1] - c2[1]))
    open('/tmp/st_live.u8', 'wb').write(blob[:max(o + s for q, o, s in ents)])
    break
