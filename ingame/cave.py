"""Petit crochet PowerPC : choisit au hasard une variante pre-generee du trou au moment du chargement.
glf_course_%s.carc  ->  glf_course_%s_%d.carc  (d = (temps machine >> 16) modulo N : ~1 ms par pas ; le modulo direct ne donnait que 4 valeurs, l'entree etant lue a chaque image) pour les trous du pool."""
import struct

def D(op, rt, ra, imm): return (op << 26) | (rt << 21) | (ra << 16) | (imm & 0xffff)
def X(rt, ra, rb, xo, rc=0): return (31 << 26) | (rt << 21) | (ra << 16) | (rb << 11) | (xo << 1) | rc
def lis(rt, v): return D(15, rt, 0, v)
def ori(ra, rs, v): return D(24, rs, ra, v)
def li(rt, v): return D(14, rt, 0, v)
def addi(rt, ra, v): return D(14, rt, ra, v)
def lbz(rt, ra, d): return D(34, rt, ra, d)
def cmpwi(ra, v): return D(11, 0, ra, v)
def lbzx(rt, ra, rb): return X(rt, ra, rb, 87)
def cmpw(ra, rb): return X(0, ra, rb, 0)
def divwu(rt, ra, rb): return X(rt, ra, rb, 459)
def mullw(rt, ra, rb): return X(rt, ra, rb, 235)
def subf(rt, ra, rb): return X(rt, ra, rb, 40)       # rt = rb - ra
def mftb(rt): return (31 << 26) | (rt << 21) | (12 << 16) | (8 << 11) | (371 << 1)
def rlwinm(ra, rs, sh, mb, me): return (21 << 26) | (rs << 21) | (ra << 16) | (sh << 11) | (mb << 6) | (me << 1)
def b(frm, to, lk=0): return (18 << 26) | ((to - frm) & 0x3fffffc) | lk
def bc(frm, to, bo, bi): return (16 << 26) | (bo << 21) | (bi << 16) | ((to - frm) & 0xfffc)
def beq(frm, to): return bc(frm, to, 12, 2)
def bne(frm, to): return bc(frm, to, 4, 2)
CRCLR6 = 0x4CC63182
def mftbu(rt): return (31 << 26) | (rt << 21) | (13 << 16) | (8 << 11) | (371 << 1)
def cmplwi(ra, v): return (10 << 26) | (ra << 16) | (v & 0xffff)
def ble(frm, to): return bc(frm, to, 4, 1)
def lwz(rt, ra, d): return D(32, rt, ra, d)
def stw(rs, ra, d): return D(36, rs, ra, d)
def add(rt, ra, rb): return X(rt, ra, rb, 266)
STATE = 0x80002FF0      # miroir par partie : +0 sens (0/1), +4 dernier chargement (registre TBU, ~70 s par pas)
SNPRINTF = 0x8000d074
CALL_SITE = 0x801ffebc
CODE_AT, DATA_AT = 0x80004490, 0x80002E00   # code : trou de zeros 0x80004484-0x80004580 ; table des noms : memoire basse libre
                                              # 0x80001F80-0x80003000 (apres le chargeur, avant les journaux) : 18 trous

def build(code_at, data_at, names, n, mirror=False):
    newfmt = data_at
    names_at = data_at + 32
    prog = []
    a = code_at
    lab = {}
    # passe 1 : adresses des etiquettes (taille fixe de chaque instruction)
    seq = ['lis9', 'ori9', 'L:loop', 'lbz10', 'cmp0', 'beq_nomatch', 'li11', 'L:cmp', 'lbzx12', 'lbzx10', 'cmpw', 'bne_next',
           'cmpz', 'beq_match', 'addi11', 'b_cmp', 'L:next', 'addi9', 'b_loop', 'L:match']
    if mirror:
        # nouvelle partie si le dernier chargement date de plus de 8 x 70 s : sens tire au hasard et memorise ;
        # variantes 0..n/2-1 normales, n/2..n-1 en miroir
        seq += ['tbu7', 'lisS', 'oriS', 'lwzlast', 'subdt', 'cmp8', 'ble_same', 'mftb0', 'bit0', 'stwM', 'L:same', 'stwlast']
    seq += ['mftb', 'srwi', 'li0', 'divwu', 'mullw', 'subf']
    if mirror: seq += ['lwzM', 'slwM', 'addM']
    seq += ['lis5', 'ori5', 'L:nomatch', 'crclr', 'b_snprintf']
    nn = n // 2 if mirror else n
    pc = code_at
    for s in seq:
        if s.startswith('L:'): lab[s[2:]] = pc
        else: pc += 4
    pc = code_at; out = []
    for s in seq:
        if s.startswith('L:'): continue
        w = {'lis9': lis(9, names_at >> 16), 'ori9': ori(9, 9, names_at & 0xffff), 'lbz10': lbz(10, 9, 0),
             'cmp0': cmpwi(10, 0), 'beq_nomatch': beq(pc, lab['nomatch']), 'li11': li(11, 0),
             'lbzx12': lbzx(12, 6, 11), 'lbzx10': lbzx(10, 9, 11), 'cmpw': cmpw(12, 10), 'bne_next': bne(pc, lab['next']),
             'cmpz': cmpwi(12, 0), 'beq_match': beq(pc, lab['match']), 'addi11': addi(11, 11, 1), 'b_cmp': b(pc, lab['cmp']),
             'addi9': addi(9, 9, 8), 'b_loop': b(pc, lab['loop']), 'mftb': mftb(7), 'srwi': rlwinm(7, 7, 16, 16, 31), 'li0': li(0, nn),
             'tbu7': mftbu(7), 'lisS': lis(9, STATE >> 16), 'oriS': ori(9, 9, STATE & 0xffff), 'lwzlast': lwz(0, 9, 4),
             'subdt': subf(0, 0, 7), 'cmp8': cmplwi(0, 8), 'ble_same': ble(pc, lab.get('same', pc)), 'mftb0': mftb(0),
             'bit0': rlwinm(0, 0, 16, 31, 31), 'stwM': stw(0, 9, 0), 'stwlast': stw(7, 9, 4),
             'lwzM': lwz(0, 9, 0), 'slwM': rlwinm(0, 0, {16: 3, 8: 2, 4: 1}.get(n, 3), 0, 31 - {16: 3, 8: 2, 4: 1}.get(n, 3)), 'addM': add(7, 7, 0),
             'divwu': divwu(8, 7, 0), 'mullw': mullw(8, 8, 0), 'subf': subf(7, 8, 7),
             'lis5': lis(5, newfmt >> 16), 'ori5': ori(5, 5, newfmt & 0xffff), 'crclr': CRCLR6,
             'b_snprintf': b(pc, SNPRINTF)}[s]
        out.append(w); pc += 4
    code = b''.join(struct.pack('>I', w) for w in out)
    data = b'glf_course_%s_%d.carc'.ljust(32, b'\0')
    for nm in names: data += nm.encode().ljust(8, b'\0')
    data += b'\0' * 8
    hook = struct.pack('>I', b(CALL_SITE, code_at, 1))
    return code, data, hook

if __name__ == '__main__':
    code, data, hook = build(CODE_AT, DATA_AT, ['fcJP11', 'fcJP6', 'fcJP12'], 8)
    print(len(code), len(data), code.hex(), data.hex(), hook.hex())
