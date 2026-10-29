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
begins, tagged `RST` records emit cumulative counters for at most the first
four distinct processes, keyed by `proc_uniqueid(p)` (at most eight logical
summaries, six records each, hence 48 lines per boot). Output includes both
`p` (PID) and the full 64-bit `u` (unique ID); PID reuse
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
existing at-most-eight logical summaries include these counters (compact wire
keys are listed below):

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
snapshot. The compact transport uses at most 48 newline-terminated records as
described below; it does not log on the signature/blob-add path.

```sh
python scripts/tests/check_root_blob_timing.py --xnu-source /path/to/pinned/xnu
```

This compiles the actual patched blob-add body and collectors with API mocks in
both compile modes and MACF on/off, under ASan/UBSan. It checks strict flags,
init/MACF/pre/post failures, cleanup and EAGAIN normalization, disjoint intervals,
vid/offset and process-identity separation, bounded/drop behavior, concurrent
updates, and summary output after the original vnode has been freed.


### Compact console-safe timing records

The XNU console print buffer retains only 255 bytes per printf unless synchronous
drain is enabled; a longer line also loses its newline. The original extended
summary hit exactly this limit in raw UART, so adjacent prefixes were concatenated.
The console-safe format uses six tagged printf calls per logical summary. Each
record is at most 200 bytes including its newline even with maximum-width numeric
values, and each fits a single normal console ring reservation (256-byte chunk).
No diagnostic spin/try-lock is held while printing. A report's records may be
ordered among another report's records; `q` (report 1 or 2), `p` and `u` identify
which logical summary owns each record. There is no promise of a transactional
snapshot across those records. Existing `root timing begin/end` records are
unchanged; the observed root-end records were 233/237 bytes and were not truncated.

| Record | Compact keys and meaning |
| --- | --- |
| `RST sig` | `c` count, `b` bytes, `w` whole_ns, `e` errors, `rc` read_count, `rn` read_ns |
| `RST add` | `rb` read_requested_bytes, `ac` add_count, `ab` add_bytes, `an` add_ns, `bc` blob_count, `be` blob_errors |
| `RST phase` | `ic` init_count, `in` init_ns, `pre` pre_ns, `mc` mac_count, `mn` mac_ns, `post` post_ns |
| `RST hash` | `rc` preparation read calls, `rb` requested read bytes, `rn` read ns, `on` original-hash ns, `dn` derived-hash ns, `bat` selected-batch calls |
| `RST prep` | `pc` prepare calls, `pb` effective requested code-limit bytes, `pn` prepare ns, `pe` prepare errors, `hit` completed-cache reuse |
| `RST vnode` | `cross` vnode_cross, `drop` vnode_dropped, `a` duplicate_vnode (hex), `v` duplicate_vid, `o` duplicate_base (hex), `peer` duplicate_peer |

```sh
python scripts/tests/check_root_timing_console.py --xnu-source /path/to/pinned/xnu
```

The fixture uses the pinned XNU `__doprnt`, `printnum`, and console print-buffer
functions. It reproduces the original 255-byte truncation/newline loss, then
verifies all shipped records against libc formatting at maximum counter widths,
including the vararg types, and checks one complete <=200-byte console write per
record. Concurrent reporters produce exactly one of each tag for each q/process
pair, bounded to 48 records. It runs under ASan/UBSan with printf format checking.


### Opt-in native4k registration coalescing

`native-cs-coalesce=1` enables registration coalescing only when the existing
`XNU_NATIVE_CS_HASH_CACHE=1` support is compiled, the native page shift is 12,
the signature hash shift is 14, and `vnode_vfsisrdonly` reports a read-only mount.
Absent/non-one flags and writable vnodes retain the original preparation path.
No board defaults or signature checks are disabled. The canonical functional
change is `zzy-native4k-coalesce.patch`, applied after the timing and native4k
patches. There is no on-demand vnode I/O in VM page validation.

