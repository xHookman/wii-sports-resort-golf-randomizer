/* Compresseur Yaz0 (meme algorithme glouton que pack.py, en C) : chaines de hachage sur 3 octets */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define WIN 0x1000
#define HBITS 15
size_t yaz0_compress(const uint8_t *src, size_t n, uint8_t *out) {
    int32_t *head = malloc(sizeof(int32_t) << HBITS), *prev = malloc(sizeof(int32_t) * (n + 1));
    for (size_t i = 0; i < (1u << HBITS); i++) head[i] = -1;
    memcpy(out, "Yaz0", 4); out[4] = n >> 24; out[5] = n >> 16; out[6] = n >> 8; out[7] = n; memset(out + 8, 0, 8);
    size_t o = 16, i = 0;
    #define H(p) ((((uint32_t)src[p] << 10) ^ ((uint32_t)src[p + 1] << 5) ^ src[p + 2]) & ((1u << HBITS) - 1))
    #define INS(p) do { if ((p) + 3 <= n) { uint32_t h_ = H(p); prev[p] = head[h_]; head[h_] = (int32_t)(p); } } while (0)
    while (i < n) {
        size_t fpos = o++; uint8_t flags = 0;
        for (int bit = 0; bit < 8 && i < n; bit++) {
            size_t blen = 0, bpos = 0;
            if (i + 3 <= n) {
                size_t lim = n - i < 0x111 ? n - i : 0x111; int tries = 0;
                for (int32_t p = head[H(i)]; p >= 0 && i - (size_t)p <= WIN && tries < 64; p = prev[p], tries++) {
                    if (src[p] != src[i] || src[p + 1] != src[i + 1] || src[p + 2] != src[i + 2]) continue;
                    size_t l = 3; while (l < lim && src[p + l] == src[i + l]) l++;
                    if (l > blen) { blen = l; bpos = p; if (l == lim) break; }
                }
            }
            if (blen >= 3) {
                size_t d = i - bpos - 1;
                if (blen >= 0x12) { out[o++] = (d >> 8) & 0x0F; out[o++] = d & 0xFF; out[o++] = blen - 0x12; }
                else { out[o++] = ((blen - 2) << 4) | ((d >> 8) & 0x0F); out[o++] = d & 0xFF; }
                for (size_t k = 0; k < blen; k++) INS(i + k);
                i += blen;
            } else { flags |= 0x80 >> bit; out[o++] = src[i]; INS(i); i++; }
        }
        out[fpos] = flags;
    }
    free(head); free(prev);
    return o;
}
