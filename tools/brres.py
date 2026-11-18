import struct
def _dict(d, off):
    size, n = struct.unpack('>II', d[off:off+8]); out = []
    for i in range(1, n + 1):
        e = off + 8 + 16 * i
        _, _, _, _, noff, doff = struct.unpack('>HHHHII', d[e:e+16])
        s = off + noff; name = d[s:d.index(b'\x00', s)].decode('latin1')
        out.append((name, off + doff))
    return out
def brres_tree(d):
    assert d[:4] == b'bres'
    root = struct.unpack('>H', d[0xC:0xE])[0]
    tree = {}
    for gname, goff in _dict(d, root + 8):
        tree[gname] = [(n, o, d[o:o+4].decode('latin1')) for n, o in _dict(d, goff)]
    return tree
def mdl0_info(d, o):
    # sections du MDL0 v11 : nombre de sommets / faces dans l'en-tete info
    ver = struct.unpack('>I', d[o+8:o+12])[0]
    nsec = {8: 11, 9: 11, 10: 14, 11: 14}.get(ver, 14)
    secs = struct.unpack('>%di' % nsec, d[o+16:o+16+4*nsec])
    info = o + 16 + 4*nsec + 4
    nv, nf = struct.unpack('>II', d[info+0x14:info+0x1C])
    names = ['Links','Bones','Vertices','Normals','Colors','UVs','FurVec','FurPos','Materials','Shaders','Objects','Textures','Palettes','UserData'][:nsec]
    groups = {}
    for nm, so in zip(names, secs):
        if so: groups[nm] = [n for n, _ in _dict(d, o + so)]
    return ver, nv, nf, groups
