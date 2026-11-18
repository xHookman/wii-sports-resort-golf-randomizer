/* Chargeur (zone basse fixe, 0x800017A0) : trouve wsrgen.bin dans l'archive du trou,
 * le reloge une fois (format WGEN, cf. build.py), vide les caches puis l'appelle.
 * Journal : un mot tous les 16 octets a partir de 0x80003200 (lisible dans le debogueur). */
typedef unsigned int u32; typedef unsigned char u8;
#define T(i) (*(volatile u32 *)(0x80003200 + 16 * (i)))
enum { T_ETAPE, T_APPELS, T_MGR, T_HANDLE, T_ARC1, T_ARC2, T_RET, T_CODE, T_TAS };

static int ok_ptr(u32 p) { return (p >= 0x80000000 && p < 0x81800000) || (p >= 0x90000000 && p < 0x94000000); }

static int endswith_gen(const char *s) {
    const char *e = "wsrgen.bin"; const char *a = s; int n = 0; while (*a && n++ < 128) a++;
    const char *b = e; while (*b) b++;
    while (b > e) { if (a == s || *--a != *--b) return 0; }
    return 1;
}

/* nom du trou en cours de chargement (fonction du jeu, ex. "fcJP11") */
#define COURSE_NAME ((const char *(*)(void))0x80406e80)
static const char *g_name;
/* l'archive contient-elle WS2_glf_course_<nom>.kcl ? (evite de toucher une vieille archive d'un autre trou) */
static int is_course_kcl(const char *s) {
    const char *p = "WS2_glf_course_"; while (*p) if (*s++ != *p++) return 0;
    const char *n = g_name; while (*n) if (*s++ != *n++) return 0;
    return s[0] == '.' && s[1] == 'k' && s[2] == 'c' && s[3] == 'l' && s[4] == 0;
}

/* Cherche dans une archive U8 l'entree wsrgen.bin ; renvoie le blob ou 0 (verifie toutes les bornes) */
static u32 *find_blob(u8 *arc) {
    u32 end = (u32)arc < 0x90000000 ? 0x81800000 : 0x94000000;
    if ((u32)arc + 0x40 > end || *(u32 *)arc != 0x55AA382D || *(u32 *)(arc + 4) != 0x20) return 0;
    u8 *nodes = arc + 0x20; u32 nn = *(u32 *)(nodes + 8);
    if (nodes[0] != 1 || nn < 2 || nn > 64) return 0;
    u32 strsz = *(u32 *)(arc + 8);
    if (strsz > 0x2000 || (u32)nodes + strsz > end) return 0;
    const char *st = (const char *)nodes + nn * 12;
    int same = 0;
    for (u32 i = 0; i < nn; i++) {
        u8 *e = nodes + 12 * i; u32 no = *(u32 *)e & 0xFFFFFF;
        if (!e[0] && no + 32 < strsz && is_course_kcl(st + no)) same = 1;
    }
    if (!same) return 0;
    for (u32 i = 0; i < nn; i++) {
        u8 *e = nodes + 12 * i;
        u32 no = *(u32 *)e & 0xFFFFFF;
        if (e[0] || no >= strsz) continue;
        if (endswith_gen(st + no)) {
            u32 off = *(u32 *)(e + 4), sz = *(u32 *)(e + 8);
            if (off > 0x800000 || sz < 64 || (u32)arc + off + sz > end) return 0;
            u32 *b = (u32 *)(arc + off);
            return b[0] == 0x5747454E ? b : 0;
        }
    }
    return 0;
}

/* Le jeu ne rend la MEM2 executable par aucune BAT : on copie le generateur dans un tas
 * de la MEM1 (tas EGG fixes, reperes dans les dumps), on l'y reloge puis on l'execute. */
typedef void *(*alloc_t)(u32 size, int align, void *heap);
typedef void (*free_t)(void *p);
#define GAME_ALLOC ((alloc_t)0x801c1654)
#define GAME_FREE  ((free_t)0x801c1c90)
static const u32 mem1_heaps[] = { 0x81267200, 0x80ce71f0, 0x816e1e24, 0x807e7138, 0x807e70a0 };

