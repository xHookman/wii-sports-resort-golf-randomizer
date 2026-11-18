/* Preuve de concept : deformation du relief du trou directement sur la Wii.
 * Appele juste avant la creation de l'objet collision du golf (0x80417DAC -> 0x80401360).
 * - retrouve l'archive du trou chargee (gestionnaire *(r13-11488) -> +12 -> +0x18)
 * - deforme les sommets du modele (MDL0), des objets (PMP) et reconstruit la collision (KCL)
 *   avec la meme fonction de hauteur : visuel et collisions restent coherents.
 * Compile aussi sur PC (-DHOST) pour tester l'ecriture KCL contre l'outil Python. */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef int s32;
#ifdef HOST
#define HI
#define NOINL
#else
#define HI __attribute__((section(".text.hi"), noinline))
#define NOINL __attribute__((noinline))
#endif

/* ---------- acces gros-boutiste (marche sur PC comme sur Wii) ---------- */
static u32 rd32(const u8 *p) { return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3]; }
static u16 rd16(const u8 *p) { return (u16)((p[0] << 8) | p[1]); }
static void wr32(u8 *p, u32 v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }
static void wr16(u8 *p, u16 v) { p[0] = v >> 8; p[1] = (u8)v; }
static float rdf(const u8 *p) { union { u32 i; float f; } u; u.i = rd32(p); return u.f; }
static void wrf(u8 *p, float f) { union { u32 i; float f; } u; u.f = f; wr32(p, u.i); }

void *memcpy(void *d, const void *s, unsigned long n) { u8 *a = d; const u8 *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, unsigned long n) { u8 *a = d; while (n--) *a++ = (u8)c; return d; }

static int starts(const char *s, const char *p) { while (*p) if (*s++ != *p++) return 0; return 1; }
static int ends(const char *s, const char *e) {
    const char *a = s, *b = e; while (*a) a++; while (*b) b++;
    while (b > e) { if (a == s || *--a != *--b) return 0; }
    return 1;
}
static int streq(const char *a, const char *b) { while (*a && *a == *b) a++, b++; return *a == *b; }

/* ---------- maths ---------- */
static float fsqrt(float x) {             /* Newton, suffisant ici */
    if (x <= 0) return 0;
    float r = x > 1 ? x : 1;
    for (int i = 0; i < 20; i++) r = 0.5f * (r + x / r);
    return r;
}
static float fsin(float x) {
    const float PI = 3.14159265f, TWO_PI = 6.2831853f;
    x -= TWO_PI * (float)(s32)(x / TWO_PI);
    if (x > PI) x -= TWO_PI; else if (x < -PI) x += TWO_PI;
    if (x > PI / 2) x = PI - x; else if (x < -PI / 2) x = -PI - x;
    float x2 = x * x;
    return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42)));
}
typedef struct { float x, y, z; } V3;
static V3 sub(V3 a, V3 b) { V3 r = { a.x - b.x, a.y - b.y, a.z - b.z }; return r; }
static float dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static V3 cross(V3 a, V3 b) { V3 r = { a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x }; return r; }
static int norm(V3 *a) { float l = fsqrt(dot(*a, *a)); if (l < 1e-6f) return 0; a->x /= l; a->y /= l; a->z /= l; return 1; }
static V3 rdv(const u8 *p) { V3 r = { rdf(p), rdf(p + 4), rdf(p + 8) }; return r; }
static void wrv(u8 *p, V3 v) { wrf(p, v.x); wrf(p + 4, v.y); wrf(p + 8, v.z); }

/* ---------- deformation ---------- */
typedef struct { float amp, k, px, pz; } Wave;
static float height(const Wave *w, float x, float y, float z) {
    if (y < -500.0f) return 0;            /* plan de mer / hors-limites : on ne touche pas */
    return w->amp * fsin(x * w->k + w->px) * fsin(z * w->k + w->pz);
}

/* ---------- ecriture KCL (portage de tools/kclwrite.py) ---------- */
typedef struct { V3 a, b, c; u16 attr; } Tri;

typedef struct {
    const Tri *t; u8 *out; u32 cap, len; u16 *stk; u32 stkcap, stktop; float margin; int max_tris; float min_size; int fail;
} Oct;

