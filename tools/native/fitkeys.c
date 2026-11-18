/* Portage C de scn0cam.fit_keys : retrait glouton des cles Hermite (meme algorithme). */
#include <stdlib.h>
#include <math.h>
static void tang(const double *f, const double *v, int n, double *t) {
    for (int i = 0; i < n; i++) {
        int a = i > 0 ? i - 1 : 0, b = i < n - 1 ? i + 1 : n - 1; double df = f[b] - f[a];
        t[i] = df != 0 ? (v[b] - v[a]) / df : 0.0;
    }
}
static double herm(const double *f, const double *v, const double *t, int n, double x) {
    if (x <= f[0]) return v[0];
    if (x >= f[n - 1]) return v[n - 1];
    int lo = 0, hi = n;                       /* searchsorted right - 1 */
    while (lo < hi) { int m = (lo + hi) / 2; if (f[m] <= x) lo = m + 1; else hi = m; }
    int s_ = lo - 1; if (s_ < 0) s_ = 0; if (s_ > n - 2) s_ = n - 2;
    double f0 = f[s_], f1 = f[s_ + 1], d = f1 - f0, s = d > 0 ? (x - f0) / d : 1.0, s2 = s * s, s3 = s2 * s;
    return (2 * s3 - 3 * s2 + 1) * v[s_] + (s3 - 2 * s2 + s) * d * t[s_] + (-2 * s3 + 3 * s2) * v[s_ + 1] + (s3 - s2) * d * t[s_ + 1];
}
/* idx (entree/sortie) : indices retenus ; retourne leur nombre */
int fit_keys(const double *F, const double *V, int N, int count, int *idx) {
    int m = N; for (int i = 0; i < N; i++) idx[i] = i;
    double *f = malloc(N * sizeof(double)), *v = malloc(N * sizeof(double)), *t = malloc(N * sizeof(double));
    double *se = malloc(N * sizeof(double)), *pre = malloc(N * sizeof(double)), *suf = malloc(N * sizeof(double));
    int lim = count > 2 ? count : 2;
    while (m > lim) {
        for (int k = 0; k < m; k++) { f[k] = F[idx[k]]; v[k] = V[idx[k]]; }
        tang(f, v, m, t);
        for (int k = 0; k < m - 1; k++) se[k] = 0;
        for (int k = 0, s = 0; k < N; k++) {
            while (s + 1 < m - 1 && idx[s + 1] <= k) s++;
            double e = fabs(herm(f, v, t, m, F[k]) - V[k]); if (e > se[s]) se[s] = e;
        }
        for (int k = 0; k < m - 1; k++) pre[k] = k ? (se[k] > pre[k - 1] ? se[k] : pre[k - 1]) : se[k];
        for (int k = m - 2; k >= 0; k--) suf[k] = k < m - 2 ? (se[k] > suf[k + 1] ? se[k] : suf[k + 1]) : se[k];
        double best = -1; int bj = 1;
        for (int j = 1; j < m - 1; j++) {
            int lo = j - 2 > 0 ? j - 2 : 0, hi = j + 2 < m - 1 ? j + 2 : m - 1;
            int klo = j - 3 > 0 ? j - 3 : 0, khi = j + 3 < m - 1 ? j + 3 : m - 1;
            double sf[8], sv[8], st[8]; int ns = 0;
            for (int k = klo; k <= khi; k++) if (k != j) { sf[ns] = F[idx[k]]; sv[ns] = V[idx[k]]; ns++; }
            tang(sf, sv, ns, st);
            double e = 0;
            for (int q = idx[lo]; q <= idx[hi]; q++) { double d = fabs(herm(sf, sv, st, ns, F[q]) - V[q]); if (d > e) e = d; }
            if (lo > 0 && pre[lo - 1] > e) e = pre[lo - 1];
            if (hi < m - 1 && suf[hi] > e) e = suf[hi];
            if (best < 0 || e < best) { best = e; bj = j; }
        }
        for (int k = bj; k < m - 1; k++) idx[k] = idx[k + 1];
        m--;
    }
    free(f); free(v); free(t); free(se); free(pre); free(suf);
    return m;
}
