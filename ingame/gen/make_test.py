"""Archives de test (KCL prolonge de zeros + wsrgen.bin) et XML Riivolution du generateur sur Wii."""
import sys, os, shutil
sys.path.insert(0, '/home/user/wsr/tools')
import nintendo
from pack import u8_build, yaz0_compress
OUT = '/home/user/wsr/out/gen'; os.makedirs(OUT, exist_ok=True)
HOLES = ['fcJP11', 'fcJP6', 'fcJP12']
blob = open('wsrgen.bin', 'rb').read()
for h in HOLES:
    d = nintendo.yaz0_decompress(open('/home/user/wsr/out/pool/glf_course_%s_0.carc' % h, 'rb').read())
    ents = []
    for e in nintendo.u8_list(d):
        data = d[e[1]:e[1] + e[2]]
        if e[0].endswith('.kcl'): data += b'\0' * 0x40000
        ents.append((e[0], data))
    ents.append(('wsrgen.bin', blob))
    open('%s/glf_course_%s.carc' % (OUT, h), 'wb').write(yaz0_compress(u8_build(ents)))
shutil.copy('loader.bin', OUT + '/loader.bin')
hook = (18 << 26) | ((0x800017A0 - 0x80417DAC) & 0x3fffffc) | 1
L = ['<wiidisc version="1">', '  <id game="RZT" />', '  <options>', '    <section name="Golf generateur">',
     '      <option name="Generation sur la Wii (Resort A 1-3)">',
     '        <choice name="Active"><patch id="gen" /></choice>', '      </option>', '    </section>', '  </options>',
     '  <patch id="gen" root="/wsrgolf/gen">',
     '    <memory offset="0x800017A0" valuefile="loader.bin" />',
     '    <memory offset="0x80417DAC" value="%08x" />' % hook]
for h in HOLES:
    L.append('    <file disc="/Stage/Shared2/glf_course_%s.carc" external="glf_course_%s.carc" />' % (h, h))
L += ['  </patch>', '</wiidisc>']
open('/home/user/wsr/out/wsrgolf_poc.xml', 'w').write('\n'.join(L) + '\n')
# verification : l'archive contient bien le generateur
d = nintendo.yaz0_decompress(open('%s/glf_course_fcJP11.carc' % OUT, 'rb').read())
for e in nintendo.u8_list(d):
    if e[0] == 'wsrgen.bin': assert d[e[1]:e[1] + e[2]] == blob and e[1] % 32 == 0, e
print('ok', hex(hook))