static int tri_box(const Tri *t, float lx, float ly, float lz, float s, float m) {
    float mn, mx;
    mn = t->a.x; if (t->b.x < mn) mn = t->b.x; if (t->c.x < mn) mn = t->c.x;
    mx = t->a.x; if (t->b.x > mx) mx = t->b.x; if (t->c.x > mx) mx = t->c.x;
    if (mx + m < lx || mn - m > lx + s) return 0;
    mn = t->a.y; if (t->b.y < mn) mn = t->b.y; if (t->c.y < mn) mn = t->c.y;
    mx = t->a.y; if (t->b.y > mx) mx = t->b.y; if (t->c.y > mx) mx = t->c.y;
    if (mx + m < ly || mn - m > ly + s) return 0;
    mn = t->a.z; if (t->b.z < mn) mn = t->b.z; if (t->c.z < mn) mn = t->c.z;
    mx = t->a.z; if (t->b.z > mx) mx = t->b.z; if (t->c.z > mx) mx = t->c.z;
    if (mx + m < lz || mn - m > lz + s) return 0;
    return 1;
}

static u32 reserve(Oct *o, u32 n) {
    u32 at = o->len;
    if (o->len + n > o->cap) { o->fail = 1; return at; }
    memset(o->out + at, 0, n); o->len += n; return at;
}

/* cand : liste d'indices sur la pile ; ecrit la valeur du mot 'slot' (relatif a 'base') */
static void build(Oct *o, u32 slot, u32 base, float lx, float ly, float lz, float s, u32 c0, u32 nc) {
    u32 top = o->stktop, n = 0;
    if (top + nc > o->stkcap) { o->fail = 1; return; }
    for (u32 i = 0; i < nc; i++) {
        u16 id = o->stk[c0 + i];
        if (tri_box(&o->t[id], lx, ly, lz, s, o->margin)) o->stk[top + n++] = id;
    }
    o->stktop = top + n;
    if ((int)n <= o->max_tris || s <= o->min_size) {
        /* feuille : u16 0, indices (+1), u16 0 ; le pointeur vise le 0 initial */
        u32 at = reserve(o, (n + 2) * 2 + 2);   /* +2 pour aligner sur 4 */
        if (!o->fail) {
            for (u32 i = 0; i < n; i++) wr16(o->out + at + 2 + 2 * i, (u16)(o->stk[top + i] + 1));
            wr32(o->out + slot, 0x80000000u | (at - base));
            o->len = (o->len + 3) & ~3u;
        }
    } else {
        u32 g = reserve(o, 32);
        if (!o->fail) {
            wr32(o->out + slot, g - base);
            float h = s / 2;
            for (int ci = 0; ci < 8 && !o->fail; ci++)
                build(o, g + 4 * ci, g, lx + (ci & 1) * h, ly + (ci >> 1 & 1) * h, lz + (ci >> 2 & 1) * h, h, top, n);
        }
    }
    o->stktop = top;
}

static int ilog2_floor(float v) { int r = 0; while ((float)(1u << (r + 1)) <= v && r < 30) r++; return r; }
static int ilog2_ceil(float v) { int r = 0; while ((float)(1u << r) < v && r < 30) r++; return r; }

