kcl_ctor = 0x80401360;
SECTIONS {
  . = 0x800017A0;
  .text : { *(.text.stub) *(.text*) *(.rodata*) *(.sdata2*) *(.data*) *(.sdata*) *(.bss*) *(.sbss*) }
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) *(.gnu*) }
}
