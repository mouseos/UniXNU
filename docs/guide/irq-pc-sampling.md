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

The optional `native_irq_correlation_sample` observer is independently compiled
only when `XNU_IRQ_CORRELATION_STATS=1` (default 0) and requires
`XNU_IRQ_PC_STATS=1` plus a linked board provider. The legacy correlation
board must explicitly enable both flags; a live-PC-only board leaves the
correlation flag off. Some kernel links reject unresolved weak imports.
The observer receives user PCs
unchanged and kernel PCs unslid, with the explicit mode. It is compiled out by
the two default-off flags. The existing observer's user-PC suppression remains
unchanged. A board must independently gate and bound any recording of addresses;
user PCs can expose ASLR-sensitive information in diagnostic output.

The capability function is defined in both builds and returns 0 when disabled,
1 when enabled. This is required for kernels that reject unresolved weak imports
at link time. The observer declarations and calls remain absent in the disabled
object; the capability function does not enable sampling.

The same opt-in timer hook also calls the optional weak `native_live_pc_sample`
observer, passing the interrupted user PC and user LR, or the unslid kernel PC
and an unavailable (zero) LR. A board must separately opt into recording. These
are timer-interrupt samples, not saved scheduler state or a full profiler; the
hook does not establish image identity or CPU-time fractions. ARM64 only.
