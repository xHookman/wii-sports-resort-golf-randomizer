import struct
def read_kcl(path):
    d = open(path, 'rb').read()
    h = struct.unpack('>4If3f3I3If', d[:0x3C])
    pos_o, nrm_o, pri_o, blk_o = h[0:4]
    thick = h[4]; mn = h[5:8]
    # prismes : indexes a partir de 1, le tableau commence a pri_o + 0x10
    n = (blk_o - (pri_o + 0x10)) // 0x10
    verts = [struct.unpack('>3f', d[pos_o + 12 * i: pos_o + 12 * i + 12]) for i in range((nrm_o - pos_o) // 12)]
    nrms = [struct.unpack('>3f', d[nrm_o + 12 * i: nrm_o + 12 * i + 12]) for i in range((pri_o + 0x10 - nrm_o) // 12)]
    prisms = []
    for i in range(n):
        o = pri_o + 0x10 + 0x10 * i
        hgt, pi, fn, e1, e2, e3, attr = struct.unpack('>f6H', d[o:o + 0x10])
        prisms.append((hgt, pi, fn, e1, e2, e3, attr))
    return dict(header=h, verts=verts, nrms=nrms, prisms=prisms, raw=d)
