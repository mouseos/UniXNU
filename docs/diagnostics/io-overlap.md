# Bounded signature-preparation and block-offer trace

This diagnostic is opt-in and does not change verification. Build the kernel
with `XNU_ROOT_TIMING=1 XNU_NATIVE_CS_HASH_CACHE=1 XNU_IO_OVERLAP_TRACE=1`; the latter
defaults to 0 and requires both other flags. The a04br3 defconfig enables the
signature hash cache. Boot with `native-io-trace=1` and enable the device's
existing periodic reporter (a04br3: `pl=1`, ten seconds). Do not also enable
`native-root-timing` merely to collect this trace: that separate, older
instrumentation has different identity/telemetry properties. The image must
contain the matching NativeMsdc and device reporter commits. A clean clone with
its pinned submodules and the standard UniXNU/device build retains the input
sources; use the normal boot image construction and size/boot-argument checks.

XNU records prepare entry and exit independently. They have the same operation
number, anonymous per-boot vnode ID, PID/TID and boot-relative ns; an entry has
`end=0`, a finished record has the file byte offset, the sum of vn_rdwr bytes
**offered**, the number of calls and final error. All offers in one preparation
are contiguous from `base`. Some or all of an errored final offer may not have
been read. Entry records permit detection of work still in flight; missing exit
can also be due to loss or a truncated log. The anonymous ID comes from a
bounded 64-entry `{vnode address, vnode vid}` comparison table; neither address
nor vid is printed, and no vnode reference is retained. ID assignment is local
to a boot, not persistent across boots; a reused address with a new vid gets a
new ID. VID wrap/ABA is not ruled out. Paths, names and data are not printed,
but file offsets and known image geometry can still identify files.

Both entry and exit use a try-lock and never log on the I/O path. At most 32
records per report are kept; `full`, `busy`, and `keys_full` reveal omitted
records. A missing ID on table exhaustion or lock contention is discarded.
The registry is never evicted. No table reset occurs during a boot. The reporter
copies into a fixed snapshot under the lock and prints outside it; concurrent
report attempts are excluded. It runs on the device's existing reporter thread.
The trace is restricted to read-only vnodes and starts after validation and
allocation, just before the preparation loop. A coalesced waiter never enters
the preparer and therefore is not counted as an I/O producer. Counters and
records can be split across reports, and interrupted boots can lack an end.

NativeMsdc independently reports up to 32 eligible verified read-only window
offers per ten-second interval; see NativeMsdc README for details. Offers are
recorded before queue admission and completion validation, so later rejection
is possible; they are not accepted requests or completed transfers. Once the
buffer is full, producers skip clock, PID/TID and record-lock work and increment
an atomic loss counter. Full and contention counts are exact across quiescent
drains but independent samples; boundary races can shift a loss to an adjacent
interval. Both streams
use `mach_absolute_time` converted to ns. Reporter output contributes overhead;
32 records per stream per reporting interval are a hard line cap, not a complete
census. The first records of a busy interval are favored. The finite buffers,
try-lock losses, read-ahead, caching and asynchronous execution all bias results.
No data bytes or signature-validation decisions are altered.

Analyze one boot at a time:

```
python3 scripts/analyze-io-overlap.py path/to/uart.log
```

Only complete framed reports are consumed; multiple boots with repeated report
sequence numbers are refused. Two a04br3 preloader-start markers are also
refused, but a capture that misses boot markers may still combine boots. `file_range_overlaps` compares offered contiguous
file ranges for completed preparations sharing one boot-local ID; it states
whether their execution intervals overlap and includes errors. `block_range_overlaps`
compares sampled offers from different execution threads in the same window,
regardless of time, and gives their time separation; this alone does not show
concurrent requests.
`temporal_thread_candidates` counts sampled same-PID/TID offers inside a prepare
interval without a timing margin. It does not prove a mapping from file offsets
to block offsets or causation. Missing matches mean unknown, not no I/O.
Inspect `coverage`, loss counters (including the separately reported loss
fields observed in incomplete headers), invalid CS events and incomplete frames
before drawing conclusions. A missing overlap is never proof of absence, even
when the reported loss counters are zero: capture is sampled and the reporter
discards the final partial interval when stopped. Its stop marker is surfaced
as `stopped_with_unreported_final_interval`; the discarded losses cannot be
counted, and an interrupted log may also omit that marker.

Host checks use the pinned XNU checkout:

```
python3 scripts/tests/check_io_overlap.py --xnu-source /path/to/pinned/xnu
python3 scripts/tests/test_io_overlap_analysis.py
python3 scripts/tests/check_root_read_batch.py --xnu-source /path/to/pinned/xnu
python3 scripts/tests/check_root_coalesce.py --xnu-source /path/to/pinned/xnu
```

For NativeMsdc also run `python3 tests/check-read-attribution.py` and compile
and run `tests/overlap-buffer.cpp` with C++17, pthreads and ASan/UBSan. These
are host mocks, not an actual XNU, APFS, UART or device test.

The reviewed a04br3 pairing is device commit
`481ed49fafc444c6b5c2c6aa11a9fcfbec98ec99` and its pinned ArmCpu commit
`85d06a5248a4516c777763d195866a2362e5d7b0`; the UniXNU gitlink pins the
corresponding NativeMsdc commit. Both device and UniXNU branches are
`wip/io-overlap-trace` in their respective mouseos repositories. Select these
explicitly when reproducing the host and later target builds.
