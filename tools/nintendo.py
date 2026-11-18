"""Decodeurs Nintendo : Yaz0 (compression) et U8 (archive)."""
import struct, os


def yaz0_decompress(data):
    assert data[:4] == b'Yaz0', 'pas du Yaz0'
    size = struct.unpack('>I', data[4:8])[0]
    out = bytearray(size)
    src, dst = 16, 0
    while dst < size:
        code = data[src]; src += 1
        for bit in range(8):
            if dst >= size:
                break
            if code & (0x80 >> bit):
                out[dst] = data[src]; dst += 1; src += 1
            else:
                b1, b2 = data[src], data[src + 1]; src += 2
                dist = ((b1 & 0x0F) << 8 | b2) + 1
                n = b1 >> 4
                if n == 0:
                    n = data[src] + 0x12; src += 1
                else:
                    n += 2
                cp = dst - dist
                for _ in range(n):
                    out[dst] = out[cp]; dst += 1; cp += 1
    return bytes(out)


def u8_list(data):
    """Retourne [(chemin, offset, taille)] pour une archive U8."""
    assert data[:4] == b'\x55\xAA\x38\x2D', 'pas du U8'
    root = struct.unpack('>I', data[4:8])[0]
    nnodes = struct.unpack('>I', data[root + 8:root + 12])[0]
    strtab = root + nnodes * 12
    def name(off):
        e = data.index(b'\x00', strtab + off)
        return data[strtab + off:e].decode('latin1')
    files, stack = [], []
    i = 1
    path = []
    ends = [nnodes]
    while i < nnodes:
        while i >= ends[-1] and len(ends) > 1:
            ends.pop(); path.pop()
        t_name, a, b = struct.unpack('>III', data[root + i * 12:root + i * 12 + 12])
        is_dir = t_name >> 24
        nm = name(t_name & 0xFFFFFF)
        if is_dir:
            path.append(nm); ends.append(b)
        else:
            files.append(('/'.join(path + [nm]), a, b))
        i += 1
    return files


def load_carc(path):
    d = open(path, 'rb').read()
    if d[:4] == b'Yaz0':
        d = yaz0_decompress(d)
    return d


def extract(path, outdir):
    d = load_carc(path)
    for p, off, sz in u8_list(d):
        fp = os.path.join(outdir, p.lstrip('./'))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, 'wb').write(d[off:off + sz])
    return u8_list(d)