Each call still performs its own structure/CodeDirectory/MACF/auxiliary validation.
After that, a 64-entry active registry coalesces producers by vnode plus vid.
Waiters sleep outside vnode/VM locks. The registry mutex is held only for table
lookup/claim/release, never through validation, I/O, or publication. A full table
falls back to the original path. No failed or partially prepared cache is stored
in the registry, and entries are cleared/woken on every post-acquisition exit.
The caller's existing vnode reference spans the whole call; no reference remains
in the registry after release.

After waiting, the code rechecks the read-only mount/vid and calls the shared
original duplicate matcher under vnode_lock. Reuse requires the original range,
size, flags, signer/platform/team, CPU compatibility and CD hash conditions, plus
an already-published native4k hash array. It preserves the original CPU update,
generation refresh, temporary cleanup and EAGAIN-to-success normalization.
Mismatches or missing arrays do not short-circuit preparation; the original final
matcher still runs after preparation, preserving its error precedence. Stack PAC
sign/auth covers the newly blocking wait/lookup, and the original publication
PAC flow remains. A successful producer still verifies all original 16KiB blocks,
derives 4KiB hashes from the same verified bytes and publishes only the completed
read-only array.

The existing root-timing compile/runtime gate separately enables `RST prep`.
`pc` counts actual `cs_native4k_prepare` calls, including no-op/error calls; `pn`
measures that call alone, excluding gate wait and the telemetry collector. `pb`
sums the effective requested signing limit for 16KiB signatures, using nonzero
`codeLimit64` when its version permits it, otherwise `codeLimit`. It is requested
bytes, not completed I/O/verified bytes: rejected/failed preparation may read less
or nothing. `hit` counts early reuse of completed native4k arrays. All six short
records remain <=200 bytes and the total report budget is now 48 records per boot.

```sh
python scripts/tests/check_root_coalesce.py --xnu-source /path/to/pinned/xnu
python scripts/tests/check_root_coalesce_headers.py --xnu-source /path/to/pinned/xnu
```

The first fixture executes the actual gate, matcher and blob-add function under
ASan/UBSan in three cache/timing configurations. Four callers include real blocked
waiters and prepare once; a failed producer wakes a waiter which retries. It also
checks separate-vnode parallelism, strict flags, writable exclusion, original
mismatch/error precedence, CPU/generation updates, missing-cache fallback, bounded
registry fallback and effective codeLimit64 telemetry. The second compiles the
actual gate functions to arm64 Mach-O against the real pinned XNU headers (no API
mocks), including static LCK declarations, their mid-translation-unit include
position, msleep/wakeup and vnode APIs. This is not a complete SDK kernel/PAC
build/link or runtime performance proof; those remain owner validation.


### Opt-in 256KiB native4k preparation reads

`native-cs-read-batch=1` selects a fixed 256KiB scratch read buffer in
`cs_native4k_prepare`, only for a read-only vnode mount and with the existing
native4k hash-cache support compiled. The default/absent/non-one flag and writable
mounts retain 16KiB scratch reads. The independent canonical patch is
`zzx-native4k-read-batch.patch`, ordered after root timing and before registration
coalescing. No board flags, SDK setup, VM fault paths or original hash policy are
changed. The tracked patchset refresher handles the changed source incrementally.

Each original 16KiB block is still authenticated separately with its signed
expected hash. Only after that block passes are its 4KiB digests derived from the
same scratch buffer. Every tail is bounded by its actual read/original block
length, never uninitialized scratch padding. All original blocks must pass and
`vm_map_protect(..., VM_PROT_READ, TRUE)` must succeed before the array is published.
Read errors, residual bytes, missing/bad hashes, allocation errors and RO-protect
failure free private storage without publishing. Signed offset and last-byte
span overflow are rejected before issuing the affected read.

