import struct
def read_pmp(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'PMPF'
    n = struct.unpack('>H', d[0x10:0x12])[0]
    objs = []
    for i in range(n):
        o = 0x80 + i * 88
        grp, typ = struct.unpack('>HH', d[o:o + 4])
        pos = struct.unpack('>3f', d[o + 8:o + 20])
        scl = struct.unpack('>3f', d[o + 20:o + 32])
        rot = struct.unpack('>9f', d[o + 32:o + 68])
        par = struct.unpack('>5I', d[o + 68:o + 88])
        objs.append(dict(i=i, grp=grp, typ=typ, pos=pos, scl=scl, rot=rot, par=par))
    return objs
