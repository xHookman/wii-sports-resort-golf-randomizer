/* Octree KCL : meme decoupage que kclwrite.build (Python), resultat a plat.
   Sortie : pour chaque racine, prefixe : -1 = noeud (8 enfants suivent) ; k >= 0 = feuille de k indices. */
#include <stdlib.h>
static const double *TMN, *TMX; static int MAXT; static double MINS;
static int *OUT; static long NOUT, CAP;
static void put(int v) { if (NOUT >= CAP) { CAP = CAP * 2 + 1024; OUT = realloc(OUT, CAP * sizeof(int)); } OUT[NOUT++] = v; }
static void build(double l0, double l1, double l2, double size, const int *cand, int nc) {
    int *in = malloc((nc + 1) * sizeof(int)), k = 0;
    double lo[3] = { l0, l1, l2 }, hi[3] = { l0 + size, l1 + size, l2 + size };
    for (int j = 0; j < nc; j++) {
        int i = cand[j], ok = 1;
        for (int a = 0; a < 3 && ok; a++) if (!(TMX[3 * i + a] >= lo[a] && TMN[3 * i + a] <= hi[a])) ok = 0;
        if (ok) in[k++] = i;
    }
    if (k <= MAXT || size <= MINS) { put(k); for (int j = 0; j < k; j++) put(in[j]); free(in); return; }
    put(-1);
    double h2 = size / 2;
    for (int ci = 0; ci < 8; ci++)
        build(l0 + (ci & 1) * h2, l1 + (ci >> 1 & 1) * h2, l2 + (ci >> 2 & 1) * h2, h2, in, k);
    free(in);
}
/* racines dans l'ordre z, y, x ; les candidats d'une racine sont pre-filtres par cases (elargies de 1) */
long octree(const double *tmn, const double *tmx, int ntri, const double *mn, double cube, const int *n,
            int maxt, double mins, int **out) {
    TMN = tmn; TMX = tmx; MAXT = maxt; MINS = mins; OUT = NULL; NOUT = CAP = 0;
    long nr = (long)n[0] * n[1] * n[2];
    int *cnt = calloc(nr + 1, sizeof(int)), *lo = malloc(6 * ntri * sizeof(int));
    for (int i = 0; i < ntri; i++) for (int a = 0; a < 3; a++) {
        int s = (int)((tmn[3 * i + a] - mn[a]) / cube) - 2, e = (int)((tmx[3 * i + a] - mn[a]) / cube) + 2;
        if (s < 0) s = 0; if (e > n[a] - 1) e = n[a] - 1;
        lo[6 * i + 2 * a] = s; lo[6 * i + 2 * a + 1] = e;
    }
    for (int i = 0; i < ntri; i++)
        for (int z = lo[6*i+4]; z <= lo[6*i+5]; z++) for (int y = lo[6*i+2]; y <= lo[6*i+3]; y++)
            for (int x = lo[6*i]; x <= lo[6*i+1]; x++) cnt[((long)z * n[1] + y) * n[0] + x + 1]++;
    for (long r = 0; r < nr; r++) cnt[r + 1] += cnt[r];
    int *idx = malloc((cnt[nr] + 1) * sizeof(int)), *fill = calloc(nr, sizeof(int));
    for (int i = 0; i < ntri; i++)
        for (int z = lo[6*i+4]; z <= lo[6*i+5]; z++) for (int y = lo[6*i+2]; y <= lo[6*i+3]; y++)
            for (int x = lo[6*i]; x <= lo[6*i+1]; x++) { long r = ((long)z * n[1] + y) * n[0] + x; idx[cnt[r] + fill[r]++] = i; }
    for (int z = 0; z < n[2]; z++) for (int y = 0; y < n[1]; y++) for (int x = 0; x < n[0]; x++) {
        long r = ((long)z * n[1] + y) * n[0] + x;
        build(mn[0] + x * cube, mn[1] + y * cube, mn[2] + z * cube, cube, idx + cnt[r], cnt[r + 1] - cnt[r]);
    }
    free(cnt); free(lo); free(idx); free(fill);
    *out = OUT; return NOUT;
}
void octree_free(int *p) { free(p); }
