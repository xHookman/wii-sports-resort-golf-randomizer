kcl_ctor = 0x80401360;
MEMORY { lo (rx) : ORIGIN = 0x800017A0, LENGTH = 0x1860
         hi (rx) : ORIGIN = 0x800031A0, LENGTH = 0x640 }
SECTIONS {
  .text : { *(.text.stub) *(.text) *(.text.*[!i]) } > lo
  .texthi : { *(.text.hi) *(.rodata*) *(.sdata2*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) } > hi
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) *(.gnu*) }
}
