"""XML Riivolution du mode aleatoire : crochet en memoire + 8 variantes par trou ajoutees au disque."""
import struct, sys
sys.path.insert(0, '/home/user/wsr/ingame')
import cave
HOLES = [('fcJP11', 'trou 1'), ('fcJP6', 'trou 2'), ('fcJP12', 'trou 3')]
N = 8
code, data, hook = cave.build(cave.CODE_AT, cave.DATA_AT, [h for h, _ in HOLES], N)
assert cave.CODE_AT + len(code) <= cave.DATA_AT and cave.DATA_AT + len(data) <= 0x80004580
orig_bl = struct.pack('>I', cave.b(cave.CALL_SITE, cave.SNPRINTF, 1)).hex()
assert orig_bl == '4be0d1b9'
L = ['<wiidisc version="1">', '  <id game="RZT" />', '  <options>', '    <section name="Golf generateur">',
     '      <option name="Trous aleatoires (Resort A 1-3)" default="1">',
     '        <choice name="Active"><patch id="pool" /></choice>', '      </option>',
     '    </section>', '  </options>', '  <patch id="pool" root="/wsrgolf/pool">',
     '    <memory offset="0x%08X" value="%s" original="%s" />' % (cave.CODE_AT, code.hex(), '00' * len(code)),
     '    <memory offset="0x%08X" value="%s" original="%s" />' % (cave.DATA_AT, data.hex(), '00' * len(data)),
     '    <memory offset="0x%08X" value="%s" />' % (cave.CALL_SITE, hook.hex())]   # sans 'original' : Dolphin ignorait le patch
for site in (0x80417BA8,):   # second chargeur (golf), appelle directement 0x803EF848
    o = struct.pack('>I', cave.b(site, cave.SNPRINTF, 1)).hex(); assert o == '4bbf54cd'
    L.append('    <memory offset="0x%08X" value="%s" />' % (site, struct.pack('>I', cave.b(site, cave.CODE_AT, 1)).hex()))
for h, _ in HOLES:
    for i in range(N):
        f = 'glf_course_%s_%d.carc' % (h, i)
        L.append('    <file disc="/Stage/Shared2/%s" external="%s" create="true" />' % (f, f))
L += ['  </patch>', '</wiidisc>']
open('/home/user/wsr/out/wsrgolf_pool.xml', 'w').write('\n'.join(L) + '\n')
print('\n'.join(L[:14]))
