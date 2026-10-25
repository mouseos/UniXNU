# Optional cold shared-region/root-read timing

Disabled by default. Set `CONFIG_XNU_ROOT_TIMING=y` in the selected diagnostic
configuration (passed as `XNU_ROOT_TIMING=1` to the legacy build), and add the
explicit boot argument `native-root-timing=1`. No board defaults are changed.
Both gates are required for the shared-region logs. The same boot argument
activates NativeMsdc's verified-read counters when that driver is built with
its existing verified-root support. Other argument values leave it disabled.

The wrapper around `_shared_region_map_and_slide` prints `root timing begin`
and `root timing end` with PID/name, monotonic nanoseconds, elapsed nanoseconds,
original errno and Mach result. Both success and setup/map failures retain their
original behavior. Log calls are outside the shared-region and process-fd locks.
The default compiled kernel has no clock reads or timing logs at these sites.
Changing the build gate invalidates only `vm_unix.o` and the linked kernel.

NativeMsdc exports `native_msdc_verified_timing_stats[6]`:

| Index | Cumulative value |
| --- | --- |
| 0 | Verified-root transport read attempts |
| 1 | Requested read bytes, including failed attempts |
| 2 | Read nanoseconds, including host-lock wait, DMA/cache maintenance and bounce copy |
| 3 | Block authentication attempts |
| 4 | Bytes submitted to authentication |
| 5 | Nanoseconds in `vr_verify_block` |

An optional weak `native_root_timing_snapshot` provider lets the shared-region
end log include interval differences and cumulative read/verify nanoseconds.
Without NativeMsdc, the provider is absent and those fields remain zero.
Counters aggregate all verified-root windows/processes; intervals from concurrent
callers overlap and must not be summed or labeled per-PID CPU time. Individual
atomic counters are not a transactional snapshot. In-flight operation durations
are recorded on completion. Cache hits perform no new read/authentication.
No timing logs occur on the storage hot path, and runtime-off operations call
neither the clock nor timing counter updates. Existing authentication and I/O
results are unchanged. No performance conclusion is available without a boot.

Host checks from the UniXNU root, after the official pinned XNU reference
has been populated at `refer/xnu` by the normal tree/source setup:

```sh
python3 scripts/tests/check_root_startup_timing.py
sh drivers/NativeMsdc/tests/run-timing.sh
sh drivers/NativeMsdc/tests/run.sh
sh drivers/NativeMsdc/tests/run-cache.sh
bash -n scripts/build-xnu-4k-baseline.sh
```

For a separately prepared reference checkout, use the explicit form:

```sh
python3 scripts/tests/check_root_startup_timing.py --xnu-source /absolute/path/to/xnu
```

The selected Git checkout must have HEAD exactly equal to the XNU `commit` in
`feeds.toml`. Missing sources or mismatched revisions fail with an actionable
error; the test does not fetch, search external cache directories, or modify the
checkout. It reads the committed blob at that verified revision, applies the
canonical patches in a temporary directory, then compiles the actual wrapper/helpers with mocked APIs (ASan/UBSan).
It does not replace a real Apple SDK/kernel build.
