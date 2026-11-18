"""Cameras SCN0 (v5) des trous de golf : lecture des pistes animees et reecriture
sur place (meme taille de bloc), en redistribuant les cles entre les pistes."""
import struct
import numpy as np

FIELDS = ['posX', 'posY', 'posZ', 'aspect', 'near', 'far', 'rotX', 'rotY', 'rotZ',
          'aimX', 'aimY', 'aimZ', 'twist', 'fovY', 'ortho']
ANIM = ['posX', 'posY', 'posZ', 'aimX', 'aimY', 'aimZ']


def _cam_base(blk):
    return struct.unpack('>I', blk[0x24:0x28])[0]          # premiere camera


def read_cam(blk):
    """-> (nframes, {champ: liste de cles (frame, valeur, tangente)}, offsets des pistes)"""
    nfr = struct.unpack('>H', blk[0x34:0x36])[0]
    cb = _cam_base(blk); fb = cb + 0x20
    tracks, where = {}, {}
    for i, nm in enumerate(FIELDS):
        if nm not in ANIM: continue
        fa = fb + 4 * i
        off = struct.unpack('>i', blk[fa:fa + 4])[0]
        to = fa + off
        if not (0 < off < len(blk) and to + 8 <= len(blk) and off % 4 == 0 and blk[to + 2:to + 4] == b'\0\0'):
            v = struct.unpack('>f', blk[fa:fa + 4])[0]          # valeur constante
            tracks[nm] = [(0.0, v, 0.0)]; where[nm] = (fa, None, 0)
            continue
        n = struct.unpack('>H', blk[to:to + 2])[0]
        keys = [struct.unpack('>3f', blk[to + 8 + 12 * k: to + 20 + 12 * k]) for k in range(n)]
        tracks[nm] = keys; where[nm] = (fa, to, n)
    return nfr, tracks, where


def hermite(keys, f):
    if f <= keys[0][0]: return keys[0][1]
    if f >= keys[-1][0]: return keys[-1][1]
    for (f0, v0, t0), (f1, v1, t1) in zip(keys, keys[1:]):
        if f0 <= f <= f1:
            d = f1 - f0
            if d <= 0: return v1
            s = (f - f0) / d
            h00 = 2 * s ** 3 - 3 * s ** 2 + 1; h10 = s ** 3 - 2 * s ** 2 + s
            h01 = -2 * s ** 3 + 3 * s ** 2; h11 = s ** 3 - s ** 2
            return h00 * v0 + h10 * d * t0 + h01 * v1 + h11 * d * t1
    return keys[-1][1]


def _tangents(f, v):
    t = np.zeros(len(f))
    for i in range(len(f)):
        a, b = max(0, i - 1), min(len(f) - 1, i + 1)
        t[i] = (v[b] - v[a]) / (f[b] - f[a]) if f[b] != f[a] else 0.0
    return t


def _tangents_np(f, v):
    n = len(f); a = np.maximum(np.arange(n) - 1, 0); b = np.minimum(np.arange(n) + 1, n - 1)
    df = f[b] - f[a]
    return np.where(df != 0, (v[b] - v[a]) / np.where(df != 0, df, 1), 0.0)


def _herm_np(f, v, t, x):
    """Hermite vectorise (memes conventions que hermite) aux instants x."""
    seg = np.clip(np.searchsorted(f, x, side='right') - 1, 0, len(f) - 2)
    f0, f1 = f[seg], f[seg + 1]; d = f1 - f0
    s = np.where(d > 0, (x - f0) / np.where(d > 0, d, 1), 1.0)
    s2 = s * s; s3 = s2 * s
    y = (2 * s3 - 3 * s2 + 1) * v[seg] + (s3 - 2 * s2 + s) * d * t[seg] + (-2 * s3 + 3 * s2) * v[seg + 1] + (s3 - s2) * d * t[seg + 1]
    y = np.where(x <= f[0], v[0], y)
    return np.where(x >= f[-1], v[-1], y)


