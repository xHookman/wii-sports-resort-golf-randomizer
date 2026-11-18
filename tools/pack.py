"""Ecriture d'archives U8, compression Yaz0 et ecriture PMP."""
import struct


def u8_build(entries):
    """entries : liste ordonnee de (chemin, octets). Les dossiers sont crees dans l'ordre."""
    nodes = [['d', '', 0, 0]]        # type, nom, a, b (b du dossier fixe a la fin)
    files = []
    dir_index = {'': 0}
    for path, data in entries:
        parts = path.split('/')
        cur = ''
        for i, part in enumerate(parts[:-1]):
            nxt = part if not cur else cur + '/' + part
            if nxt not in dir_index:
                dir_index[nxt] = len(nodes)
                nodes.append(['d', part, dir_index[cur], 0])
            cur = nxt
        nodes.append(['f', parts[-1], 0, len(data)])
        files.append((len(nodes) - 1, data))
    # recalcul robuste : un dossier se termine au premier noeud qui n'est pas son descendant
    parent = {}
    cur_dirs = [0]
    for i, n in enumerate(nodes):
        if i == 0: continue
        if n[0] == 'd':
            while cur_dirs[-1] != n[2]: cur_dirs.pop()
            parent[i] = n[2]; cur_dirs.append(i)
        else:
            parent[i] = cur_dirs[-1]
    def is_desc(j, i):
        while j in parent:
            j = parent[j]
            if j == i: return True
        return False
    for i, n in enumerate(nodes):
        if n[0] == 'd':
            j = i + 1
            while j < len(nodes) and is_desc(j, i): j += 1
            n[3] = j if i else len(nodes)
    # chaine de noms
    names = bytearray()
    noff = []
    for n in nodes:
        noff.append(len(names)); names.extend(n[1].encode('latin1') + b'\x00')
    node_size = 12 * len(nodes) + len(names)
    data_off = (0x20 + node_size + 0x1F) & ~0x1F
    blob = bytearray()
    foff = {}
    for idx, data in files:
        while (data_off + len(blob)) % 32: blob.append(0)
        foff[idx] = data_off + len(blob); blob.extend(data)
    out = bytearray(struct.pack('>IIII', 0x55AA382D, 0x20, node_size, data_off) + b'\x00' * 16)
    for i, n in enumerate(nodes):
        if n[0] == 'd':
            out += struct.pack('>III', (1 << 24) | noff[i], n[2], n[3])
        else:
            out += struct.pack('>III', noff[i], foff[i], n[3])
    out += names
    while len(out) < data_off: out.append(0)
    out += blob
    return bytes(out)


import ctypes as _ct, os as _os
_lib = None
try:
    _lib = _ct.CDLL(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'native', 'libyaz0.so'))
    _lib.yaz0_compress.restype = _ct.c_size_t
except OSError:
    _lib = None


def yaz0_compress(src):
    """Version C si disponible (native/libyaz0.so), sinon la version Python."""
    if _lib is not None:
        src = bytes(src); buf = _ct.create_string_buffer(len(src) + len(src) // 8 + 64)
        m = _lib.yaz0_compress(src, len(src), buf)
        return buf.raw[:m]
    return _yaz0_compress_py(src)


def _native_yaz0(): return _lib is not None


def _yaz0_compress_py(src):
    n = len(src)
    out = bytearray(b'Yaz0' + struct.pack('>I', n) + b'\x00' * 8)
    table = {}
    i = 0
    while i < n:
        flag_pos = len(out); out.append(0); flags = 0
        for bit in range(8):
            if i >= n: break
            best_len = 0; best_pos = 0
            if i + 3 <= n:
                key = src[i:i + 3]
                cands = table.get(key)
                if cands:
                    lim = min(0x111, n - i)
                    for p in reversed(cands[-24:]):
                        if i - p > 0x1000: break
                        l = 3
                        while l < lim and src[p + l] == src[i + l]: l += 1
                        if l > best_len:
                            best_len, best_pos = l, p
                            if l == lim: break
            if best_len >= 3:
                dist = i - best_pos - 1
                if best_len >= 0x12:
                    out += bytes([(dist >> 8) & 0x0F, dist & 0xFF, best_len - 0x12])
                else:
                    out += bytes([((best_len - 2) << 4) | ((dist >> 8) & 0x0F), dist & 0xFF])
                for k in range(best_len):
                    if i + k + 3 <= n:
                        table.setdefault(src[i + k:i + k + 3], []).append(i + k)
                i += best_len
            else:
                flags |= 0x80 >> bit
                out.append(src[i])
                if i + 3 <= n: table.setdefault(src[i:i + 3], []).append(i)
                i += 1
        out[flag_pos] = flags
    return bytes(out)


def write_pmp(header, objs):
    """header : 0x80 premiers octets d'un PMP original. objs : liste de dict (cf. pmp.read_pmp)."""
    h = bytearray(header[:0x80])
    struct.pack_into('>H', h, 0x10, len(objs))
    total = 0x80 + 88 * len(objs)
    struct.pack_into('>II', h, 0x44, total, total)      # tailles (= taille du fichier)
    out = bytearray(h)
    for o in objs:
        out += struct.pack('>HHI', o['grp'], o['typ'], 0)
        out += struct.pack('>3f', *o['pos']) + struct.pack('>3f', *o['scl']) + struct.pack('>9f', *o['rot'])
        out += struct.pack('>5I', *o['par'])
    return bytes(out)