/* Ecrit un KCL complet dans out (capacite cap). Retourne la taille ou 0. */
NOINL static u32 write_kcl(const Tri *t, u32 n, float thickness, float radius, u8 *out, u32 cap, u16 *stk, u32 stkcap) {
    u32 hdr = 0x3C, pos_o = hdr, nrm_o = pos_o + n * 12, pri_o = nrm_o + n * 48, blk_o = pri_o + n * 16;
    if (blk_o > cap || n == 0 || n > 65000) return 0;
    float mn[3] = { 1e30f, 1e30f, 1e30f }, mx[3] = { -1e30f, -1e30f, -1e30f };
    u32 m = 0;
    for (u32 i = 0; i < n; i++) {
        V3 A = t[i].a, B = t[i].b, C = t[i].c, P[3] = { A, B, C };
        V3 fn = cross(sub(B, A), sub(C, A));
        if (!norm(&fn)) continue;
        V3 e1 = cross(fn, sub(C, A)), e2 = cross(sub(B, A), fn), e3 = cross(sub(C, B), fn);
        if (!norm(&e1) || !norm(&e2) || !norm(&e3)) continue;
        float h = dot(sub(B, A), e3);
        if (h <= 0) continue;
        wrv(out + pos_o + m * 12, A);
        u8 *nb = out + nrm_o + m * 48;
        wrv(nb, fn); wrv(nb + 12, e1); wrv(nb + 24, e2); wrv(nb + 36, e3);
        u8 *pp = out + pri_o + m * 16;
        wrf(pp, h); wr16(pp + 4, (u16)m); wr16(pp + 6, (u16)(4 * m)); wr16(pp + 8, (u16)(4 * m + 1));
        wr16(pp + 10, (u16)(4 * m + 2)); wr16(pp + 12, (u16)(4 * m + 3)); wr16(pp + 14, t[i].attr);
        if (m != i) { /* compacte les triangles valides en tete (t est en ecriture chez nous) */ }
        for (int k = 0; k < 3; k++) {
            float c[3] = { P[k].x, P[k].y, P[k].z };
            for (int j = 0; j < 3; j++) { if (c[j] < mn[j]) mn[j] = c[j]; if (c[j] > mx[j]) mx[j] = c[j]; }
        }
        ((Tri *)t)[m] = t[i];
        m++;
    }
    /* les tableaux ont ete ecrits pour m <= n ; on garde les decalages calcules sur n (trous inutilises) */
    for (int j = 0; j < 3; j++) { mn[j] -= 50.0f; mx[j] += 50.0f; }
    float ext[3] = { mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2] };
    float smallest = ext[0]; if (ext[1] < smallest) smallest = ext[1]; if (ext[2] < smallest) smallest = ext[2];
    float min_size = 128.0f;
    int shift = ilog2_floor(smallest < 1 ? 1 : smallest); if (shift < 7) shift = 7;
    float cube = (float)(1u << shift);
    int wb[3], nn[3];
    for (int j = 0; j < 3; j++) { wb[j] = ilog2_ceil(ext[j] < 1 ? 1 : ext[j]); if (wb[j] < shift) wb[j] = shift; nn[j] = 1 << (wb[j] - shift); }
    int xs = ilog2_ceil((float)nn[0]), xys = ilog2_ceil((float)(nn[0] * nn[1]));

    Oct o; o.t = t; o.out = out; o.cap = cap; o.len = blk_o; o.stk = stk; o.stkcap = stkcap; o.stktop = 0;
    o.margin = radius + 1.0f; o.max_tris = 24; o.min_size = min_size; o.fail = 0;
    u32 nroot = (u32)(nn[0] * nn[1] * nn[2]);
    u32 g = reserve(&o, 4 * nroot);
    if (o.fail || m > stkcap) return 0;
    for (u32 i = 0; i < m; i++) stk[i] = (u16)i;
    o.stktop = m;
    for (int z = 0; z < nn[2] && !o.fail; z++)
        for (int y = 0; y < nn[1] && !o.fail; y++)
            for (int x = 0; x < nn[0] && !o.fail; x++)
                build(&o, g + 4 * (u32)((z << xys) | (y << xs) | x), g,
                      mn[0] + x * cube, mn[1] + y * cube, mn[2] + z * cube, cube, 0, m);
    if (o.fail) return 0;
    /* en-tete */
    wr32(out + 0x00, pos_o); wr32(out + 0x04, nrm_o); wr32(out + 0x08, pri_o - 0x10); wr32(out + 0x0C, blk_o);
    wrf(out + 0x10, thickness); wrf(out + 0x14, mn[0]); wrf(out + 0x18, mn[1]); wrf(out + 0x1C, mn[2]);
    for (int j = 0; j < 3; j++) wr32(out + 0x20 + 4 * j, ~((1u << wb[j]) - 1));
    wr32(out + 0x2C, (u32)shift); wr32(out + 0x30, (u32)xs); wr32(out + 0x34, (u32)xys); wrf(out + 0x38, radius);
    return (o.len + 3) & ~3u;
}

/* Decode les prismes d'un KCL en triangles (cf. tools/kcltri.py). Retourne le nombre. */
HI static u32 read_kcl(const u8 *k, Tri *t, u32 cap) {
    u32 pos_o = rd32(k), nrm_o = rd32(k + 4), pri_first = rd32(k + 8) + 0x10, blk_o = rd32(k + 12);
    u32 n = (blk_o - pri_first) / 16; if (n > cap) n = cap;
    for (u32 i = 0; i < n; i++) {
        const u8 *p = k + pri_first + 16 * i;
        float h = rdf(p);
        V3 A = rdv(k + pos_o + 12 * rd16(p + 4));
        V3 fn = rdv(k + nrm_o + 12 * rd16(p + 6)), e1 = rdv(k + nrm_o + 12 * rd16(p + 8));
        V3 e2 = rdv(k + nrm_o + 12 * rd16(p + 10)), e3 = rdv(k + nrm_o + 12 * rd16(p + 12));
        V3 cA = cross(e1, fn), cB = cross(e2, fn);
        float dB = h / dot(cB, e3), dC = h / dot(cA, e3);
        t[i].a = A;
        t[i].b.x = A.x + cB.x * dB; t[i].b.y = A.y + cB.y * dB; t[i].b.z = A.z + cB.z * dB;
        t[i].c.x = A.x + cA.x * dC; t[i].c.y = A.y + cA.y * dC; t[i].c.z = A.z + cA.z * dC;
        t[i].attr = rd16(p + 14);
    }
    return n;
}