void loader_main(void) {
    T(T_ETAPE) = 0x4C440000;                                  /* 'LD' */
    T(T_APPELS) = T(T_APPELS) + 1;
    T(T_MGR) = T(T_HANDLE) = T(T_ARC1) = T(T_ARC2) = 0; T(T_RET) = 0xFFFFFFFF;
    u8 *arc = 0; u32 *blob = 0;
    g_name = COURSE_NAME();
    /* seulement les trous qu'on remplace : sinon on ne touche a rien (Resort B, C, classiques...) */
    {
        static const char *ours[] = { "fcJP11", "fcJP6", "fcJP12", "fcJP16", "fcJP7", "fcJP10", "fcJP9", "fcJP13", "fcJP3",
                                     "fc1", "fc3", "fc5", "fc8", "fc9", "fc12", "fc13", "fc14", "fc16" };
        int hit = 0;
        for (int i = 0; i < 18 && g_name && !hit; i++) {
            const char *a = ours[i], *b = g_name; while (*a && *a == *b) a++, b++;
            if (!*a && !*b) hit = 1;
        }
        if (!hit) { T(T_ETAPE) |= 0x40; return; }
    }
    { int k = 0; const char *q = g_name; while (q && *q && k < 16) { q++; k++; } if (!g_name || !k || k >= 16) { T(T_ETAPE) |= 0x20; return; } }
    /* 1) par le gestionnaire d'archives du golf (r13-11488 -> +12 -> +0x18) */
    u32 mgr = *(volatile u32 *)0x806F5AA0; T(T_MGR) = mgr;
    if (ok_ptr(mgr)) {
        u32 h = *(volatile u32 *)(mgr + 12); T(T_HANDLE) = h;
        if (ok_ptr(h)) {
            u32 a = *(u32 *)(h + 0x18); T(T_ARC1) = a;
            if (ok_ptr(a)) { blob = find_blob((u8 *)a); if (blob) arc = (u8 *)a; }
        }
    }
    /* 2) sinon : balayage de la MEM2 ; l'archive fraiche est celle dont le generateur n'est pas reloge */
    if (!blob) {
        T(T_ETAPE) = 0x4C440010;
        for (u32 p = 0x90000000; p < 0x93400000; p += 32) {   /* le haut de la MEM2 appartient a l'IOS : lecture interdite */
            if (*(u32 *)p != 0x55AA382D) continue;
            u32 *b = find_blob((u8 *)p);
            if (b && !b[1]) { arc = (u8 *)p; blob = b; break; }
        }
        T(T_ARC2) = (u32)arc;
    }
    if (!blob) { T(T_ETAPE) |= 2; return; }
    T(T_ETAPE) |= 0x100;
    if (blob[1]) { T(T_ETAPE) |= 4; return; }          /* deja traite (archive reutilisee) */
    /* en-tete : magic, fait, entree, nrel, taille image, decalage image, rel[nrel] */
    u32 isz = blob[4];
    u8 *src = (u8 *)blob + blob[5], *img = 0;
    for (u32 i = 0; i < sizeof(mem1_heaps) / 4 && !img; i++) {
        u32 hp = mem1_heaps[i];
        if (*(u32 *)hp != 0x806b5300) continue;          /* vtable EGG::ExpHeap */
        u8 *p = (u8 *)GAME_ALLOC(isz, 32, (void *)hp);
        if (p && (u32)p < 0x81800000) { img = p; T(T_TAS) = hp; }
        else if (p) GAME_FREE(p);
    }
    T(T_CODE) = (u32)img;
    if (!img) { T(T_ETAPE) |= 8; return; }
    for (u32 i = 0; i < isz; i++) img[i] = src[i];
    for (u32 i = 0; i < blob[3]; i++) *(u32 *)(img + blob[6 + i]) += (u32)img;
    blob[1] = 1;
    for (u32 a = (u32)img & ~31u; a < (u32)img + isz; a += 32)
        __asm__ volatile("dcbf 0,%0\n\ticbi 0,%0" :: "r"(a));
    __asm__ volatile("sync\n\tisync");
    T(T_ETAPE) |= 0x200;
    int r = ((int (*)(u8 *))(img + blob[2]))(arc);
    T(T_RET) = (u32)r;
    GAME_FREE(img);
    T(T_ETAPE) = 0x47454E00 | (u32)(r & 0xFF);                /* 'GEN' + code (0 = ok) */
}
