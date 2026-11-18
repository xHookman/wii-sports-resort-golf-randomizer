"""Ecriture de collision KCL (format Nintendo, conventions verifiees sur Wii Sports Resort)."""
import struct, math


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _norm(a):
    l = math.sqrt(_dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-12 else None


def _tri_box(A, B, C, lo, size, margin):
    """Test conservatif boite englobante du triangle / cube (avec marge)."""
    for i in range(3):
        mn = min(A[i], B[i], C[i]) - margin; mx = max(A[i], B[i], C[i]) + margin
        if mx < lo[i] or mn > lo[i] + size: return False
    return True


def _rebuild_ok(A, B, C, h, fn, e1, e2, e3, tol=2.0):
    """Le jeu reconstruit B et C a partir de A, des normales (float32) et de la hauteur : verifier que ca tient."""
    f32 = lambda v: tuple(struct.unpack('>3f', struct.pack('>3f', *(round(c, 6) for c in v))))
    fn, e1, e2, e3 = f32(fn), f32(e1), f32(e2), f32(e3)
    cA = _cross(e1, fn); cB = _cross(e2, fn)
    dB = _dot(cB, e3); dC = _dot(cA, e3)
    if abs(dB) < 1e-4 or abs(dC) < 1e-4: return False
    B2 = tuple(A[i] + cB[i] * h / dB for i in range(3)); C2 = tuple(A[i] + cA[i] * h / dC for i in range(3))
    return max(abs(B2[i] - B[i]) for i in range(3)) < tol and max(abs(C2[i] - C[i]) for i in range(3)) < tol


def write_kcl(tris, thickness=5.0, radius=2.5, max_tris=24, min_size=128):
    """tris : liste de (A, B, C, attribut). Retourne les octets du fichier."""
    verts, vmap, nrms, nmap = [], {}, [], {}
    def vid(p):
        k = tuple(round(c, 3) for c in p)
        if k not in vmap: vmap[k] = len(verts); verts.append(k)
        return vmap[k]
    def nid(n):
        k = tuple(round(c, 6) for c in n)
        if k not in nmap: nmap[k] = len(nrms); nrms.append(k)
        return nmap[k]

    prisms, geo = [], []
    for A, B, C, attr in tris:
        fn = _norm(_cross(_sub(B, A), _sub(C, A)))
        if fn is None: continue                      # triangle degenere
        e1 = _norm(_cross(fn, _sub(C, A)))
        e2 = _norm(_cross(_sub(B, A), fn))
        e3 = _norm(_cross(_sub(C, B), fn))
        if not (e1 and e2 and e3): continue
        h = _dot(_sub(B, A), e3)
        if h <= 0: continue
        if not _rebuild_ok(A, B, C, h, fn, e1, e2, e3): continue      # triangle trop fin : sommets non reconstructibles
        prisms.append((h, vid(A), nid(fn), nid(e1), nid(e2), nid(e3), attr))
        geo.append((A, B, C))

    # ---- octree
    mn = [min(min(t[0][i], t[1][i], t[2][i]) for t in geo) - 50.0 for i in range(3)]
    mx = [max(max(t[0][i], t[1][i], t[2][i]) for t in geo) + 50.0 for i in range(3)]
    ext = [mx[i] - mn[i] for i in range(3)]
    smallest = min(ext)
    shift = max(int(math.floor(math.log2(max(smallest, 1)))), int(math.log2(min_size)))
    cube = 1 << shift
    wbits = [max(shift, int(math.ceil(math.log2(max(e, 1))))) for e in ext]
    n = [1 << (wbits[i] - shift) for i in range(3)]
    masks = [(~((1 << wbits[i]) - 1)) & 0xFFFFFFFF for i in range(3)]
    xshift = int(math.log2(n[0])); xyshift = int(math.log2(n[0] * n[1]))
    margin = radius + 1.0

    import numpy as _np
    _G = _np.array(geo, dtype=_np.float64)              # (n, 3 sommets, 3)
    _TMN = _G.min(axis=1) - margin; _TMX = _G.max(axis=1) + margin
    def build(lo, size, cand):
        if len(cand):
            lo_ = _np.array(lo); hi_ = lo_ + size
            ok = _np.all((_TMX[cand] >= lo_) & (_TMN[cand] <= hi_), axis=1)
            inside = cand[ok]
        else:
            inside = cand
        if len(inside) <= max_tris or size <= min_size:
            return ('leaf', tuple(int(i) for i in inside))
        h2 = size / 2
        kids = []
        for ci in range(8):
            o = (lo[0] + (ci & 1) * h2, lo[1] + (ci >> 1 & 1) * h2, lo[2] + (ci >> 2 & 1) * h2)
            kids.append(build(o, h2, inside))
        return ('node', kids)

    roots = _native_roots(_TMN, _TMX, mn, cube, n, max_tris, min_size)
    if roots is None:
        allidx = _np.arange(len(geo))
        roots = []
        for z in range(n[2]):
            for y in range(n[1]):
                for x in range(n[0]):
                    lo = (mn[0] + x * cube, mn[1] + y * cube, mn[2] + z * cube)
                    roots.append(build(lo, cube, allidx))

    # serialisation : chaque groupe de noeuds = tableau de u32 ; feuilles -> listes u16
    out_nodes = bytearray()
    pending = []      # (position dans out_nodes, base du groupe, noeud)
    def emit_group(nodes):
        base = len(out_nodes)
        out_nodes.extend(b'\x00' * 4 * len(nodes))
        for i, nd in enumerate(nodes): pending.append((base + 4 * i, base, nd))
        return base
    emit_group(roots)
    leaf_refs = []    # (position, base, tuple)
    while pending:
        pos, base, nd = pending.pop(0)
        if nd[0] == 'node':
            g = emit_group(nd[1])
            struct.pack_into('>I', out_nodes, pos, g - base)
        else:
            leaf_refs.append((pos, base, nd[1]))
    # listes de triangles (partagees si identiques)
    list_bytes = bytearray()
    list_off = {}
    for pos, base, tup in leaf_refs:
        if tup not in list_off:
            list_off[tup] = len(list_bytes)
            list_bytes.extend(struct.pack('>H', 0))       # l'offset pointe 2 octets avant
            list_bytes.extend(struct.pack('>%dH' % len(tup), *[i + 1 for i in tup]))
        # le 0 final est le 0 de debut de la liste suivante ; on ajoute un 0 final global
    list_bytes.extend(b'\x00\x00')
    nodes_len = len(out_nodes)
    for pos, base, tup in leaf_refs:
        struct.pack_into('>I', out_nodes, pos, 0x80000000 | (nodes_len + list_off[tup] - base))
    # NB : chaque liste se termine par le 0 qui ouvre la suivante, ou le 0 final.

    # ---- assemblage
    hdr_size = 0x3C
    pos_o = hdr_size
    pos_b = b''.join(struct.pack('>3f', *v) for v in verts)
    nrm_o = pos_o + len(pos_b)
    nrm_b = b''.join(struct.pack('>3f', *v) for v in nrms)
    pri_first = nrm_o + len(nrm_b)
    pri_b = b''.join(struct.pack('>f6H', *p) for p in prisms)
    blk_o = pri_first + len(pri_b)
    hdr = struct.pack('>4If3f3I3If', pos_o, nrm_o, pri_first - 0x10, blk_o, thickness,
                      mn[0], mn[1], mn[2], masks[0], masks[1], masks[2], shift, xshift, xyshift, radius)
    data = hdr + pos_b + nrm_b + pri_b + bytes(out_nodes) + bytes(list_bytes)
    while len(data) % 4: data += b'\x00'
    return data


def query(raw, p):
    """Liste des prismes (index 1..n) du cube contenant p, comme le ferait le jeu."""
    h = struct.unpack('>4If3f3I3If', raw[:0x3C])
    blk = h[3]; mn = h[5:8]; masks = h[8:11]; shift = h[11]; xs, xys = h[12], h[13]
    x, y, z = (int(p[i] - mn[i]) for i in range(3))
    if x < 0 or y < 0 or z < 0 or x & masks[0] or y & masks[1] or z & masks[2]:
        return None
    node = blk
    off = node + 4 * (((z >> shift) << xys) | ((y >> shift) << xs) | (x >> shift))
    while True:
        v = struct.unpack('>I', raw[off:off + 4])[0]
        if v & 0x80000000:
            lp = node + (v & 0x7FFFFFFF) + 2; out = []
            while True:
                i = struct.unpack('>H', raw[lp:lp + 2])[0]
                if i == 0: return out
                out.append(i); lp += 2
        node = node + v
        shift -= 1
        off = node + 4 * (((z >> shift & 1) << 2) | ((y >> shift & 1) << 1) | (x >> shift & 1))


import ctypes as _ct, os as _os
try:
    _OT = _ct.CDLL(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'native', 'liboctree.so'))
    _OT.octree.restype = _ct.c_long
    _OT.octree.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_int, _ct.c_void_p, _ct.c_double, _ct.c_void_p,
                           _ct.c_int, _ct.c_double, _ct.POINTER(_ct.POINTER(_ct.c_int))]
    _OT.octree_free.argtypes = [_ct.c_void_p]
except OSError:
    _OT = None


def _native_roots(tmn, tmx, mn, cube, n, max_tris, min_size):
    """Meme arbre que build() en Python, calcule en C (liboctree.so)."""
    if _OT is None: return None
    import numpy as np
    tmn = np.ascontiguousarray(tmn, np.float64); tmx = np.ascontiguousarray(tmx, np.float64)
    mn_ = np.array(mn, np.float64); n_ = np.array(n, np.int32)
    p = _ct.POINTER(_ct.c_int)()
    cnt = _OT.octree(tmn.ctypes.data, tmx.ctypes.data, len(tmn), mn_.ctypes.data, float(cube), n_.ctypes.data,
                     max_tris, float(min_size), _ct.byref(p))
    flat = np.ctypeslib.as_array(p, (cnt,)).tolist() if cnt else []
    _OT.octree_free(p)
    pos = 0
    def rd():
        nonlocal pos
        v = flat[pos]; pos += 1
        if v < 0: return ('node', [rd() for _ in range(8)])
        t = tuple(flat[pos:pos + v]); pos += v
        return ('leaf', t)
    return [rd() for _ in range(n[0] * n[1] * n[2])]
