"""Remplacement de la geometrie d'objets MDL0 dans un fichier BRRES.

Chaque objet cible recoit de nouveaux tableaux (positions, normales, couleurs,
UV) et une nouvelle liste d'affichage. Les donnees sont ajoutees en fin de
fichier (alignees 32 octets) ; les en-tetes existants sont redirigees vers elles.
Les materiaux, textures, shaders et objets non cibles ne sont pas touches.
"""
import struct
from brres import brres_tree
from mdl0 import read_mdl0

FMT = {0: ('B', 1), 1: ('b', 1), 2: ('H', 2), 3: ('h', 2), 4: ('f', 4)}


def _align(buf, a=32):
    while len(buf) % a: buf.append(0)


def _enc_values(vals, fmt, div):
    c, sz = FMT[fmt]
    if fmt == 4:
        return struct.pack('>' + c * len(vals), *vals)
    s = 1 << div
    lo, hi = {0: (0, 255), 1: (-128, 127), 2: (0, 65535), 3: (-32768, 32767)}[fmt]
    q = [max(lo, min(hi, int(round(v * s)))) for v in vals]
    return struct.pack('>' + c * len(q), *q)


def replace_geometry(data, targets, model=0):
    """data : octets du BRRES. targets : {nom_objet: liste de triangles}, un triangle
    etant 3 sommets dict {'pos':(x,y,z), 'nrm':(..), 'clr0':(r,g,b,a), 'uv0':(u,v), ...}
    avec exactement les attributs de l'objet d'origine. Retourne les nouveaux octets."""
    d = bytearray(data)
    t = brres_tree(bytes(d))
    mo = t['3DModels(NW4R)'][model][1]
    m = read_mdl0(bytes(d), mo)
    arr_hdr = {}
    for kind in ('pos', 'nrm', 'clr', 'uv'):
        for name, vals, meta in m['arr'][kind]:
            arr_hdr[(kind, meta['idx'])] = (meta, _hdr_offset(d, mo, kind, meta['idx']))
    # tableaux partages entre objets (frequent pour les couleurs) : un seul tableau commun par index,
    # qui garde d'abord les valeurs d'origine (objets non remplaces) puis ajoute celles des objets remplaces
    users = {}
    for p in m['polys']:
        ids = dict(zip(['pos', 'nrm', 'clr0', 'clr1'] + ['uv%d' % k for k in range(8)], p['ids']))
        for a, _ in p['attrs']:
            kind = 'uv' if a.startswith('uv') else ('clr' if a.startswith('clr') else a)
            users.setdefault((kind, ids[a]), set()).add(p['name'])
    orig_vals = {(kind, meta['idx']): vals for kind in ('pos', 'nrm', 'clr', 'uv') for _, vals, meta in m['arr'][kind]}
    G = {}
    def table(kind, aid):
        if (kind, aid) not in G:
            lst, mp = [], {}
            if users[(kind, aid)] - set(targets):            # un objet garde ses indices d'origine
                for v in orig_vals[(kind, aid)]:
                    k = tuple(v); mp.setdefault(k, len(lst)); lst.append(k)
            G[(kind, aid)] = (lst, mp)
        return G[(kind, aid)]
    per_poly = {}
    for p in m['polys']:
        if p['name'] not in targets: continue
        slots = [a for a, _ in p['attrs']]
        ids = dict(zip(['pos', 'nrm', 'clr0', 'clr1'] + ['uv%d' % k for k in range(8)], p['ids']))
        kinds = {s: ('uv' if s.startswith('uv') else ('clr' if s.startswith('clr') else s)) for s in slots}
        idx_tris = []
        for tri in targets[p['name']]:
            vt = []
            for v in tri:
                e = {}
                for s in slots:
                    lst, mp = table(kinds[s], ids[s]); key = tuple(v[s])
                    if key not in mp: mp[key] = len(lst); lst.append(key)
                    e[s] = mp[key]
                vt.append(e)
            idx_tris.append(vt)
        per_poly[p['name']] = (slots, ids, kinds, idx_tris)
    for (kind, aid), (lst, mp) in G.items():
        meta, ho = arr_hdr[(kind, aid)]
        if len(lst) > 65535: raise ValueError('trop d\'elements dans un tableau %s' % kind)
        blob = bytearray()
        for vals in lst:
            if kind == 'clr':
                blob.extend(bytes(vals[:4]) if meta['fmt'] == 5 else bytes(vals[:3]))
            else:
                blob.extend(_enc_values(vals, meta['fmt'], meta['div']))
        old_off = ho + struct.unpack('>i', bytes(d[ho + 8:ho + 12]))[0]
        old_len = meta['stride'] * struct.unpack('>H', bytes(d[ho + 0x1E:ho + 0x20]))[0]
        if len(blob) <= old_len:
            start = old_off
            d[start:start + len(blob)] = blob
        else:
            _align(d)
            start = len(d)
            d.extend(blob)
        struct.pack_into('>i', d, ho + 8, start - ho)
        struct.pack_into('>H', d, ho + 0x1E, len(lst))
        if kind == 'pos':
            mn = [min(v[i] for v in lst) for i in range(3)]; mx = [max(v[i] for v in lst) for i in range(3)]
            struct.pack_into('>6f', d, ho + 0x20, *mn, *mx)
        elif kind == 'uv':
            mn = [min(v[i] for v in lst) for i in range(2)]; mx = [max(v[i] for v in lst) for i in range(2)]
            struct.pack_into('>4f', d, ho + 0x20, *mn, *mx)
    dv_total = df_total = 0
    for p in m['polys']:
        if p['name'] not in targets:
            dv_total += p['nverts']; df_total += p['nfaces']
            continue
        slots, ids, kinds, idx_tris = per_poly[p['name']]
        tables = {s: G[(kinds[s], ids[s])] for s in slots}
        # --- descripteur : index 8 bits si < 256 elements, sinon 16 bits
        o = p['hdr']
        vlo, vhi = p['vcd']
        width = {s: (1 if len(tables[s][0]) <= 255 else 2) for s in slots}
        for s, sh in (('pos', 9), ('nrm', 11), ('clr0', 13), ('clr1', 15)):
            if s in slots: vlo = (vlo & ~(3 << sh)) | ((width[s] + 1) << sh)
        for k in range(8):
            if 'uv%d' % k in slots: vhi = (vhi & ~(3 << 2 * k)) | ((width['uv%d' % k] + 1) << 2 * k)
        struct.pack_into('>II', d, o + 0x0C, vlo, vhi)
        vdef = o + 0x18 + struct.unpack('>i', d[o + 0x20:o + 0x24])[0]
        vsize = struct.unpack('>I', d[o + 0x18:o + 0x1C])[0]
        i = 0
        while i < vsize:
            c = d[vdef + i]
            if c == 0x08:
                reg = d[vdef + i + 1]
                if reg == 0x50: struct.pack_into('>I', d, vdef + i + 2, vlo)
                if reg == 0x60: struct.pack_into('>I', d, vdef + i + 2, vhi)
                i += 6
            elif c == 0x10:
                n = struct.unpack('>H', d[vdef + i + 1:vdef + i + 3])[0] + 1; i += 5 + 4 * n
            else:
                i += 1
        # --- liste d'affichage : bandes (0x98) quand les triangles s'enchainent, sinon triangles (0x90)
        dl = bytearray()
        order = [s for s in slots if s in ('pos', 'nrm', 'clr0', 'clr1')] + sorted(s for s in slots if s.startswith('uv'))
        def key(e): return tuple(e[s] for s in order)
        def emit_vertex(e):
            for s in order:
                dl.extend(struct.pack('>B', e[s]) if width[s] == 1 else struct.pack('>H', e[s]))
        strips, singles = [], []
        cur = None
        for vt in idx_tris:
            if cur is not None and len(cur) < 65000:
                k = len(cur) - 2
                exp = (key(cur[-2]), key(cur[-1])) if k % 2 == 0 else (key(cur[-1]), key(cur[-2]))
                if (key(vt[0]), key(vt[1])) == exp:
                    cur.append(vt[2]); continue
            if cur is not None: strips.append(cur)
            cur = list(vt)
        if cur is not None: strips.append(cur)
        for st in strips:
            if len(st) == 3: singles.append(st); continue
            dl.append(0x98); dl.extend(struct.pack('>H', len(st)))
            for e in st: emit_vertex(e)
        for c0 in range(0, len(singles), 21000):
            part = singles[c0:c0 + 21000]
            dl.append(0x90); dl.extend(struct.pack('>H', 3 * len(part)))
            for vt in part:
                for e in vt: emit_vertex(e)
        _align(dl)
        old_dl, old_dl_size = p['dl']
        if len(dl) <= old_dl_size:
            start = old_dl                                          # sur place
            d[start:start + len(dl)] = dl
        else:
            _align(d)
            start = len(d)
            d.extend(dl)
        struct.pack_into('>II', d, o + 0x24, len(dl), len(dl))
        struct.pack_into('>i', d, o + 0x2C, start - (o + 0x24))
        struct.pack_into('>II', d, o + 0x40, 3 * len(idx_tris), len(idx_tris))
        dv_total += 3 * len(idx_tris); df_total += len(idx_tris)
    info = mo + 16 + 4 * 14 + 4
    struct.pack_into('>II', d, info + 0x10, dv_total, df_total)
    _align(d)
    struct.pack_into('>I', d, 8, len(d))   # taille du fichier BRRES
    return bytes(d)


def _hdr_offset(d, mo, kind, idx):
    from brres import _dict
    secs = struct.unpack('>14i', bytes(d[mo + 16:mo + 16 + 56]))
    si = {'pos': 2, 'nrm': 3, 'clr': 4, 'uv': 5}[kind]
    for _, o in _dict(bytes(d), mo + secs[si]):
        if struct.unpack('>I', bytes(d[o + 0x10:o + 0x14]))[0] == idx: return o
    raise KeyError((kind, idx))