The independent root-timing compile/runtime gates add `RST hash` to the existing
bounded summaries: `rc`/`rb` count requested vn_rdwr calls/bytes including failed
requests; `rn` times vn_rdwr only; `on` times original-hash init/update/final only;
`dn` times each derived-hash init/update/final only, excluding digest memcpy.
These are disjoint wall intervals, not exclusive CPU time. They exclude allocation,
lookup/compare/copy, protection and final telemetry aggregation. `bat` counts helper
calls which selected the 256KiB buffer; early rejects or storage-allocation failures
before that selection have no batched sample. Metrics from failed calls still
accumulate. No per-read or per-hash UART is emitted. There are six <=200-byte
records per logical summary, at most 48 records per boot.

```sh
python scripts/tests/check_root_read_batch.py --xnu-source /path/to/pinned/xnu
```

This runs the actual ordered-patched helper with real OpenSSL SHA-256 under
ASan/UBSan, with timing compiled both off and on. It checks strict batch/root flags,
read-only scope, 4KiB/16KiB/256KiB boundaries and multi-batch tails, truncated-digest
strides, original-buffer derivation after backing bytes change, corruption of each
original block, failed/short first/middle/last reads, null hashes, allocation and
protection failures, signed offset overflow, compatibility rejections and no
publication on any failure. The existing collector and actual-XNU-console fixtures
also cover accumulated stage counters and the widened 48-record output budget.

This is an experimental throughput comparison. No boot-time reduction or real
hardware performance improvement is claimed until measured with a matching payload.

#### 通常読みとバッチ読みの比較上の制約

両経路とも署名付き16 KiBブロックを位置順に照合し、成功したブロックと
同一の読み込みバッファから4 KiBハッシュを導出する。全ブロック成功と
読み取り専用保護の前にハッシュ配列を公開しない。ただし、バッチ経路は
最大256 KiBを一度に読み込んでから先頭の署名を照合する。したがって、
後方の読み込みエラーと先頭側の署名不一致が同時にある場合のエラーの
優先順位や、失敗までの読み込み量は16 KiB経路と異なり得る。

`scripts/tests/check_native4k_page_validation.py --xnu-source /path/to/pinned/xnu`
は固定XNUの実prepareと実ページ検証関数をSHA-256で実行し、通常・バッチの
生成ハッシュ一致、各署名ブロックのデータと期待値の改変拒否、各完全4 KiB
ページの改変検出を確認する。これはXNU実機上のI/O、キャッシュ整合性や
性能を証明しない。通常読みに比べバッチは読み込み要求をまとめるが、
署名付き範囲の読み込みとハッシュ計算を省略しない。

比較試験はread-batchパッチ適用前の実関数も同じ入力・SHA-256期待値で
検査し、既定off・onのページ検証は計時をコンパイルした場合としない場合の
両方を実行する。末尾の部分ページにはNXが付き、署名対象の変更はtaintと
なる。`ubc_cs_blob_add` の呼出し順序は、構造検証と構成に応じたMACF・
code-signing monitor検査の後にprepareを実行する。hostのモックは実際の
AMFIやカーネルリンクを証明しない。バッチ読みの一時バッファは16 KiBから
256 KiBへ増えるため、低メモリ時の割当て・実機の動作は別途確認が必要。

固定版の比較試験は、read-batchパッチ適用前と適用後の既定offについて、
フラグなし・0・1以外の16 KiB読み、先頭・次ブロックのread error、短読、
ハッシュ欠落、不一致を同じ条件で実行し、エラーと未公開を確認する。
さらに前方ブロックの不一致と後方のread errorを同時に模擬し、通常経路は
不一致を、バッチ経路は先読みのエラーを返すことを確認する。ホスト上の
模擬readであり、実ファイルシステムやAMFIの挙動を再現する試験ではない。

原本および既定offを各々、計時コンパイル0/1で実行し、生成ハッシュ配列の
SHA-256、各ページのtaintと処理長、入力改変・読込異常時のエラー値と読込
回数を直接比較する。原本はread-batch直前のパッチ段階であり、後続パッチを
適用した側の `cs_validate_hash` 本文が一致することも試験する。これは全
カーネルやAMFIポリシーの差分比較ではない。