/* ---------- BRRES / MDL0 ---------- */
static const u8 *dict_find(const u8 *dict, const char *name, int *count, int idx) {
    /* idx >= 0 : renvoie la i-eme entree ; sinon cherche par nom */
    u32 n = rd32(dict + 4); if (count) *count = (int)n;
    for (u32 i = 1; i <= n; i++) {
        const u8 *e = dict + 8 + 16 * i;
        const char *nm = (const char *)dict + rd32(e + 8);
        if ((idx >= 0 && (int)i - 1 == idx) || (idx < 0 && streq(nm, name))) return dict + rd32(e + 12);
    }
    return 0;
}

static void flush(void *p, u32 n) {
#ifndef HOST
    u32 a = (u32)p & ~31u, e = (u32)p + n;
    for (; a < e; a += 32) __asm__ volatile("dcbf 0,%0" :: "r"(a));
    __asm__ volatile("sync");
#else
    (void)p; (void)n;
#endif
}

HI static u32 deform_brres(u8 *b, const Wave *w) {
    if (rd32(b) != 0x62726573) return 0;              /* 'bres' */
    u8 *root = b + rd16(b + 0xC);
    const u8 *grp = dict_find(root + 8, "3DModels(NW4R)", 0, -1);
    if (!grp) return 0;
    int nm = 0; dict_find(grp, "", &nm, 0);
    u32 nv = 0;
    for (int mi = 0; mi < nm; mi++) {
        u8 *mo = (u8 *)dict_find(grp, 0, 0, mi);
        s32 vs = (s32)rd32(mo + 16 + 4 * 2);            /* section Vertices */
        if (!vs) continue;
        const u8 *vd = mo + vs; int na = 0; dict_find(vd, "", &na, 0);
        for (int ai = 0; ai < na; ai++) {
            u8 *a = (u8 *)dict_find(vd, 0, 0, ai);
            u32 comp = rd32(a + 0x14), fmt = rd32(a + 0x18);
            u8 stride = a[0x1D]; u16 cnt = rd16(a + 0x1E);
            if (comp != 1 || fmt != 4) continue;         /* XYZ flottants seulement */
            u8 *d = a + (s32)rd32(a + 8);
            float ymin = 1e30f, ymax = -1e30f;
            for (u32 i = 0; i < cnt; i++) {
                u8 *p = d + stride * i;
                float x = rdf(p), y = rdf(p + 4), z = rdf(p + 8);
                y += height(w, x, y, z);
                wrf(p + 4, y);
                if (y < ymin) ymin = y; if (y > ymax) ymax = y;
            }
            wrf(a + 0x24, ymin); wrf(a + 0x30, ymax);    /* boite englobante */
            flush(d, (u32)stride * cnt); flush(a, 0x40);
            nv += cnt;
        }
    }
    return nv;
}

HI static u32 deform_pmp(u8 *p, const Wave *w) {
    if (rd32(p) != 0x504D5046) return 0;              /* 'PMPF' */
    u16 n = rd16(p + 0x10);
    for (u32 i = 0; i < n; i++) {
        u8 *o = p + 0x80 + 88 * i;
        float x = rdf(o + 8), y = rdf(o + 12), z = rdf(o + 16);
        wrf(o + 12, y + height(w, x, y, z));
    }
    return n;
}

/* ---------- point d'entree ---------- */
#ifndef HOST
#define STATUS ((volatile u32 *)0x800037E0)
typedef void *(*alloc_t)(u32 size, s32 align, void *heap);
typedef void (*free_t)(void *p);
#define GAME_ALLOC ((alloc_t)0x801c1654)
#define GAME_FREE  ((free_t)0x801c1c90)

static u32 timebase(void) { u32 t; __asm__ volatile("mftb %0" : "=r"(t)); return t; }

