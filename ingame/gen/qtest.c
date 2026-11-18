/* Test sous qemu-ppc : reloge wsrgen.bin comme le chargeur et l'execute sur une archive decompressee. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
typedef unsigned int u32;
static void *my_alloc(u32 sz, int al, void *h) { void *p = 0; posix_memalign(&p, 32, sz); return p; }
static void my_free(void *p) { free(p); }
static void tramp(u32 at, void *fn) {
    u32 a = (u32)fn, *p = (u32 *)at;
    p[0] = 0x3d800000 | (a >> 16); p[1] = 0x618c0000 | (a & 0xffff); p[2] = 0x7d8903a6; p[3] = 0x4e800420;
}
int main(int argc, char **argv) {
    void *m = mmap((void *)0x80000000, 0x500000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_FIXED | MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (m != (void *)0x80000000) { puts("mmap"); return 1; }
    tramp(0x801c1654, my_alloc); tramp(0x801c1c90, my_free);
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, 2); long L = ftell(f); fseek(f, 0, 0);
    unsigned char *arc = mmap(0, (L + 0xfff) & ~0xfff, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); fread(arc, 1, L, f); fclose(f);
    unsigned char *nodes = arc + *(u32 *)(arc + 4); u32 nn = *(u32 *)(nodes + 8);
    const char *st = (const char *)nodes + nn * 12; u32 *blob = 0;
    for (u32 i = 0; i < nn; i++) { unsigned char *e = nodes + 12 * i;
        if (!e[0] && !strcmp(st + (*(u32 *)e & 0xFFFFFF), "wsrgen.bin")) blob = (u32 *)(arc + *(u32 *)(e + 4)); }
    if (!blob) { puts("pas de blob"); return 1; }
    unsigned char *img = (unsigned char *)blob + blob[5];
    for (u32 i = 0; i < blob[3]; i++) *(u32 *)(img + blob[6 + i]) += (u32)img;
    printf("img %p entry %x nrel %u\n", img, blob[2], blob[3]); fflush(stdout);
    int r = ((int (*)(unsigned char *))(img + blob[2]))(arc);
    volatile u32 *S = (u32 *)0x80003300; 
    printf("retour %d  prismes %u  kcl %u/%u  sommets %u  objets %u\n", r, S[4], S[8], S[12], S[16], S[20]);
    f = fopen(argv[2], "wb"); fwrite(arc, 1, L, f); fclose(f);
    return r;
}
