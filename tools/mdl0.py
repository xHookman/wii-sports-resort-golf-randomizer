"""Decodage de la geometrie MDL0 (NW4R g3d, version 11)."""
import struct
from brres import _dict

SECT = ['Links', 'Bones', 'Vertices', 'Normals', 'Colors', 'UVs', 'FurVec', 'FurPos',
        'Materials', 'Shaders', 'Objects', 'Textures', 'Palettes', 'UserData']
FMT = {0: ('B', 1), 1: ('b', 1), 2: ('H', 2), 3: ('h', 2), 4: ('f', 4)}


def _name(d, base, rel):
    s = base + rel
    return d[s:d.index(b'\x00', s)].decode('latin1')


def read_array(d, o, kind):
    """kind : 'pos', 'nrm', 'uv', 'clr'. Retourne (nom, liste de tuples, meta)."""
    size, mdl, doff, noff, idx, comp, fmt = struct.unpack('>IiiiIII', d[o:o + 28])
    name = _name(d, o, noff)
    if kind == 'clr':
        stride, flag, count = struct.unpack('>BBH', d[o + 28:o + 32])
        out = []
        p = o + doff
        for i in range(count):
            q = p + stride * i
            if fmt == 5:   out.append(tuple(d[q:q + 4]))
            elif fmt == 1: out.append(tuple(d[q:q + 3]) + (255,))
            elif fmt == 2: out.append(tuple(d[q:q + 3]) + (255,))
            else:          out.append((255, 255, 255, 255))
        return name, out, dict(fmt=fmt, comp=comp, stride=stride, idx=idx)
    div, stride, count = struct.unpack('>BBH', d[o + 28:o + 32])
    if kind == 'pos':  n = 3 if comp == 1 else 2
    elif kind == 'nrm': n = 3
    else: n = 2 if comp == 1 else 1
    c, sz = FMT[fmt]
    scale = 1.0 if fmt == 4 else float(1 << div)
    out = []
    p = o + doff
    for i in range(count):
        v = struct.unpack('>' + c * n, d[p + stride * i:p + stride * i + sz * n])
        out.append(tuple(x / scale for x in v))
    return name, out, dict(fmt=fmt, comp=comp, div=div, stride=stride, idx=idx, hdr=o)


def read_links(d, o):
    """Retourne la liste (materiau, objet, os) depuis le bytecode DrawOpa/DrawXlu."""
    draws = []
    p = o
    while True:
        op = d[p]
        if op == 0x01: break
        if op == 0x04:   # Draw : mat, obj, bone, prio
            mat, obj, bone = struct.unpack('>HHH', d[p + 1:p + 7]); draws.append((mat, obj, bone)); p += 8
        elif op == 0x02: p += 5
        elif op == 0x03: p += 1 + 2 + 1 + 6 * d[p + 3] if False else 1 + 2 + 1; break
        elif op in (0x05, 0x06): p += 5
        else: break
    return draws


def read_polygon(d, o, arrays):
    hdr = struct.unpack('>IiiIIIIIiIIiII', d[o:o + 0x38])
    size, mdl, node, vcd_lo, vcd_hi = hdr[0:5]
    dl_size = hdr[9]; dl_off = o + 0x24 + hdr[11]
    name = _name(d, o, struct.unpack('>i', d[o + 0x38:o + 0x3C])[0])
    nverts, nfaces = struct.unpack('>II', d[o + 0x40:o + 0x48])
    ids = struct.unpack('>hhhh8h', d[o + 0x48:o + 0x60])
    # descripteur de sommets
    attrs = []
    if vcd_lo & 1: attrs.append(('pnm', 1))
    for t in range(8):
        if vcd_lo >> (1 + t) & 1: attrs.append(('tm%d' % t, 1))
    def kind(v): return {0: 0, 1: 1, 2: 1, 3: 2}[v]
    for nm, sh in [('pos', 9), ('nrm', 11), ('clr0', 13), ('clr1', 15)]:
        v = vcd_lo >> sh & 3
        if v: attrs.append((nm, 1 if v == 2 else 2 if v == 3 else -1))
    for t in range(8):
        v = vcd_hi >> (2 * t) & 3
        if v: attrs.append(('uv%d' % t, 1 if v == 2 else 2 if v == 3 else -1))
    tris = []   # liste de triangles, chaque sommet = dict attribut -> index
    p = dl_off; end = dl_off + dl_size
    while p < end:
        cmd = d[p]; p += 1
        if cmd == 0: continue
        if cmd & 0xF8 not in (0x90, 0x98, 0xA0, 0x80):
            break
        prim = cmd & 0xF8
        cnt = struct.unpack('>H', d[p:p + 2])[0]; p += 2
        vs = []
        for _ in range(cnt):
            v = {}
            for nm, w in attrs:
                if w == 1: v[nm] = d[p]; p += 1
                elif w == 2: v[nm] = struct.unpack('>H', d[p:p + 2])[0]; p += 2
                else: raise ValueError('attribut direct non gere')
            vs.append(v)
        if prim == 0x90:
            tris += [vs[i:i + 3] for i in range(0, cnt - 2, 3)]
        elif prim == 0x98:
            for i in range(cnt - 2):
                tris.append([vs[i], vs[i + 1], vs[i + 2]] if i % 2 == 0 else [vs[i + 1], vs[i], vs[i + 2]])
        elif prim == 0xA0:
            tris += [[vs[0], vs[i], vs[i + 1]] for i in range(1, cnt - 1)]
        elif prim == 0x80:
            for i in range(0, cnt, 4):
                tris += [[vs[i], vs[i + 1], vs[i + 2]], [vs[i], vs[i + 2], vs[i + 3]]]
    return dict(name=name, vcd=(vcd_lo, vcd_hi), attrs=attrs, ids=ids, tris=tris,
                nverts=nverts, nfaces=nfaces, hdr=o, dl=(dl_off, dl_size))


def read_mdl0(d, mo):
    secs = struct.unpack('>14i', d[mo + 16:mo + 16 + 56])
    S = {nm: (_dict(d, mo + so) if so else []) for nm, so in zip(SECT, secs)}
    arr = {}
    for nm, kind in [('Vertices', 'pos'), ('Normals', 'nrm'), ('Colors', 'clr'), ('UVs', 'uv')]:
        arr[kind] = [read_array(d, o, kind) for _, o in S[nm]]
    polys = [read_polygon(d, o, arr) for _, o in S['Objects']]
    links = {n: read_links(d, o) for n, o in S['Links'] if n.startswith('Draw')}
    mats = [n for n, _ in S['Materials']]
    return dict(secs=S, arr=arr, polys=polys, links=links, mats=mats)