void poc_main(void) {
    STATUS[0] = 0x504F4300; STATUS[1] = STATUS[2] = STATUS[3] = 0;
    u32 mgr = *(volatile u32 *)(0x806F87C0 - 11488);
    if (!mgr) return;
    u32 h = *(volatile u32 *)(mgr + 12); if (!h) return;
    u8 *arc = *(u8 **)(h + 0x18);
    if (!arc || rd32(arc) != 0x55AA382D) { STATUS[0] = 0x504F4301; return; }
    u8 *nodes = arc + rd32(arc + 4); u32 nn = rd32(nodes + 8); const char *st = (const char *)nodes + nn * 12;
    u8 *kcl = 0, *brres = 0, *pmp = 0; u32 kcl_sz = 0;
    for (u32 i = 0; i < nn; i++) {
        u8 *e = nodes + 12 * i; if (e[0]) continue;
        const char *nm = st + (rd32(e) & 0xFFFFFF);
        if (starts(nm, "WS2_glf_course_") && ends(nm, ".kcl")) { kcl = arc + rd32(e + 4); kcl_sz = rd32(e + 8); }
        else if (starts(nm, "WS2_glf_course_") && ends(nm, ".pmp")) pmp = arc + rd32(e + 4);
        else if (starts(nm, "glf_course_") && ends(nm, ".brres")) brres = arc + rd32(e + 4);
    }
    if (!kcl || !brres || !pmp) { STATUS[0] = 0x504F4302; return; }
    /* place libre au bout du KCL : l'archive de test le prolonge par des zeros */
    u32 used = rd32(kcl + 12);
    u32 pri_first = rd32(kcl + 8) + 0x10, n = (used - pri_first) / 16;

    u32 t0 = timebase();
    Wave w; w.amp = 140.0f; w.k = 6.2831853f / 2600.0f;
    w.px = (float)(t0 & 1023) * 0.00614f; w.pz = (float)((t0 >> 10) & 1023) * 0.00614f;

    Tri *tris = (Tri *)GAME_ALLOC(n * sizeof(Tri), 32, 0);
    u16 *stk = (u16 *)GAME_ALLOC(n * 2 * 8, 32, 0);
    if (!tris || !stk) { STATUS[0] = 0x504F4303; if (tris) GAME_FREE(tris); return; }
    n = read_kcl(kcl, tris, n);
    for (u32 i = 0; i < n; i++) {
        tris[i].a.y += height(&w, tris[i].a.x, tris[i].a.y, tris[i].a.z);
        tris[i].b.y += height(&w, tris[i].b.x, tris[i].b.y, tris[i].b.z);
        tris[i].c.y += height(&w, tris[i].c.x, tris[i].c.y, tris[i].c.z);
    }
    /* l'archive de test prolonge le KCL de zeros : on reecrit directement a sa place
       (les triangles sont deja copies dans 'tris'). Garde-fou : taille fixe + 64 Ko d'octree. */
    STATUS[1] = n; STATUS[3] = kcl_sz;
    if (0x3C + n * 76 + 0x10000 > kcl_sz) { STATUS[0] = 0x504F4304; GAME_FREE(stk); GAME_FREE(tris); return; }
    u32 sz = write_kcl(tris, n, rdf(kcl + 0x10), rdf(kcl + 0x38), kcl, kcl_sz, stk, n * 8);
    STATUS[2] = sz;
    if (!sz) { STATUS[0] = 0x504F4305; GAME_FREE(stk); GAME_FREE(tris); return; }
    u32 nv = deform_brres(brres, &w);
    u32 np = deform_pmp(pmp, &w);
    GAME_FREE(stk); GAME_FREE(tris);
    STATUS[0] = 0x504F4F4B;  /* 'POOK' */
    STATUS[4] = nv; STATUS[5] = np; STATUS[6] = timebase() - t0;
}
#else
/* ---------- test PC : relit un KCL, le reecrit, compare via l'outil Python ---------- */
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, 2); long L = ftell(f); fseek(f, 0, 0);
    u8 *k = malloc(L); fread(k, 1, L, f); fclose(f);
    u32 n = (rd32(k + 12) - (rd32(k + 8) + 0x10)) / 16;
    Tri *t = malloc(n * sizeof(Tri)); n = read_kcl(k, t, n);
    float amp = argc > 3 ? atof(argv[3]) : 0;
    Wave w = { amp, 6.2831853f / 2600.0f, 0.3f, 1.1f };
    for (u32 i = 0; i < n; i++) {
        t[i].a.y += height(&w, t[i].a.x, t[i].a.y, t[i].a.z);
        t[i].b.y += height(&w, t[i].b.x, t[i].b.y, t[i].b.z);
        t[i].c.y += height(&w, t[i].c.x, t[i].c.y, t[i].c.z);
    }
    u32 cap = (u32)L * 3; u8 *out = malloc(cap); u16 *stk = malloc(n * 16);
    u32 sz = write_kcl(t, n, rdf(k + 0x10), rdf(k + 0x38), out, cap, stk, n * 8);
    printf("prismes %u  ancien %ld  nouveau %u\n", n, L, sz);
    f = fopen(argv[2], "wb"); fwrite(out, 1, sz, f); fclose(f);
    return sz == 0;
}
#endif
