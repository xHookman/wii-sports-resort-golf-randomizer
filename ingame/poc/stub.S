    .section .text.stub,"ax"
    .globl poc_hook
/* remplace "bl 0x80401360" a 0x80417DAC : deforme le trou puis cree l'objet collision */
poc_hook:
    stwu 1,-16(1)
    mflr 0
    stw 0,20(1)
    bl poc_main
    bl kcl_ctor
    lwz 0,20(1)
    mtlr 0
    addi 1,1,16
    blr
