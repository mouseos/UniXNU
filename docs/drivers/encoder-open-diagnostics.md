# Scanout encoder-open diagnostics: incremental build

The optional first-valid-frame record is described in NativeMetal's README.
The scanout observer arms it only for `PVR_METAL_PIPELINE_DIAG=1`; it is off by
default. This is instrumentation, not a performance fix or a GPU timestamp.

The bridge source must be NativeMetal at the gitlink recorded by this UniXNU
commit. The translator must be exactly
`720ef1ce9ae2a2068999a8675717418b9416283e` with the nine recorded NativeMetal
patches. The builder reconstructs each recorded patch prefix in a private Git
index and object store, verifies the pinned tree for each patch prefix and each
patch SHA-256, then checks every tracked file's raw bytes and mode and rejects
unrelated untracked paths. The root `target/` build-output directory is the sole
exception. The source tree must not be modified concurrently while it is being
verified and built. The full-byte scan reads the entire translator tree. For
TAB-A04-BR3, device `7bd13db94a772c5f70470160289bedd00365f3d9` pins Mesa
`0d94b3f397fb9cf8470bb5600ada8af79ff5361a`, tree
`f6a8011a63fc386a431214898dd8fb93d9ae7c54`, and its recorded patch (SHA-256
`f5c637ba4f0fd0565312625f9d296a848073251139307975c411e0f63831fd67`). Reuse
only a verified driver artifact from that source and matching configuration;
this change needs no Mesa or kernel rebuild. Record source commits, full diff,
driver hash, SDK, Rust toolchain and bridge/plugin hashes for any comparison.

On a prepared macOS build tree with Rust 1.98.0 and its `aarch64-apple-ios`
target, Xcode/iPhoneOS SDK and LLVM `llvm-as` 21 or newer, the following are
incremental build commands to execute later in an authorized environment. They
were not run as part of this source-only task:

```sh
# From the prepared UniXNU tree, after checking its NativeMetal gitlink and
# .cache/gpu-reference/metal2vulkan against the pinned source and nine patches.
python3 scripts/build-native-metal-bridge.py --target ios --portable-sha2

# Run the device wrapper from the prepared tree containing kits/a04br3 and
# its copied scripts; supply the verified, previously built driver explicitly.
python3 scripts/build-a04br3-metal-plugin.py \
  --vulkan /absolute/path/to/verified/libvulkan_powervr_mesa.dylib \
  --skip-bridge --pipeline-failure-diag --buffer-rows
```

`--pipeline-failure-diag` also enables first-four-frame top-400-row verification.
P28 used an earlier implementation that read the live mapping on the CPU before
`COMPLETE_SWAP` and timed out before retirement; its readback duration was not
measured. In this source revision, a GPU snapshot copy still runs before
`COMPLETE_SWAP`, while CPU comparison of the snapshot runs asynchronously after
successful completion. Its timing and effect on the timeout are unmeasured.
The snapshot capture waits for GPU completion without a separate deadline while
holding the swap lease. A stall there can still prevent retirement. The `0x6731`
marker indicates that the display copy returned, before snapshot capture.
GPU-to-CPU snapshot visibility on the target has not been established.
Encoder timing and verification are not independent in this configuration.
Do not infer a normal-path failure or mask/extend the timeout from P28.

`--skip-bridge` is safe only after verifying the immediately preceding bridge
archive's hash and manifest; an older bridge will not provide the callback ABI.
The diagnostic and buffer-rows flags match the prior measured configuration;
all other device flags and inputs must be matched separately. Building the
bundle does not test, package, deploy, flash or boot an image. Existing trust
and payload tooling must be used for a separately authorized device trial.

On Linux, the pure host diagnostics checks are:

```sh
python3 scripts/build-native-metal-bridge.py --apply-and-verify-source-only
python3 drivers/NativeMetal/tests/check_scanout_copy_trace.py
python3 drivers/NativeMetal/tests/check_encoder_presenter_mock.py
python3 drivers/NativeMetal/tests/check_encoder_open_trace.py \
  --translator /absolute/path/to/translator-with-nine-patches
cargo +1.98.0 check --offline --manifest-path \
  /absolute/path/to/translator/Cargo.toml -p metal2vulkan-runtime
```

Those checks do not replace an Apple SDK build or a real Metal runtime test.
