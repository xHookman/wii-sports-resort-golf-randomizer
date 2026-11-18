/* Test sous qemu-ppc du chargeur complet : chemin "balayage MEM2". */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
typedef unsigned int u32;
static void *my_alloc(u32 sz, int al, void *h) { return mmap(0, (sz + 0xfff) & ~0xfff, 7, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); }
static void my_free(void *p) { }
static void tramp(u32 at, void *fn) { u32 a = (u32)fn, *p = (u32 *)at;
    p[0] = 0x3d800000 | (a >> 16); p[1] = 0x618c0000 | (a & 0xffff); p[2] = 0x7d8903a6; p[3] = 0x4e800420; }
int main(int argc, char **argv) {
    if (mmap((void *)0x80000000, 0x1800000, 7, MAP_FIXED | MAP_PRIVATE | MAP_ANONYMOUS, -1, 0) != (void *)0x80000000) return 1;
    if (mmap((void *)0x90000000, 0x4000000, 7, MAP_FIXED | MAP_PRIVATE | MAP_ANONYMOUS, -1, 0) != (void *)0x90000000) return 1;
    tramp(0x801c1654, my_alloc); tramp(0x801c1c90, my_free);
    *(u32 *)0x80401360 = 0x4e800020;
    /* COURSE : fonction du jeu qui renvoie le nom du trou */
    const char *nm = argc > 4 ? argv[4] : "fcJP11"; strcpy((char *)0x80500000, nm);
    *(u32 *)0x80406e80 = 0x3c608050; *(u32 *)0x80406e84 = 0x60630000; *(u32 *)0x80406e88 = 0x4e800020; *(u32 *)0x81267200 = 0x806b5300;                      /* kcl_ctor = blr */
    FILE *f = fopen(argv[1], "rb"); size_t n = fread((void *)0x800017A0, 1, 0x1860, f); fclose(f);
    f = fopen(argv[2], "rb"); n = fread((void *)0x92be2dc0, 1, 0x1000000, f); fclose(f);
    /* une copie perimee (deja relogee) plus bas, pour verifier qu'elle est ignoree */
    memcpy((void *)0x91000000, (void *)0x92be2dc0, n);
    ((void (*)(void))0x800017A0)();
    for (int i = 0; i < 9; i++) printf("T%d=%08x ", i, *(u32 *)(0x80003200 + 16 * i)); puts("");
    for (int i = 0; i < 11; i++) printf("G%d=%08x ", i, *(u32 *)(0x80003300 + 16 * i)); puts("");
    if (argc > 3) { FILE *o = fopen(argv[3], "wb"); fwrite((void *)0x91000000, 1, n, o); fclose(o); }
    ((void (*)(void))0x800017A0)();                        /* 2e appel : l'archive est deja relogee */
    printf("2e appel : etape %08x arc %08x\n", *(u32 *)0x80003200, *(u32 *)0x80003250);
    return 0;
}
