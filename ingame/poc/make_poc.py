"""Archives de test (KCL prolonge de zeros) + XML Riivolution de la preuve de concept."""
import sys, struct, subprocess, os
sys.path.insert(0, '/home/user/wsr/tools')
import nintendo
from pack import u8_build, yaz0_compress
OUT = '/home/user/wsr/out/poc'; os.makedirs(OUT, exist_ok=True)
HOLES = ['fcJP11', 'fcJP6', 'fcJP12']
for h in HOLES:
    d = nintendo.yaz0_decompress(open('/home/user/wsr/out/pool/glf_course_%s_0.carc' % h, 'rb').read())
    ents = []
    for e in nintendo.u8_list(d):
        data = d[e[1]:e[1] + e[2]]
        if e[0].endswith('.kcl'): data += b'\0' * 0x40000          # place pour reecrire la collision
        ents.append((e[0], data))
    open('%s/glf_course_%s.carc' % (OUT, h), 'wb').write(yaz0_compress(u8_build(ents)))
# blobs de code
for sec, name in [('.text', 'lo'), ('.texthi', 'hi')]:
    subprocess.check_call(['powerpc-linux-gnu-objcopy', '-O', 'binary', '-j', sec, 'poc.elf', '%s/poc_%s.bin' % (OUT, name)])
lo = open('%s/poc_lo.bin' % OUT, 'rb').read(); hi = open('%s/poc_hi.bin' % OUT, 'rb').read()
assert 0x800017A0 + len(lo) <= 0x80003000 and 0x800031A0 + len(hi) <= 0x800037E0
hook = (18 << 26) | ((0x800017A0 - 0x80417DAC) & 0x3fffffc) | 1
L = ['<wiidisc version="1">', '  <id game="RZT" />', '  <options>', '    <section name="Golf generateur">',
     '      <option name="Test relief genere sur la Wii (Resort A 1-3)">',
     '        <choice name="Active"><patch id="poc" /></choice>', '      </option>', '    </section>', '  </options>',
     '  <patch id="poc" root="/wsrgolf/poc">',
     '    <memory offset="0x800017A0" valuefile="poc_lo.bin" />',
     '    <memory offset="0x800031A0" valuefile="poc_hi.bin" />',
     '    <memory offset="0x80417DAC" value="%08x" />' % hook]
for h in HOLES:
    L.append('    <file disc="/Stage/Shared2/glf_course_%s.carc" external="glf_course_%s.carc" />' % (h, h))
L += ['  </patch>', '</wiidisc>']
open('/home/user/wsr/out/wsrgolf_poc.xml', 'w').write('\n'.join(L) + '\n')
print(len(lo), len(hi), hex(hook))
