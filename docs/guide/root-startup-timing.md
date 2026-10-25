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


### Signature registration timing

The same compile/runtime gates also collect `F_ADDFILESIGS`,
`F_ADDFILESIGS_RETURN`, `F_ADDFILESIGS_INFO`, and
`F_ADDFILESIGS_FOR_DYLD_SIM` timing; `F_ADDSIGS` is excluded.
There is no signature-path UART output. At the first two gated shared-region
begins, `root signature timing` emits cumulative counters for at most the first
four distinct processes, keyed by `proc_uniqueid(p)` (at most eight lines per
boot). Output includes both `pid` and the full 64-bit `uniqueid`; PID reuse
therefore cannot merge different processes. Zero unique IDs are excluded.

`whole_ns` starts at the signature case, after fd lookup/MAC fcntl checks, and
ends after the existing fd cleanup. `bytes` sums successfully copied-in
`fs_blob_size` requests, including later failures and already-present blobs.
`read_count`, `read_requested_bytes`, `read_ns` measure `vn_rdwr` calls, including
failed calls; requested bytes include allocator page rounding, not actual bytes
read. `add_count`, `add_bytes`, `add_ns` measure `ubc_cs_blob_add` calls, including
failures. `errors` counts nonzero final results. Existing-blob fast paths have no
read/add sample. Whole includes both stages, so these times must not be added.
Snapshots are relaxed concurrent aggregates of completed cases, not a transaction
or exclusive CPU time; an ongoing call may be partly reflected. Earlier reports
may omit a PID whose first signature case has not yet started. Runtime gate alone
does not enable a compile-disabled kernel. Toggle invalidation covers both
`vm_unix.o` and `kern_descrip.o` plus the kernel link output.

Run the actual shipped signature-case mock fixture with the pinned source:

```sh
python scripts/tests/check_root_signature_timing.py --xnu-source /path/to/pinned/xnu
python scripts/tests/check_root_startup_timing.py --xnu-source /path/to/pinned/xnu
```

The fixture compiles both feature modes with ASan/UBSan and exercises strict
runtime flags, all signature variants, failure cleanup, cached signatures,
rounded reads/residual zeroing, error preservation, bounded summaries, and separation of identical PIDs with
different 64-bit process unique IDs.


### Warm-source patch updates

`build-xnu-4k-baseline.sh` calls `scripts/prepare-xnu-patches.py` before source
header preparation. A stamp in `.cache/xnu-work/.git/unixnu-patchset.json` hashes
the XNU pin and the ordered path/content of all canonical XNU and NativePrelink
patches. A changed or missing stamp stages the complete patchset against the
verified pin in a temporary checkout. Only after all patches apply successfully
are changed files synchronized to the managed work source; identical bytes keep
their mtimes. Previously recorded patch-created files are removed when absent
from the new result. Ownership comes from the old HEAD commit tree
(`git ls-tree -rz`), plus the previous manifest, never from the live index.
Before any live mutation, every managed path is checked for parent symlinks,
non-directory parents, non-file targets, and unowned destination collisions.
The managed work/Git directory must also have no symlink parents below the
resolved build root. Unknown user files, including staged additions and restored
headers, are preserved. A staged addition is not implicitly owned by this helper.
On first migration without a stamp, a canonical patch addition that already
exists is adopted only when its type, bytes, and mode exactly match the staged
canonical result. Different legacy content cannot be proven owned and is rejected
without overwriting it; use recorded source provenance rather than guessing.
After a stamp exists, new unowned collisions are rejected even for matching bytes.
The index is preserved when the pin is unchanged; changing the pin requires a
clean index and resets Git metadata without resetting source mtimes.
No object, SDK, dependency archive, or header-install stamp is deleted here.
The normal build still recompiles changed sources and performs its feature-mode
object invalidation. Do not edit the managed work source as an implementation
source; canonical patches remain authoritative.

```sh
python scripts/tests/check_xnu_patchset_refresh.py
```

This host-only fixture covers a pre-stamp old-patch tree migrating to changed
contents at the same patch path, patch ordering, stable mtimes, patch additions
and removals, failed-stage isolation, pin validation/change, and interrupted-sync
manifest recovery while retaining object and SDK sentinels. It also verifies
staged/untracked collision rejection, preservation of unrelated staged additions
and their index entries, matching legacy-addition adoption, and rejection of an
external parent symlink before any live source/stamp mutation.


### Blob-add internal intervals and duplicate observations

The same strict compile/runtime gates split `ubc_cs_blob_add` into disjoint wall
intervals. All original results, `EAGAIN` success normalization, ownership and
cleanup remain unchanged. No diagnostic UART is performed on this path. The
existing at-most-eight `root signature timing` summary lines append:

- `blob_count` / `blob_errors`: completed blob-add calls and final nonzero results.
- `init_count` / `init_ns`: the initial `cs_blob_init_validated` call only,
  including that callee's validation, hashing and internal failure cleanup.
- `pre_ns`: after init returns and before MACF is entered; includes first-stage
  reconstitution, RO allocation/update, and monitor registration when compiled.
- `mac_count` / `mac_ns`: `mac_vnode_check_signature` only, including failures.
  Both remain zero when MACF is not compiled or an earlier operation fails.
- `post_ns`: after MACF returns (or after the CONFIG_MACF block when absent)
  through subsequent processing, vnode lock acquisition/work, and original
  cleanup. Early errors switch to POST at their cleanup entry; initial-init
  failure switches before its original error print and direct return.

These four intervals partition the instrumented blob-add body through its
original cleanup; the final diagnostic collector itself is outside that time.
They are elapsed wall times, including nested I/O, scheduling and lock waits,
not exclusive CPU time. `post_ns` does not isolate lock contention from other
postprocessing. Blob calls from exec or other paths are counted too, so their
counts need not equal the F_ADDFILESIGS `add_count`. Both collectors share the
same four process-unique-ID slots. Compilation-mode invalidation now also covers
`ubc_subr.o`.

A 64-entry, first-seen table records scalar vnode address, `vnode_vid` and signed
file base offset while the caller still owns the vnode. It retains no vnode or
process reference and never dereferences the stored address later. `vnode_cross`
counts observations of an identity already observed for a different process
unique ID; it does not prove that calls ran simultaneously, or that validation
can safely be reused. A different vid or base offset is a different identity.
`duplicate_vnode` (hex), `duplicate_vid`, `duplicate_base` (hex) and
`duplicate_peer` (process unique ID) show the last such observation for that slot.
The address is diagnostic identity metadata, not a dereferenceable pointer.

A nonblocking try-lock protects only this bounded table, after original cleanup.
Contention or table exhaustion increments `vnode_dropped`; phase totals still
accumulate. Consequently duplicate counts are conservative samples. Relaxed
concurrent summaries can observe partial counter updates or a mixed last-metadata
snapshot; they do not add any new output lines beyond the existing cap.

```sh
python scripts/tests/check_root_blob_timing.py --xnu-source /path/to/pinned/xnu
```

This compiles the actual patched blob-add body and collectors with API mocks in
both compile modes and MACF on/off, under ASan/UBSan. It checks strict flags,
init/MACF/pre/post failures, cleanup and EAGAIN normalization, disjoint intervals,
vid/offset and process-identity separation, bounded/drop behavior, concurrent
updates, and summary output after the original vnode has been freed.
