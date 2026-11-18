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
#define HI __attribute__((noinline))
#define NOINL __attribute__((noinline))
#endif

/* ---------- acces gros-boutiste (marche sur PC comme sur Wii) ---------- */
static u32 rd32(const u8 *p) { return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3]; }
static u16 rd16(const u8 *p) { return (u16)((p[0] << 8) | p[1]); }
static void wr32(u8 *p, u32 v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }
static void wr16(u8 *p, u16 v) { p[0] = v >> 8; p[1] = (u8)v; }
static float rdf(const u8 *p) { union { u32 i; float f; } u; u.i = rd32(p); return u.f; }
static void wrf(u8 *p, float f) { union { u32 i; float f; } u; u.f = f; wr32(p, u.i); }

#ifndef HOST
void *memcpy(void *d, const void *s, unsigned long n) { u8 *a = d; const u8 *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, unsigned long n) { u8 *a = d; while (n--) *a++ = (u8)c; return d; }
#else
#include <string.h>
#endif

static int starts(const char *s, const char *p) { while (*p) if (*s++ != *p++) return 0; return 1; }
static int ends(const char *s, const char *e) {
    const char *a = s, *b = e; while (*a) a++; while (*b) b++;
    while (b > e) { if (a == s || *--a != *--b) return 0; }
    return 1;
}
static int streq(const char *a, const char *b) { while (*a && *a == *b) a++, b++; return *a == *b; }

