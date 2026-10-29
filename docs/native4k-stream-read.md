# Optional native4k streaming signature preparation

This source-only performance candidate ports the read/cache policy from official
UniXNU commit `477e530a8689af4a09eacb4eb9bdb878c737d8b6` into the existing
native4k coalescer, read-batch, and startup-timing patch stack. Baseline is
`f01a50acca0853daf1c3a0564656ded2406f72bb`. It does not eliminate whole-file
preparation. No A04BR3 performance improvement is established by host tests.

`native-cs-stream=1` opts in on readonly mounts only. Missing/0/2/3 keep the
previous policy. Each read is at most 1MiB; signed ranges strictly above 32MiB
use `IO_NOCACHE`. Smaller files remain cached for their imminent executable
faults. This selector takes precedence over the existing 256KiB selector.
If the optional 1MiB scratch allocation fails, retry with the original 16KiB
scratch; failure of both retains the existing ENOMEM result.
No global vnode cache flags, VM purge, persistent hash cache or device policy is
changed. Writable mounts retain the existing baseline behavior.

Every original 16KiB signature block, including the final partial block, must
still authenticate before deriving its 4KiB digests from that exact buffer.
The complete derived array is made readonly before publication. Read errors,
short reads, corrupt hashes and protection/allocation failures publish nothing.
The existing coalescer, MACF checks, blob equivalence/revocation, vnode locks,
cleanup and VM-fault path are unchanged. I/O still occurs outside vnode/VM locks.
The optional timing `batched` field continues to mean exactly 256KiB, not all
multi-block modes; use read call/byte counts to identify the 1MiB policy.

## Source comparison

* GitHub API comparison confirms 477e530 is an ancestor of official main
  066c8d8315f83749d28bcae2faf3595718646be5 (ahead 117, behind 0,
  merge-base 477e530). A commit URL alone would not prove branch ancestry.
* Official `UniXNU/UniXNU` commit 477e530 reports eager dyld cache reads polluting
  UBC and introduces 1MiB reads and the >32MiB uncached threshold. Its TB128FU
  performance numbers are the commit author's report, not independently verified
  measurements: raw UART and measurement methodology have not been located.
  They are not A04BR3 measurements or predictions.
* Local official reference HEAD b881ac7 has the earlier eager 16KiB implementation;
  its object store also contains the later 477e530 implementation.
* iOS16 amethyst reference e0cf469c2ef0f6fec14d271aee0937c935d68281
  (`configs/*`) enables XNU_NATIVE_CS_HASH_CACHE but supplies no replacement
  native4k preparer. It inherits the selected base; this is not evidence of a
  separate lazy, authenticated solution.
* nuwa iOS16/8796 candidate README explicitly says candidates are not a complete
  patch stack nor runtime validation. Do not infer a safe lazy policy from it.
* Pinned Apple XNU d8b80295118ef25ac3a784134bcf95cd8e88109f:
  `bsd/sys/vnode.h` defines IO_NOCACHE for this I/O only;
  `bsd/vfs/vfs_cluster.c` aborts newly read UPL pages with DUMP_PAGES rather than
  committing them to UBC, while preexisting pages have their own release path.
  Filesystem behavior and actual demand rereads must still be measured.

## Host validation

```
CC=clang python3 scripts/tests/check_root_read_batch.py --xnu-source PINNED_XNU
python3 scripts/tests/check_root_coalesce.py --xnu-source PINNED_XNU
```

The first test applies the real ordered patch stack to pinned Apple source,
extracts the actual preparer, and executes it with OpenSSL SHA256 and bounded
I/O/VM mocks under ASan/UBSan, with root timing both compiled out and in. It
checks flag absence/values, mutable mounts, exact threshold and tails, digest
identity, late corruption, short reads, cleanup and publication. It cannot
validate APFS/UPL runtime behavior or hardware performance.

## Owner-run comparison (no device actions by this change)

Build the existing kernel incrementally with this patch; leave Data, driver
archives, GPU, userland and all unrelated boot settings fixed. Run paired
baseline/stream epochs on the same kernel, at least three alternating pairs.
Record UART byte offsets, image/source hashes and exact args. Do not append to
an already-full command line; make a recorded profile replacement if necessary.
Use existing root timing, MSDC attribution/bytes, VM counters, per-task CPU,
first-frame and input-to-render timestamps. Record read/hash time separately.

Accept only with no new signature/AMFI/I/O failures, preserved UI correctness,
and repeatable startup/input improvement or materially lower memory pressure
without a sustained I/O/latency regression. Larger read requests alone are not
proof of improvement. Reject if executable demand rereads erase the benefit.
No actual SDK/prelink or device validation is implied by host PASS.
