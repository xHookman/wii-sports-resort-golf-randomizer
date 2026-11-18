    .section .text.stub,"ax"
    .globl gen_hook
/* remplace "bl 0x80401360" a 0x80417DAC */
gen_hook:
    stwu 1,-16(1)
    mflr 0
    stw 0,20(1)
    bl loader_main
    bl kcl_ctor
    lwz 0,20(1)
    mtlr 0
    addi 1,1,16
    blr
