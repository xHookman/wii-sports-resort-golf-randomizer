"""Mode complet : trace tire au hasard parmi N variantes (crochet du pool) + relief et arbres generes sur la Wii.
Produit outputs/full/ (archives + loader.bin) et outputs/wsrgolf_full.xml."""
import sys, os, struct, shutil
sys.path.insert(0, '/home/user/wsr/tools'); sys.path.insert(0, '/home/user/wsr/ingame')
import nintendo, cave
from pack import u8_build, yaz0_compress
N = int(sys.argv[1]) if len(sys.argv) > 1 else 16
POOL = sys.argv[2] if len(sys.argv) > 2 else 'pool'
SUB = sys.argv[3] if len(sys.argv) > 3 else 'full'
HOLES = ['fcJP11', 'fcJP6', 'fcJP12', 'fcJP16', 'fcJP7', 'fcJP10', 'fcJP9', 'fcJP13', 'fcJP3', 'fc1', 'fc3', 'fc5', 'fc8', 'fc9', 'fc12', 'fc13', 'fc14', 'fc16']
OUT = '/home/user/wsr/out/' + SUB; os.makedirs(OUT, exist_ok=True)
blob = open('wsrgen.bin', 'rb').read()
ONLY = set(os.environ.get('ONLY', '').split()) - {''}     # ONLY="fcJP3_0 fcJP7_1" : ne refaire que ces archives
for h in HOLES:
    for i in range(N):
        if ONLY and '%s_%d' % (h, i) not in ONLY: continue
        src = '/home/user/wsr/out/%s/glf_course_%s_%d.carc' % (POOL, h, i)
        d = nintendo.yaz0_decompress(open(src, 'rb').read())
        ents = []
        for e in nintendo.u8_list(d):
            data = d[e[1]:e[1] + e[2]]
            if e[0].endswith('.kcl'): data += b'\0' * 0x40000          # place pour reecrire la collision
            ents.append((e[0], data))
        ents.append(('wsrgen.bin', blob))
        open('%s/glf_course_%s_%d.carc' % (OUT, h, i), 'wb').write(yaz0_compress(u8_build(ents)))
shutil.copy('loader.bin', OUT + '/loader.bin')
def xml(n, title, path):
    code, data, hook = cave.build(cave.CODE_AT, cave.DATA_AT, HOLES, n, mirror=bool(os.environ.get('MIRROR_POOL')))
    assert cave.CODE_AT + len(code) <= 0x80004580 and 0x80002000 <= cave.DATA_AT and cave.DATA_AT + len(data) <= 0x80003000
    gen_hook = (18 << 26) | ((0x800017A0 - 0x80417DAC) & 0x3fffffc) | 1
    L = ['<wiidisc version="1">', '  <id game="RZT" />', '  <options>', '    <section name="Golf generateur">',
         '      <option name="%s">' % title,
         '        <choice name="Active"><patch id="gen%d" /></choice>' % n, '      </option>', '    </section>', '  </options>',
         '  <patch id="gen%d" root="/wsrgolf/%s">' % (n, SUB),
         '    <memory offset="0x%08X" value="%s" />' % (cave.CODE_AT, code.hex()),
         '    <memory offset="0x%08X" value="%s" />' % (cave.DATA_AT, data.hex()),
         '    <memory offset="0x%08X" value="%s" />' % (cave.CALL_SITE, hook.hex()),
         '    <memory offset="0x80417BA8" value="%08x" />' % cave.b(0x80417BA8, cave.CODE_AT, 1),
         '    <memory offset="0x800017A0" valuefile="loader.bin" />',
         '    <memory offset="0x80417DAC" value="%08x" />' % gen_hook]
    for h in HOLES:
        for i in range(n):
            f = 'glf_course_%s_%d.carc' % (h, i)
            L.append('    <file disc="/Stage/Shared2/%s" external="%s" create="true" />' % (f, f))
    L += ['  </patch>', '</wiidisc>']
    open(path, 'w').write('\n'.join(L) + '\n')
TITLE = sys.argv[4] if len(sys.argv) > 4 else 'Trous generes (Resort A 1-3)'
xml(N, TITLE, '/home/user/wsr/out/wsrgolf_%s.xml' % SUB)
print('ok', N, 'variantes par trou')