import ctypes as _ct, os as _os
try:
    _FK = _ct.CDLL(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'native', 'libfitkeys.so'))
    _FK.fit_keys.restype = _ct.c_int
    _FK.fit_keys.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_int, _ct.c_int, _ct.c_void_p]
except OSError:
    _FK = None


def fit_keys(frames, vals, count):
    """Reduit une courbe echantillonnee a `count` cles Hermite ; tangentes de type
    Catmull-Rom calculees entre les cles retenues (pas de depassement).
    Retrait glouton de la cle qui degrade le moins l'erreur max ; l'effet d'un retrait est local
    (fenetre de 2 cles de chaque cote), le reste de l'erreur vient d'un cache par segment."""
    frames = np.asarray(frames, float); vals = np.asarray(vals, float)
    idx = list(range(len(frames)))
    if _FK is not None and len(frames) > max(2, count):
        F_ = np.ascontiguousarray(frames); V_ = np.ascontiguousarray(vals); out = np.zeros(len(frames), np.int32)
        m = _FK.fit_keys(F_.ctypes.data, V_.ctypes.data, len(frames), count, out.ctypes.data)
        idx = [int(i) for i in out[:m]]
    def keys_of(ii):
        f = frames[ii]; v = vals[ii]; t = _tangents(f, v)
        return [(f[k], v[k], t[k]) for k in range(len(ii))]
    def seg_errors(ii):
        ii = np.asarray(ii); f = frames[ii]; v = vals[ii]
        e = np.abs(_herm_np(f, v, _tangents_np(f, v), frames) - vals)
        seg = np.clip(np.searchsorted(ii, np.arange(len(frames)), side='right') - 1, 0, len(ii) - 2)
        out = np.zeros(len(ii) - 1); np.maximum.at(out, seg, e)
        return out
    while len(idx) > max(2, count):
        se = seg_errors(idx); m = len(idx)
        pre = np.maximum.accumulate(se); suf = np.maximum.accumulate(se[::-1])[::-1]
        best = None
        for j in range(1, m - 1):
            lo, hi = max(0, j - 2), min(m - 1, j + 2)          # cles bornant la zone modifiee
            klo, khi = max(0, j - 3), min(m - 1, j + 3)        # cles utiles au calcul des tangentes
            sub = [idx[k] for k in range(klo, khi + 1) if k != j]
            f = frames[sub]; v = vals[sub]; t = _tangents_np(f, v)
            a, b = idx[lo], idx[hi]
            x = frames[a:b + 1]
            e = float(np.max(np.abs(_herm_np(f, v, t, x) - vals[a:b + 1])))
            if lo > 0: e = max(e, pre[lo - 1])
            if hi < m - 1: e = max(e, suf[hi])
            if best is None or e < best[0]: best = (e, j)
        idx.pop(best[1])
    return keys_of(idx)


def write_cam(blk, new_tracks):
    """new_tracks : {champ: cles}. Le nombre total de cles doit etre <= l'original ;
    les pistes sont re-empilees dans la zone d'origine."""
    b = bytearray(blk)
    nfr, tracks, where = read_cam(bytes(blk))
    anim = [nm for nm in ANIM if where[nm][1] is not None]
    start = min(where[nm][1] for nm in anim)
    end = max(where[nm][1] + 8 + 12 * where[nm][2] for nm in anim)
    scale = struct.unpack('>f', blk[start + 4:start + 8])[0]
    need = sum(8 + 12 * len(new_tracks[nm]) for nm in anim)
    assert need <= end - start, (need, end - start)
    pos = start
    for nm in ANIM:
        fa = where[nm][0]; keys = new_tracks[nm]
        if where[nm][1] is None:
            struct.pack_into('>f', b, fa, float(np.mean([k[1] for k in keys]))); continue
        struct.pack_into('>i', b, fa, pos - fa)
        struct.pack_into('>HHf', b, pos, len(keys), 0, scale)
        for k, (f, v, t) in enumerate(keys):
            struct.pack_into('>3f', b, pos + 8 + 12 * k, f, v, t)
        pos += 8 + 12 * len(keys)
    for p in range(pos, end): b[p] = 0
    return bytes(b)
