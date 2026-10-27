# Opt-in timer-interrupted kernel PC sampling

`CONFIG_XNU_IRQ_PC_STATS=y` in a diagnostic defconfig (or an explicit
`XNU_IRQ_PC_STATS=1` environment variable when the selected defconfig does not
set the option) compiles a weak observer call at the ARM timer interrupt.
Default builds omit the call entirely. The hook supplies the interrupted PC,
unslid for kernel addresses, and an explicit user-mode flag. A missing board
observer is harmless. The hook is not a stack trace and samples only timer
interrupts, not all CPU time. Periods with interrupts masked are absent.

Changing the compile flag invalidates the arm `rtclock.o` and linked kernel;
it does not require rebuilding SDK dependencies. The observer is a weak
provider so a board can choose its target and an opt-in runtime policy. A
provider must be bounded, IRQ-safe, and must not block, allocate, or log.
The original timer handling and return values remain untouched. The enabled
mode adds overhead and must be compared with a disabled baseline.

Check the patch against the pinned XNU source and both feature gates with:
`python3 scripts/tests/check_irq_pc_hook.py --xnu-source /path/to/pinned/xnu`.
A host fixture does not establish a real XNU compile, interrupt behavior,
representative sampling, or hardware safety.