/* ---------- maths ---------- */
static float fsqrt(float x) {
    /* depart tire de l'exposant (exact a ~4 % pres), puis Newton : juste pour TOUTES les grandeurs.
       L'ancienne version (depart = x, 20 pas) ne convergeait pas au-dela de ~1e12 : normales de la mer
       ~0,008 au lieu de 1 -> le jeu croyait la balle dans l'eau jusqu'a ~60 unites au-dessus de la mer. */
    if (x <= 0) return 0;
    union { float f; u32 i; } u; u.f = x; u.i = 0x1fbd1df5u + (u.i >> 1);
    float r = u.f;
    for (int i = 0; i < 6; i++) r = 0.5f * (r + x / r);
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

/* ---------- aleatoire ---------- */
typedef struct { u32 s; } Rng;
static u32 rnext(Rng *r) { u32 x = r->s; x ^= x << 13; x ^= x >> 17; x ^= x << 5; r->s = x; return x; }
static float runi(Rng *r, float a, float b) { return a + (b - a) * (float)(rnext(r) >> 8) * (1.0f / 16777216.0f); }
static int rint_(Rng *r, int a, int b) { return a + (int)(rnext(r) % (u32)(b - a + 1)); }
static float fexpn(float x) {               /* exp(x) pour x <= 0 */
    if (x < -12.0f) return 0;
    float y = 1.0f + x / 256.0f; y *= y; y *= y; y *= y; y *= y; y *= y; y *= y; y *= y; y *= y;
    return y;
}
static float clamp01(float v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
static float smooth01(float v) { v = clamp01(v); return v * v * (3 - 2 * v); }

/* ---------- surfaces (bits bas de l'attribut KCL) ---------- */
enum { S_NONE = 0, S_FAIR = 1, S_ROUGH = 2, S_BUNKER = 3, S_OB = 4, S_GREEN = 6, S_WATER = 7, S_COLLAR = 9, S_BANK = 12 };
static int is_land(int s) { return s == S_FAIR || s == S_ROUGH || s == S_BUNKER || s == S_OB || s == S_GREEN || s == S_WATER || s == S_COLLAR || s == S_BANK; }

/* grille de triangles pour retrouver le sol (hauteur + surface) en (x, z) */
typedef struct {
    const struct Tri_ *t; float x0, z0, cs; int nx, nz; u32 *start; u16 *idx;
} Ground;

/* champ de surfaces + distances (pas DS) */
#define DS 50.0f
enum { D_FAIR, D_GREEN, D_WATER, D_BUNKER, D_TEE, ND };
typedef struct {
    float x0, z0; int nx, nz; u8 *typ; float *dist[ND];
    u32 *land; u32 nland;                              /* cellules de terrain jouable/decor (tirage) */
} Field;

typedef struct { float x, z, a, k, r2; } Bump;      /* a * exp(-k d2), coupe a d2 > r2 */
#define MAXB 64
typedef struct {
    Bump b[MAXB]; int nb;
    float tx, tz, tee_a, tee_r;                       /* depart sureleve */
    float gx, gz, g_r, g_sx, g_sz;                    /* green : pente + bosses */
    Bump gb[3]; int ngb;
    const Field *F;
    float ymin;                                       /* sous ce niveau (mer, plan hors-limites) : rien */
    float ysea;                                       /* niveau de l'eau la plus basse : le sol reste au-dessus */
    float hcup; int flat;                              /* replat autour du trou : hauteur ajoutee au drapeau */
    int np; float px[8], pz[8], ph[8];                 /* emplacements de drapeau (2,1) : replat chacun */
} Relief;

static float field_d(const Field *F, int k, float x, float z) {
    int i = (int)((x - F->x0) / DS), j = (int)((z - F->z0) / DS);
    if (i < 0 || j < 0 || i >= F->nx || j >= F->nz) return 1e9f;
    return F->dist[k][j * F->nx + i];
}

static float height_raw(const Relief *R, float x, float y, float z);
/* autour du trou, le green est un replat (rayon 50, raccord jusqu'a 140) : la balle tombe sans rester en equilibre */
static float height(const Relief *R, float x, float y, float z) {
    float h = height_raw(R, x, y, z);
    if (!R->flat || y < R->ymin) return h;
    float dx = x - R->gx, dz = z - R->gz, d2 = dx * dx + dz * dz;
    float t = d2 >= 140.0f * 140.0f ? 1.0f : smooth01((fsqrt(d2) - 50.0f) / 90.0f);
    h = R->hcup + (h - R->hcup) * t;
    for (int i = 0; i < R->np; i++) {                 /* chaque emplacement de drapeau : replat de 30, raccord 50 */
        float ex = x - R->px[i], ez = z - R->pz[i], e2 = ex * ex + ez * ez;
        if (e2 >= 80.0f * 80.0f) continue;
        float u = smooth01((fsqrt(e2) - 30.0f) / 50.0f);
        h = R->ph[i] + (h - R->ph[i]) * u;
    }
    return h;
}
static float height_raw(const Relief *R, float x, float y, float z) {
    if (y < R->ymin) return 0;
    float h = 0;
    for (int i = 0; i < R->nb; i++) {
        const Bump *b = &R->b[i]; float dx = x - b->x, dz = z - b->z, d2 = dx * dx + dz * dz;
        if (d2 < b->r2) h += b->a * fexpn(-b->k * d2);
    }
    /* les bosses qui se cumulent sont ecretees en douceur */
    if (h > 80.0f) h = 80.0f + (h - 80.0f) * 0.25f;
    if (h < -45.0f) h = -45.0f + (h + 45.0f) * 0.25f;
    float dx = x - R->gx, dz = z - R->gz, d = fsqrt(dx * dx + dz * dz);
    h *= 0.35f + 0.65f * smooth01((d - R->g_r - 20.0f) / 220.0f);   /* regle 18/11 : sur le green, un tiers des grosses bosses */
    dx = x - R->tx; dz = z - R->tz; d = fsqrt(dx * dx + dz * dz);
    h += R->tee_a * smooth01(1.0f - d / R->tee_r);
    dx = x - R->gx; dz = z - R->gz; d = fsqrt(dx * dx + dz * dz);
    if (d < R->g_r + 140.0f) {
        float g = R->g_sx * dx + R->g_sz * dz;
        for (int i = 0; i < R->ngb; i++) {
            const Bump *b = &R->gb[i]; float ex = x - b->x, ez = z - b->z;
            g += b->a * fexpn(-b->k * (ex * ex + ez * ez));
        }
        h += g * smooth01((R->g_r + 140.0f - d) / 140.0f);
    }
    /* pres de l'eau on ne bouge rien : surfaces d'eau planes, berges intactes */
    float dw = field_d(R->F, D_WATER, x, z);
    h *= smooth01((dw - 60.0f) / 220.0f);
    /* bunkers : on ne les met pas sur une dune (le terrain de base les porte deja a plat) */
    float db = field_d(R->F, D_BUNKER, x, z);
    h *= smooth01((db - 20.0f) / 160.0f);
    /* jamais d'abaissement sous le niveau de l'eau + 18 (sinon la mer recouvre le sol) */
    if (h < 0 && y + h < R->ysea + 18.0f) { float lim = R->ysea + 18.0f - y; h = lim > 0 ? 0 : (h > lim ? h : lim); }
    return h;
}

/* ---------- ecriture KCL (portage de tools/kclwrite.py) ---------- */
typedef struct Tri_ { V3 a, b, c; u16 attr; } Tri;

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
/* zero : decalage (absolu) de 4 octets nuls apres le groupe, partage par toutes les feuilles vides */
static void build(Oct *o, u32 slot, u32 base, u32 zero, float lx, float ly, float lz, float s, u32 c0, u32 nc) {
    u32 top = o->stktop, n = 0;
    if (top + nc > o->stkcap) { o->fail = 1; return; }
    for (u32 i = 0; i < nc; i++) {
        u16 id = o->stk[c0 + i];
        if (tri_box(&o->t[id], lx, ly, lz, s, o->margin)) o->stk[top + n++] = id;
    }
    o->stktop = top + n;
    if (n == 0) { wr32(o->out + slot, 0x80000000u | (zero - base)); o->stktop = top; return; }
    if ((int)n <= o->max_tris || s <= o->min_size) {
        /* feuille : u16 0, indices (+1), u16 0 ; le pointeur vise le 0 initial */
        u32 at = reserve(o, (n + 2) * 2 + 2);   /* +2 pour aligner sur 4 */
        if (!o->fail) {
            for (u32 i = 0; i < n; i++) wr16(o->out + at + 2 + 2 * i, (u16)(o->stk[top + i] + 1));
            wr32(o->out + slot, 0x80000000u | (at - base));
            o->len = (o->len + 3) & ~3u;
        }
    } else {
        u32 g = reserve(o, 36);
        if (!o->fail) {
            wr32(o->out + slot, g - base);
            float h = s / 2;
            for (int ci = 0; ci < 8 && !o->fail; ci++)
                build(o, g + 4 * ci, g, g + 32, lx + (ci & 1) * h, ly + (ci >> 1 & 1) * h, lz + (ci >> 2 & 1) * h, h, top, n);
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
    /* les tableaux ont ete ecrits pour m <= n ; on garde les decalages calcules sur n : les cases restantes
       recoivent une copie du premier prisme valide (jamais reference par l'octree, mais lisible) */
    if (m == 0) return 0;
    for (u32 i = m; i < n; i++) {
        u8 *a = out + pri_o + i * 16, *b = out + pri_o;
        for (int k = 0; k < 16; k++) a[k] = b[k];
    }
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
    u32 g = reserve(&o, 4 * nroot + 4);
    if (o.fail || m > stkcap) return 0;
    for (u32 i = 0; i < m; i++) stk[i] = (u16)i;
    o.stktop = m;
    for (int z = 0; z < nn[2] && !o.fail; z++)
        for (int y = 0; y < nn[1] && !o.fail; y++)
            for (int x = 0; x < nn[0] && !o.fail; x++)
                build(&o, g + 4 * (u32)((z << xys) | (y << xs) | x), g, g + 4 * nroot,
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
        float qB = dot(cB, e3), qC = dot(cA, e3);
        t[i].a = A; t[i].attr = rd16(p + 14);
        if (qB > -1e-4f && qB < 1e-4f) qB = 0; if (qC > -1e-4f && qC < 1e-4f) qC = 0;
        if (qB == 0 || qC == 0 || !(h == h)) { t[i].b = A; t[i].c = A; continue; }   /* prisme fin : triangle nul, ignore */
        float dB = h / qB, dC = h / qC;
        t[i].b.x = A.x + cB.x * dB; t[i].b.y = A.y + cB.y * dB; t[i].b.z = A.z + cB.z * dB;
        t[i].c.x = A.x + cA.x * dC; t[i].c.y = A.y + cA.y * dC; t[i].c.z = A.z + cA.z * dC;
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

HI static u32 deform_brres(u8 *b, const Relief *w) {
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

HI static u32 deform_pmp(u8 *p, const Relief *w) {
    if (rd32(p) != 0x504D5046) return 0;              /* 'PMPF' */
    u16 n = rd16(p + 0x10);
    for (u32 i = 0; i < n; i++) {
        u8 *o = p + 0x80 + 88 * i;
        float x = rdf(o + 8), y = rdf(o + 12), z = rdf(o + 16);
        wrf(o + 12, y + height(w, x, y, z));
    }
    return n;
}


/* trajet au sol des cameras de presentation : pas d'arbre a moins de 260 */
#define MAXCAM 700
typedef struct { float x[MAXCAM], z[MAXCAM]; int n; } CamPath;
static int near_cam(const CamPath *c, float x, float z) {
    for (int i = 0; i < c->n; i++) { float dx = c->x[i] - x, dz = c->z[i] - z; if (dx * dx + dz * dz < 260.0f * 260.0f) return 1; }
    return 0;
}
static int ground_at(const Ground *G, float x, float z, float *y, int *srf);
/* ---------- cameras de presentation (SCN0) : on les remonte au-dessus des nouvelles bosses ---------- */
static int cam_track(const u8 *blk, u32 len, u32 fb, int i, u32 *to, u16 *n) {
    u32 fa = fb + 4 * (u32)i; s32 off = (s32)rd32(blk + fa); u32 t = fa + (u32)off;
    if (off > 0 && (u32)off < len && t + 8 <= len && (off & 3) == 0 && blk[t + 2] == 0 && blk[t + 3] == 0) {
        *to = t; *n = rd16(blk + t); if (t + 8 + 12u * *n > len) return 0; return 1;
    }
    return 0;
}
static float herm(const u8 *k, u16 n, float f) {
    if (!n) return 0;
    if (f <= rdf(k)) return rdf(k + 4);
    if (f >= rdf(k + 12 * (n - 1))) return rdf(k + 12 * (n - 1) + 4);
    for (u16 i = 0; i + 1 < n; i++) {
        const u8 *a = k + 12 * i, *b = a + 12;
        float f0 = rdf(a), f1 = rdf(b);
        if (f >= f0 && f <= f1) {
            float d = f1 - f0; if (d <= 0) return rdf(b + 4);
            float s = (f - f0) / d, s2 = s * s, s3 = s2 * s;
            return (2 * s3 - 3 * s2 + 1) * rdf(a + 4) + (s3 - 2 * s2 + s) * d * rdf(a + 8)
                 + (-2 * s3 + 3 * s2) * rdf(b + 4) + (s3 - s2) * d * rdf(b + 8);
        }
    }
    return rdf(k + 12 * (n - 1) + 4);
}
typedef struct { const u8 *blk; u32 len, fb; int trk; u32 to; u16 n; } Fld;
static void fld(Fld *F, const u8 *blk, u32 len, u32 fb, int i) {
    F->blk = blk; F->len = len; F->fb = fb; F->trk = cam_track(blk, len, fb, i, &F->to, &F->n);
    if (!F->trk) F->to = fb + 4 * (u32)i;
}
static float fld_at(const Fld *F, float f) { return F->trk ? herm(F->blk + F->to + 8, F->n, f) : rdf(F->blk + F->to); }
/* bosse maximale (partie positive) sous la camera et autour (rayon 160) */
static float lift_at(const Relief *R, float x, float z) {
    float m = 0;
    for (int k = 0; k < 9; k++) {
        float ox = k == 0 ? 0 : 160.0f * fsin(k * 0.7853982f + 1.5707963f), oz = k == 0 ? 0 : 160.0f * fsin(k * 0.7853982f);
        float h = height(R, x + ox, 1e5f, z + oz); if (h > m) m = h;
    }
    return m;
}
HI static int lift_cameras(u8 *b, const Relief *R, const Ground *G) {
    if (rd32(b) != 0x62726573) return 0;
    u8 *root = b + rd16(b + 0xC);
    const u8 *grp = dict_find(root + 8, "AnmScn(NW4R)", 0, -1);
    if (!grp) return 0;
    int ns = 0; dict_find(grp, "", &ns, 0); int done = 0;
    for (int si = 0; si < ns; si++) {
        u8 *blk = (u8 *)dict_find(grp, 0, 0, si);
        if (rd32(blk) != 0x53434E30) continue;            /* 'SCN0' */
        u32 len = rd32(blk + 4), cb = rd32(blk + 0x24), fb = cb + 0x20; u16 nfr = rd16(blk + 0x34);
        if (!cb || fb + 0x40 > len || !nfr) continue;
        Fld px, py, pz, ax, ay, az;
        fld(&px, blk, len, fb, 0); fld(&py, blk, len, fb, 1); fld(&pz, blk, len, fb, 2);
        fld(&ax, blk, len, fb, 9); fld(&ay, blk, len, fb, 10); fld(&az, blk, len, fb, 11);
        /* position : chaque cle de hauteur remonte du max des bosses entre la cle d'avant et celle d'apres */
        u16 n = py.trk ? py.n : 1;
        float add[64]; if (n > 64) n = 64;
        for (u16 k = 0; k < n; k++) {
            float f0 = 0, f1 = nfr;
            if (py.trk) {
                const u8 *kk = blk + py.to + 8;
                f0 = k ? rdf(kk + 12 * (k - 1)) : rdf(kk); f1 = k + 1 < py.n ? rdf(kk + 12 * (k + 1)) : rdf(kk + 12 * k);
            }
            float m = 0;
            for (float f = f0; f <= f1 + 0.01f; f += 2.0f) {
                float x = fld_at(&px, f), z = fld_at(&pz, f), v = lift_at(R, x, z);
                /* et toujours au moins 70 au-dessus du sol le plus haut dans un rayon de 120 */
                float gm = -1e30f;
                for (int q = 0; q < 9; q++) {
                    float ox = q == 0 ? 0 : 120.0f * fsin(q * 0.7853982f + 1.5707963f), oz = q == 0 ? 0 : 120.0f * fsin(q * 0.7853982f), gy; int gs;
                    if (ground_at(G, x + ox, z + oz, &gy, &gs) && gy > gm) gm = gy;
                }
                if (gm > -1e29f) { float need = gm + 70.0f - (fld_at(&py, f) + v); if (need > 0) v += need; }
                if (v > m) m = v;
            }
            add[k] = m;
        }
        for (u16 k = 0; k < n; k++) {
            u8 *v = py.trk ? blk + py.to + 8 + 12 * k + 4 : blk + py.to;
            wrf(v, rdf(v) + add[k]);
        }
        /* point vise : suit le sol a cet endroit */
        u16 na = ay.trk ? ay.n : 1;
        for (u16 k = 0; k < na; k++) {
            float f = ay.trk ? rdf(blk + ay.to + 8 + 12 * k) : 0;
            float h = height(R, fld_at(&ax, f), 1e5f, fld_at(&az, f)); if (h < 0) h = 0;
            u8 *v = ay.trk ? blk + ay.to + 8 + 12 * k + 4 : blk + ay.to;
            wrf(v, rdf(v) + h);
        }
        flush(blk, len); done++;
    }
    return done;
}

/* releve la trace (x, z) des cameras de presentation, une image sur trois */
HI static void cam_path(u8 *b, CamPath *c) {
    c->n = 0;
    if (rd32(b) != 0x62726573) return;
    u8 *root = b + rd16(b + 0xC);
    const u8 *grp = dict_find(root + 8, "AnmScn(NW4R)", 0, -1);
    if (!grp) return;
    int ns = 0; dict_find(grp, "", &ns, 0);
    for (int si = 0; si < ns; si++) {
        u8 *blk = (u8 *)dict_find(grp, 0, 0, si);
        if (rd32(blk) != 0x53434E30) continue;
        u32 len = rd32(blk + 4), cb = rd32(blk + 0x24), fb = cb + 0x20; u16 nfr = rd16(blk + 0x34);
        if (!cb || fb + 0x40 > len || !nfr) continue;
        Fld px, pz; fld(&px, blk, len, fb, 0); fld(&pz, blk, len, fb, 2);
        for (int f = 0; f < nfr && c->n < MAXCAM; f += 3) { c->x[c->n] = fld_at(&px, (float)f); c->z[c->n] = fld_at(&pz, (float)f); c->n++; }
    }
}
/* ---------- point d'entree (appele par le chargeur, code relogeable) ---------- */
#ifndef HOST
/* journal du generateur : un mot tous les 16 octets a partir de 0x80003300 */
#define TG(i) (*(volatile u32 *)(0x80003300 + 16 * (i)))
typedef void *(*alloc_t)(u32 size, s32 align, void *heap);
typedef void (*free_t)(void *p);
#define GAME_ALLOC ((alloc_t)0x801c1654)
#define GAME_FREE  ((free_t)0x801c1c90)
static void *zalloc(u32 n) { void *p = GAME_ALLOC((n + 31) & ~31u, 32, 0); if (p) memset(p, 0, n); return p; }
static u32 timebase(void) { u32 t; __asm__ volatile("mftb %0" : "=r"(t)); return t; }
#else
#include <stdlib.h>
#include <stdio.h>
static u32 tg_[16];
#define TG(i) tg_[i]
static void *zalloc(u32 n) { return calloc(1, n); }
#define GAME_FREE free
#endif

/* --- grille de sol --- */
static void tri_xz_bounds(const Tri *t, float *mn, float *mx) {
    mn[0] = mx[0] = t->a.x; mn[1] = mx[1] = t->a.z;
    if (t->b.x < mn[0]) mn[0] = t->b.x; if (t->b.x > mx[0]) mx[0] = t->b.x;
    if (t->c.x < mn[0]) mn[0] = t->c.x; if (t->c.x > mx[0]) mx[0] = t->c.x;
    if (t->b.z < mn[1]) mn[1] = t->b.z; if (t->b.z > mx[1]) mx[1] = t->b.z;
    if (t->c.z < mn[1]) mn[1] = t->c.z; if (t->c.z > mx[1]) mx[1] = t->c.z;
}
static int finite3(V3 v) { return v.x == v.x && v.y == v.y && v.z == v.z && v.x > -1e6f && v.x < 1e6f && v.y > -1e6f && v.y < 1e6f && v.z > -1e6f && v.z < 1e6f; }
static int ground_ok(const Tri *t) { return is_land(t->attr & 0x1f) && finite3(t->a) && finite3(t->b) && finite3(t->c); }

static int ground_build(Ground *G, const Tri *t, u32 n) {
    float mn[2] = { 1e30f, 1e30f }, mx[2] = { -1e30f, -1e30f }, a[2], b[2];
    /* emprise : le terrain hors eau (les plans d'eau geants autour de l'ile sont rognes) */
    for (u32 i = 0; i < n; i++) {
        if (!ground_ok(&t[i]) || (t[i].attr & 0x1f) == S_WATER) continue;
        tri_xz_bounds(&t[i], a, b);
        for (int k = 0; k < 2; k++) { if (a[k] < mn[k]) mn[k] = a[k]; if (b[k] > mx[k]) mx[k] = b[k]; }
    }
    mn[0] -= 300; mn[1] -= 300; mx[0] += 300; mx[1] += 300;
    if (mn[0] > mx[0]) return 0;
    G->t = t; G->cs = 128.0f; G->x0 = mn[0] - 1; G->z0 = mn[1] - 1;
    G->nx = (int)((mx[0] - G->x0) / G->cs) + 2; G->nz = (int)((mx[1] - G->z0) / G->cs) + 2;
    u32 nc = (u32)(G->nx * G->nz);
    G->start = (u32 *)zalloc((nc + 1) * 4); if (!G->start) return 0;
    for (int pass = 0; pass < 2; pass++) {
        if (pass == 1) {
            u32 tot = 0; for (u32 c = 0; c <= nc; c++) { u32 v = G->start[c]; G->start[c] = tot; tot += v; }
            G->idx = (u16 *)zalloc(tot * 2 + 2); if (!G->idx) return 0;
        }
        u32 *fill = pass ? (u32 *)zalloc(nc * 4) : 0;
        if (pass && !fill) return 0;
        for (u32 i = 0; i < n; i++) {
            if (!ground_ok(&t[i])) continue;
            tri_xz_bounds(&t[i], a, b);
            int i0 = (int)((a[0] - G->x0) / G->cs), i1 = (int)((b[0] - G->x0) / G->cs);
            int j0 = (int)((a[1] - G->z0) / G->cs), j1 = (int)((b[1] - G->z0) / G->cs);
            if (a[0] < G->x0) i0 = 0; if (a[1] < G->z0) j0 = 0;
            if (i1 >= G->nx) i1 = G->nx - 1; if (j1 >= G->nz) j1 = G->nz - 1;
            if (b[0] < G->x0 || b[1] < G->z0 || i0 >= G->nx || j0 >= G->nz) continue;
            for (int j = j0; j <= j1; j++) for (int k = i0; k <= i1; k++) {
                u32 c = (u32)(j * G->nx + k);
                if (!pass) G->start[c]++; else G->idx[G->start[c] + fill[c]++] = (u16)i;
            }
        }
        if (pass) GAME_FREE(fill);
    }
    return 1;
}
/* sol le plus haut en (x, z) : renvoie 1 et la hauteur + la surface */
static int ground_at(const Ground *G, float x, float z, float *y, int *srf) {
    int i = (int)((x - G->x0) / G->cs), j = (int)((z - G->z0) / G->cs);
    if (i < 0 || j < 0 || i >= G->nx || j >= G->nz) return 0;
    u32 c = (u32)(j * G->nx + i); int found = 0; float best = -1e30f;
    for (u32 k = G->start[c]; k < G->start[c + 1]; k++) {
        const Tri *t = &G->t[G->idx[k]];
        if ((t->attr & 0x1f) == S_WATER) continue;          /* l'eau n'est pas un sol (objets, arbres) */
        float v0x = t->c.x - t->a.x, v0z = t->c.z - t->a.z, v1x = t->b.x - t->a.x, v1z = t->b.z - t->a.z;
        float v2x = x - t->a.x, v2z = z - t->a.z, den = v0x * v1z - v1x * v0z;
        if (den > -1e-9f && den < 1e-9f) continue;
        float u = (v2x * v1z - v1x * v2z) / den, w = (v0x * v2z - v2x * v0z) / den;
        if (u < -1e-4f || w < -1e-4f || u + w > 1.0001f) continue;
        float h = t->a.y + u * (t->c.y - t->a.y) + w * (t->b.y - t->a.y);
        if (h > best) { best = h; *srf = t->attr & 0x1f; found = 1; }
    }
    if (found) *y = best;
    return found;
}

/* --- champ de surfaces et distances (transformee de chanfrein) --- */
static void chamfer(float *d, int nx, int nz) {
    const float a = DS, b = DS * 1.4142f;
    for (int j = 0; j < nz; j++) for (int i = 0; i < nx; i++) {
        float *p = &d[j * nx + i], v = *p;
        if (i > 0 && p[-1] + a < v) v = p[-1] + a;
        if (j > 0) { float *q = p - nx; if (q[0] + a < v) v = q[0] + a;
            if (i > 0 && q[-1] + b < v) v = q[-1] + b; if (i < nx - 1 && q[1] + b < v) v = q[1] + b; }
        *p = v;
    }
    for (int j = nz - 1; j >= 0; j--) for (int i = nx - 1; i >= 0; i--) {
        float *p = &d[j * nx + i], v = *p;
        if (i < nx - 1 && p[1] + a < v) v = p[1] + a;
        if (j < nz - 1) { float *q = p + nx; if (q[0] + a < v) v = q[0] + a;
            if (i < nx - 1 && q[1] + b < v) v = q[1] + b; if (i > 0 && q[-1] + b < v) v = q[-1] + b; }
        *p = v;
    }
}
static int field_build(Field *F, const Ground *G, float tx, float tz) {
    F->x0 = G->x0; F->z0 = G->z0;
    F->nx = (int)(G->nx * G->cs / DS) + 1; F->nz = (int)(G->nz * G->cs / DS) + 1;
    u32 nc = (u32)(F->nx * F->nz);
    F->typ = (u8 *)zalloc(nc); if (!F->typ) return 0;
    for (int k = 0; k < ND; k++) { F->dist[k] = (float *)zalloc(nc * 4); if (!F->dist[k]) return 0; }
    for (int j = 0; j < F->nz; j++) for (int i = 0; i < F->nx; i++) {
        u32 c = (u32)(j * F->nx + i); float y; int s = 0;
        float x = F->x0 + (i + 0.5f) * DS, z = F->z0 + (j + 0.5f) * DS;
        if (!ground_at(G, x, z, &y, &s)) s = 0;
        F->typ[c] = (u8)s;
        F->dist[D_FAIR][c] = s == S_FAIR ? 0 : 1e9f;
        F->dist[D_GREEN][c] = (s == S_GREEN || s == S_COLLAR) ? 0 : 1e9f;
        F->dist[D_WATER][c] = s == S_WATER ? 0 : 1e9f;
        F->dist[D_BUNKER][c] = s == S_BUNKER ? 0 : 1e9f;
        float dx = x - tx, dz = z - tz;
        F->dist[D_TEE][c] = fsqrt(dx * dx + dz * dz);
    }
    for (int k = 0; k < D_TEE; k++) chamfer(F->dist[k], F->nx, F->nz);
    F->land = (u32 *)zalloc(nc * 4); if (!F->land) return 0;
    F->nland = 0;
    for (u32 c = 0; c < nc; c++) {
        int s = F->typ[c];
        if (s == S_FAIR || s == S_ROUGH || s == S_OB || s == S_BUNKER || s == S_GREEN || s == S_COLLAR) F->land[F->nland++] = c;
    }
    return 1;
}
/* tire une cellule au hasard qui verifie surf + distances ; renvoie une position (x, z) bruitee */
typedef struct { int srf_mask; float fair_lo, fair_hi, green_min, water_min, bunker_min, tee_min; } Rule;
static int pick(const Field *F, Rng *r, const Rule *q, float *x, float *z) {
    if (!F->nland) return 0;
    for (int t = 0; t < 1500; t++) {
        u32 c = F->land[rnext(r) % F->nland]; int i = (int)(c % (u32)F->nx), j = (int)(c / (u32)F->nx);
        int s = F->typ[c];
        if (!s || !(q->srf_mask & (1 << s))) continue;
        float df = F->dist[D_FAIR][c];
        if (df < q->fair_lo || df > q->fair_hi) continue;
        if (F->dist[D_GREEN][c] < q->green_min || F->dist[D_WATER][c] < q->water_min) continue;
        if (F->dist[D_BUNKER][c] < q->bunker_min || F->dist[D_TEE][c] < q->tee_min) continue;
        *x = F->x0 + (i + runi(r, 0.1f, 0.9f)) * DS; *z = F->z0 + (j + runi(r, 0.1f, 0.9f)) * DS;
        return 1;
    }
    return 0;
}

/* --- objets PMP --- */
#define PMP_N(p) rd16((p) + 0x10)
#define PMP_O(p, i) ((p) + 0x80 + 88 * (i))
static int find_obj(const u8 *p, int grp, int typ, float *x, float *y, float *z) {
    for (u32 i = 0; i < PMP_N(p); i++) {
        const u8 *o = PMP_O(p, i);
        if (rd16(o) == grp && rd16(o + 2) == typ) { *x = rdf(o + 8); *y = rdf(o + 12); *z = rdf(o + 16); return 1; }
    }
    return 0;
}

static void set_tree(u8 *o, float x, float y, float z, Rng *r) {
    int typ = rd16(o + 2);
    float sc = typ == 2 ? runi(r, 2.0f, 2.9f) : runi(r, 2.4f, 3.2f), ang = runi(r, 0, 6.2831853f);
    float c = fsin(ang + 1.5707963f), s = fsin(ang);
    wrf(o + 8, x); wrf(o + 12, y); wrf(o + 16, z);
    wrf(o + 20, sc * 0.92f); wrf(o + 24, sc); wrf(o + 28, sc * 0.92f);
    float rot[9] = { c, 0, -s, 0, 1, 0, s, 0, c };
    for (int k = 0; k < 9; k++) wrf(o + 32 + 4 * k, rot[k]);
}

/* zone devant le depart (cone vers le premier tiers du fairway) : pas d'arbre */
typedef struct { float tx, tz, dx, dz; } Cone;
static int in_cone(const Cone *c, float x, float z) {
    float vx = x - c->tx, vz = z - c->tz, t = vx * c->dx + vz * c->dz, l = vx * c->dz - vz * c->dx;
    if (l < 0) l = -l;
    return t > -60.0f && t < 1500.0f && l < 150.0f + 0.3f * (t > 0 ? t : 0);
}
static void make_cone(Cone *c, const Field *F, float tx, float tz, float gx, float gz) {
    float sx = 0, sz = 0; int n = 0;
    for (int j = 0; j < F->nz; j++) for (int i = 0; i < F->nx; i++) {
        u32 k = (u32)(j * F->nx + i);
        if (F->typ[k] != S_FAIR) continue;
        float d = F->dist[D_TEE][k]; if (d < 250 || d > 1000) continue;
        sx += F->x0 + (i + 0.5f) * DS; sz += F->z0 + (j + 0.5f) * DS; n++;
    }
    float ax = n ? sx / n : gx, az = n ? sz / n : gz, dx = ax - tx, dz = az - tz, l = fsqrt(dx * dx + dz * dz);
    if (l < 1) { dx = 0; dz = 1; l = 1; }
    c->tx = tx; c->tz = tz; c->dx = dx / l; c->dz = dz / l;
}

static int too_close(const float *pts, int n, float x, float z, float d) {
    for (int i = 0; i < n; i++) { float dx = pts[2 * i] - x, dz = pts[2 * i + 1] - z; if (dx * dx + dz * dz < d * d) return 1; }
    return 0;
}

/* place les arbres existants (meme nombre) : une partie en jeu au bord du fairway, le reste en bosquets */
#ifdef DEBUGTREES
static int dbg_[8];
#define DBG(k) dbg_[k]++
#else
#define DBG(k)
#endif
static int place_trees(u8 *p, const Ground *G, const Field *F, const Relief *R, Rng *r, int par, const Cone *cone, const CamPath *cam) {
    u32 n = PMP_N(p); int nt = 0;
    for (u32 i = 0; i < n; i++) { u8 *o = PMP_O(p, i); if (rd16(o) == 2 && (rd16(o + 2) == 2 || rd16(o + 2) == 3)) nt++; }
    float *pts = (float *)zalloc((u32)nt * 8 + 8); if (!pts) return 0;
    int lo = par == 3 ? 8 : par == 5 ? 26 : 18, hi = par == 3 ? 14 : par == 5 ? 40 : 30;
    int want_in = rint_(r, lo, hi), placed = 0;
    Rule in_play = { (1 << S_ROUGH), 60, 230, 140, 80, 60, 220 };
    Rule outside = { (1 << S_ROUGH) | (1 << S_OB), 330, 1e9f, 260, 90, 60, 300 };
    for (u32 i = 0; i < n; i++) {
        u8 *o = PMP_O(p, i);
        if (rd16(o) != 2 || (rd16(o + 2) != 2 && rd16(o + 2) != 3)) continue;
        if (rdf(o + 24) == 2.75f) {   /* rangee d'arbres en travers du fairway (v23) : reste en place, posee sur le sol */
            float ox = rdf(o + 8), oz = rdf(o + 16), gy; int gs;
            if (ground_at(G, ox, oz, &gy, &gs)) wrf(o + 12, gy);
            continue;
        }
        float x = 0, z = 0, y; int s, ok = 0;
        for (int t = 0; t < 120 && !ok; t++) {
            /* plus de place au bord du fairway (par 3 sans fairway...) : on passe aux bosquets */
            if (t == 60 && placed < want_in) want_in = placed;
            const Rule *q = placed < want_in ? &in_play : &outside;
            if (!pick(F, r, q, &x, &z)) { DBG(0); break; }
            if (too_close(pts, placed, x, z, placed < want_in ? 75.0f : 110.0f)) { DBG(1); continue; }
            if (!ground_at(G, x, z, &y, &s)) { DBG(2); continue; }
            if (s != S_ROUGH && s != S_OB) { DBG(3); continue; }
            if (in_cone(cone, x, z)) { DBG(4); continue; }
            if (near_cam(cam, x, z)) { DBG(5); continue; }
            ok = 1;
        }
        if (!ok) {   /* pas de place : l'arbre reste ou il est, pose sur le sol deforme... */
            float ox = rdf(o + 8), oy = rdf(o + 12), oz = rdf(o + 16), gy; int gs;
            float ny = ground_at(G, ox, oz, &gy, &gs) ? gy : oy + height(R, ox, oy, oz);
            /* ...sauf s'il gene la camera ou le depart : on l'enterre (invisible) */
            if (near_cam(cam, ox, oz) || in_cone(cone, ox, oz)) ny -= 3000.0f;
            wrf(o + 12, ny); continue;
        }
        set_tree(o, x, y, z, r);   /* G pointe sur les triangles deja deformes */
        pts[2 * placed] = x; pts[2 * placed + 1] = z; placed++;
    }
#ifdef DEBUGTREES
    { int ok_ = 0, oc = 0, ocam = 0, fair = 0, rough = 0, ob = 0;
      for (u32 k = 0; k < F->nland; k++) { u32 c = F->land[k]; int s = F->typ[c];
        fair += s == S_FAIR; rough += s == S_ROUGH; ob += s == S_OB;
        if (!(outside.srf_mask & (1 << s))) continue;
        if (F->dist[D_FAIR][c] < outside.fair_lo || F->dist[D_GREEN][c] < outside.green_min || F->dist[D_TEE][c] < outside.tee_min) continue;
        float x = F->x0 + ((c % (u32)F->nx) + 0.5f) * DS, z = F->z0 + ((c / (u32)F->nx) + 0.5f) * DS;
        ok_++; oc += in_cone(cone, x, z); ocam += near_cam(cam, x, z); }
      printf("cellules fair %d rough %d ob %d ; regle dehors %d dont cone %d cam %d ; cone %.0f %.0f -> %.2f %.2f\n", fair, rough, ob, ok_, oc, ocam, cone->tx, cone->tz, cone->dx, cone->dz); }
    printf("arbres: pick %d proches %d sol %d surf %d cone %d cam %d nt %d land %u\n", dbg_[0], dbg_[1], dbg_[2], dbg_[3], dbg_[4], dbg_[5], nt, F->nland);
#endif
    GAME_FREE(pts);
    return placed;
}

/* relief : bosses d'encadrement, ondulations du fairway, depart sureleve, green modele */
static void make_relief(Relief *R, const Field *F, Rng *r, int par, float tx, float tz, float gx, float gz) {
    R->F = F; R->nb = 0;
    float force = runi(r, 0.35f, 0.75f);                /* relief Wii modere : le style (terrasses, dunes, plat) vient du PC */
    int nm = rint_(r, 3, 5) + (par - 3) * 2;
    Rule mound = { (1 << S_ROUGH) | (1 << S_OB), 70, 420, 260, 230, 0, 300 };
    for (int k = 0; k < nm && R->nb < MAXB; k++) {
        Bump *b = &R->b[R->nb]; float x, z;
        if (!pick(F, r, &mound, &x, &z)) break;
        float sg = runi(r, 140, 320);
        b->x = x; b->z = z; b->a = force * (runi(r, 0, 1) < 0.25f ? -runi(r, 20, 45) : runi(r, 40, 90));
        b->k = 1.0f / (2 * sg * sg); b->r2 = 9 * sg * sg; R->nb++;
    }
    int nf = rint_(r, 1, 3) + (par - 3);
    Rule roll = { (1 << S_FAIR), 0, 0, 260, 230, 0, 260 };
    for (int k = 0; k < nf && R->nb < MAXB; k++) {
        Bump *b = &R->b[R->nb]; float x, z;
        if (!pick(F, r, &roll, &x, &z)) break;
        float sg = runi(r, 240, 420);
        b->x = x; b->z = z; b->a = force * (rnext(r) & 1 ? 1 : -1) * runi(r, 10, 25);
        b->k = 1.0f / (2 * sg * sg); b->r2 = 9 * sg * sg; R->nb++;
    }
    R->tx = tx; R->tz = tz; R->tee_a = runi(r, 20, 55); R->tee_r = 260;
    /* rayon du green : distance max d'une cellule green/collar au drapeau (borne) */
    float gr = 150;
    for (int j = 0; j < F->nz; j++) for (int i = 0; i < F->nx; i++) {
        int s = F->typ[j * F->nx + i];
        if (s != S_GREEN && s != S_COLLAR) continue;
        float dx = F->x0 + (i + 0.5f) * DS - gx, dz = F->z0 + (j + 0.5f) * DS - gz, d = fsqrt(dx * dx + dz * dz);
        if (d < 600 && d > gr) gr = d;
    }
    float ang = runi(r, 0, 6.2831853f), sl = runi(r, 0.015f, 0.035f);
    R->gx = gx; R->gz = gz; R->g_r = gr; R->g_sx = sl * fsin(ang + 1.5707963f); R->g_sz = sl * fsin(ang);
    R->ngb = rint_(r, 1, 2);
    for (int k = 0; k < R->ngb; k++) {
        float sg = runi(r, 80, 140), d = runi(r, 0, gr * 0.6f), a2 = runi(r, 0, 6.2831853f);
        Bump *b = &R->gb[k];
        b->x = gx + d * fsin(a2 + 1.5707963f); b->z = gz + d * fsin(a2);
        b->a = (rnext(r) & 1 ? 1 : -1) * runi(r, 6, 14); b->k = 1.0f / (2 * sg * sg); b->r2 = 1e30f;
    }
}

#ifndef HOST
int gen_main(u8 *arc) {
#else
int gen_run(u8 *arc, u32 seed_in) {
#endif
    for (int i = 0; i < 16; i++) if (i != 7) TG(i) = 0;
    u8 *nodes = arc + rd32(arc + 4); u32 nn = rd32(nodes + 8); const char *st = (const char *)nodes + nn * 12;
    u8 *kcl = 0, *brres = 0, *pmp = 0; u32 kcl_sz = 0; int par = 4;
    for (u32 i = 0; i < nn; i++) {
        u8 *e = nodes + 12 * i; if (e[0]) continue;
        const char *nm = st + (rd32(e) & 0xFFFFFF);
        if (starts(nm, "WS2_glf_course_") && ends(nm, ".kcl")) {
            kcl = arc + rd32(e + 4); kcl_sz = rd32(e + 8);
            /* par du trou (table du jeu) : Resort A, B, C */
            static const char *p3[] = { "_fcJP6.kcl", "_fcJP16.kcl", "_fcJP13.kcl", "_fc3.kcl", "_fc9.kcl", "_fc14.kcl" }, *p5[] = { "_fcJP12.kcl", "_fcJP7.kcl", "_fcJP3.kcl", "_fc8.kcl", "_fc13.kcl", "_fc14_.kcl" };
            for (int k = 0; k < 6; k++) { if (ends(nm, p3[k])) par = 3; if (ends(nm, p5[k])) par = 5; }
        }
        else if (starts(nm, "WS2_glf_course_") && ends(nm, ".pmp")) pmp = arc + rd32(e + 4);
        else if (starts(nm, "glf_course_") && ends(nm, ".brres")) brres = arc + rd32(e + 4);
    }
    TG(0) = (u32)kcl; TG(9) = (u32)brres; TG(10) = (u32)pmp;
    if (!kcl || !brres || !pmp) return 2;
    if (rd32(kcl) != 0x3C || rd32(brres) != 0x62726573 || rd32(pmp) != 0x504D5046) return 6;
    float tx, ty, tz, gx, gy, gz;
    if (!find_obj(pmp, 2, 0, &tx, &ty, &tz) || !find_obj(pmp, 11, 1, &gx, &gy, &gz)) return 7;
    u32 used = rd32(kcl + 12), pri_first = rd32(kcl + 8) + 0x10, n = (used - pri_first) / 16;

#ifndef HOST
    u32 t0 = timebase();
    u32 seed = t0 ^ (TG(7) * 0x9E3779B9u);
#else
    u32 t0 = 0, seed = seed_in;
#endif
    TG(7) = TG(7) + 1;
    seed ^= seed >> 16; seed *= 0x7FEB352Du; seed ^= seed >> 15; seed *= 0x846CA68Bu; seed ^= seed >> 16;
    if (!seed) seed = 1;
    TG(8) = seed;
    Rng rng = { seed };

    int ret = 3;
    Tri *tris = (Tri *)zalloc(n * sizeof(Tri));
    u16 *stk = (u16 *)zalloc(n * 2 * 16);
    Ground G; memset(&G, 0, sizeof G);
    Field F; memset(&F, 0, sizeof F);
    Relief *R = (Relief *)zalloc(sizeof(Relief));
    if (!tris || !stk || !R) goto out;
    n = read_kcl(kcl, tris, n);
    TG(1) = n; TG(3) = kcl_sz;
    ret = 8; if (!ground_build(&G, tris, n)) goto out;
    ret = 9; if (!field_build(&F, &G, tx, tz)) goto out;
    make_relief(R, &F, &rng, par, tx, tz, gx, gz);
    R->ymin = 1e30f;
    for (u32 i = 0; i < n; i++) if (ground_ok(&tris[i])) {
        float m = tris[i].a.y; if (tris[i].b.y < m) m = tris[i].b.y; if (tris[i].c.y < m) m = tris[i].c.y;
        if (m < R->ymin) R->ymin = m;
    }
    R->ymin -= 40.0f;
    R->ysea = -1e30f;
    for (u32 i = 0; i < n; i++) if ((tris[i].attr & 0x1f) == S_WATER) {
        float m = tris[i].a.y; if (R->ysea < -1e29f || m < R->ysea) R->ysea = m;
    }
    R->flat = 0; R->hcup = height_raw(R, gx, gy, gz);
    R->np = 0; R->flat = 1;
    int np = 0;
    for (u32 i = 0; i < PMP_N(pmp) && np < 8; i++) {
        const u8 *o = PMP_O(pmp, i);
        if (rd16(o) != 2 || rd16(o + 2) != 1) continue;
        float x = rdf(o + 8), y = rdf(o + 12), z = rdf(o + 16);
        R->px[np] = x; R->pz[np] = z; R->ph[np] = height(R, x, y, z); np++;   /* hauteur avec le replat du centre */
    }
    R->np = np;
    TG(11) = (u32)R->nb;
    /* hauteur du sol d'origine sous chaque objet (hors arbres) */
    u32 no = PMP_N(pmp);
    float *g0 = (float *)zalloc(no * 4 + 4); ret = 3; if (!g0) goto out;
    for (u32 i = 0; i < no; i++) {
        u8 *o = PMP_O(pmp, i); int s; g0[i] = -1e30f;
        if (!ground_at(&G, rdf(o + 8), rdf(o + 16), &g0[i], &s)) g0[i] = -1e30f;
    }
    for (u32 i = 0; i < n; i++) {
        if ((tris[i].attr & 0x1f) == S_WATER) continue;   /* surfaces d'eau : jamais deformees (restent planes) */
        tris[i].a.y += height(R, tris[i].a.x, tris[i].a.y, tris[i].a.z);
        tris[i].b.y += height(R, tris[i].b.x, tris[i].b.y, tris[i].b.z);
        tris[i].c.y += height(R, tris[i].c.x, tris[i].c.y, tris[i].c.z);
    }
    /* objets (depart, drapeau, decor) : decales de la variation du sol sous eux */
    for (u32 i = 0; i < no; i++) {
        u8 *o = PMP_O(pmp, i);
        if (rd16(o) == 2 && (rd16(o + 2) == 2 || rd16(o + 2) == 3)) continue;
        float x = rdf(o + 8), y = rdf(o + 12), z = rdf(o + 16), g1; int s;
        if (g0[i] > -1e29f && ground_at(&G, x, z, &g1, &s)) wrf(o + 12, y + (g1 - g0[i]));
        else wrf(o + 12, y + height(R, x, y, z));
    }
    GAME_FREE(g0);
    /* arbres : places sur le sol deja deforme (avant que l'ecriture KCL ne reordonne les triangles) */
    Cone cone; make_cone(&cone, &F, tx, tz, gx, gz);
    CamPath *cp = (CamPath *)zalloc(sizeof(CamPath)); ret = 3; if (!cp) goto out;
    cam_path(brres, cp); TG(14) = (u32)cp->n;
    TG(12) = (u32)place_trees(pmp, &G, &F, R, &rng, par, &cone, cp);
    GAME_FREE(cp);
    /* cameras : avant l'ecriture KCL (qui reordonne les triangles references par la grille de sol) */
    TG(13) = (u32)lift_cameras(brres, R, &G);
    ret = 4; if (0x3C + n * 76 + 0x10000 > kcl_sz) goto out;
    u32 sz = write_kcl(tris, n, rdf(kcl + 0x10), rdf(kcl + 0x38), kcl, kcl_sz, stk, n * 16);
    TG(2) = sz;
    ret = 5; if (!sz) goto out;
    TG(4) = deform_brres(brres, R);
    ret = 0;
#ifndef HOST
    TG(6) = timebase() - t0;
#endif
out:
    if (F.typ) GAME_FREE(F.typ);
    if (F.land) GAME_FREE(F.land);
    for (int k = 0; k < ND; k++) if (F.dist[k]) GAME_FREE(F.dist[k]);
    if (G.start) GAME_FREE(G.start);
    if (G.idx) GAME_FREE(G.idx);
    if (R) GAME_FREE(R);
    if (stk) GAME_FREE(stk);
    if (tris) GAME_FREE(tris);
    return ret;
}

#ifdef HOST
/* test PC : gen <archive U8 decompressee> <sortie> <graine> */
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, 2); long L = ftell(f); fseek(f, 0, 0);
    u8 *a = malloc(L); if (fread(a, 1, L, f) != (size_t)L) return 1; fclose(f);
    int r = gen_run(a, (u32)atoi(argv[3]));
    printf("retour %d prismes %u kcl %u bosses %u arbres %u sommets %u cameras %u graine %08x\n", r, tg_[1], tg_[2], tg_[11], tg_[12], tg_[4], tg_[13], tg_[8]);
    f = fopen(argv[2], "wb"); fwrite(a, 1, L, f); fclose(f);
    return r;
}
#endif
