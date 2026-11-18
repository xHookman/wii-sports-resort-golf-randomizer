"""Compile le chargeur (adresse fixe) et le generateur (relogeable) ; produit loader.bin et wsrgen.bin."""
import subprocess, struct, sys
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
FX = ' '.join('-ffixed-fr%d' % i for i in range(14, 32))
CF = ('-m32 -mcpu=750 -mhard-float -Os -ffreestanding -fno-builtin -nostdlib -msdata=none -G0 '
      '-fno-asynchronous-unwind-tables -ffixed-r2 -ffixed-r13 -fno-stack-protector -mregnames ' + FX).split()
CC = 'powerpc-linux-gnu-gcc'
def run(*a): subprocess.check_call(list(a))

# chargeur
run(CC, *CF, '-fno-pic', '-c', 'loader.c', '-o', 'loader.o')
run(CC, *CF, '-c', 'stub.S', '-o', 'stub.o')
run(CC, *CF, '-static', '-Wl,-T,loader.ld', '-Wl,--no-warn-rwx-segments', '-Wl,--build-id=none',
    '-o', 'loader.elf', 'stub.o', 'loader.o', '-lgcc')
run('powerpc-linux-gnu-objcopy', '-O', 'binary', 'loader.elf', 'loader.bin')
lo = open('loader.bin', 'rb').read()
assert 0x800017A0 + len(lo) <= 0x80003000, len(lo)

# generateur relogeable
run(CC, *CF, '-fPIE', '-c', 'gen.c', '-o', 'gen.o')
run(CC, *CF, '-fPIE', '-pie', '-static-pie', '-Wl,--no-dynamic-linker', '-Wl,-z,norelro', '-Wl,--build-id=none',
    '-Wl,-z,max-page-size=32', '-Wl,-z,common-page-size=32', '-Wl,-e,gen_main', '-Wl,--no-warn-rwx-segments',
    '-o', 'gen.elf', 'gen.o', '-lgcc')
e = ELFFile(open('gen.elf', 'rb'))
segs = [s for s in e.iter_segments() if s['p_type'] == 'PT_LOAD']
size = max(s['p_vaddr'] + s['p_memsz'] for s in segs)
img = bytearray(size)
for s in segs:
    img[s['p_vaddr']:s['p_vaddr'] + s['p_filesz']] = s.data()
rels = []
for sec in e.iter_sections():
    if isinstance(sec, RelocationSection):
        for r in sec.iter_relocations():
            t = r['r_info_type']
            if t == 0: continue
            assert t == 22, 'relocation non geree %d' % t           # R_PPC_RELATIVE
            struct.pack_into('>I', img, r['r_offset'], r['r_addend'])
            rels.append(r['r_offset'])
entry = e.get_section_by_name('.symtab').get_symbol_by_name('gen_main')[0]['st_value']
hdr_len = (24 + 4 * len(rels) + 31) & ~31
hdr = struct.pack('>6I', 0x5747454E, 0, entry, len(rels), size, hdr_len) + b''.join(struct.pack('>I', r) for r in rels)
blob = hdr.ljust(hdr_len, b'\0') + bytes(img)
open('wsrgen.bin', 'wb').write(blob)
print('chargeur %d o, generateur %d o (%d relocations)' % (len(lo), len(blob), len(rels)))
# copie directe vers le dossier de sortie (sinon on deploie un ancien chargeur)
import shutil, os
os.makedirs('/home/user/wsr/out/gen', exist_ok=True)
shutil.copy('loader.bin', '/home/user/wsr/out/gen/loader.bin')
