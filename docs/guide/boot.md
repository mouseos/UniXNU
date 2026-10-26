# Boot the image

The boot image runs from RAM. The workflow starts the image and leaves the installed boot partition unchanged.

## Prerequisites

- An unlocked bootloader with `fastboot`.
- A device with a UEFI port that matches the board configuration.
- A built boot image with a payload, or an empty ramdisk for the boot manager smoke test.
- A serial console when the board exposes a UART.

## Start the image

```sh
fastboot devices
fastboot boot out/<board>/boot/boot.img
```

`fastboot boot` transfers the image and starts it one time. The stock boot partition and the installed OS stay unchanged.

The boot image contains:

| Part | Contents |
| --- | --- |
| Kernel | gzip of BootShim plus the UEFI firmware volume |
| Ramdisk | UniXNU payload FAT volume |
| Appended data | Device tree |

The stock Android bootloader loads the image, verifies the ARM64 header in BootShim, and jumps to the shim. BootShim starts the firmware volume.

## Boot manager

UniXNU prints its version and configuration summary to the serial port and draws the menu. The default configuration uses a timeout, a default entry and a countdown.

| Action | Key |
| --- | --- |
| Move the highlight | Up and Down |
| Boot the selected entry | Enter |
| Stop the countdown | Any key |
| Confirm an entry | Enter |
| Cancel a confirmation | Any key without choices, or Enter on Cancel |
| Choose a confirmation option | Up and Down, then Enter |

An entry with `confirm` shows a question before it boots. The countdown skips entries that require confirmation. With `confirm_titles`, Cancel is selected first and the chosen `confirm_args` entry is appended to the entry's arguments. See [Boot configuration](/reference/boot-configuration).

The menu entries come from `\EFI\UniXNU\unixnu.toml`. An entry can start an EFI image, a Linux image with an EFI stub, an action, or a Darwin kernel through the loader protocol.

If UniXNU finds no configuration, it scans every volume for `\EFI\BOOT\BOOTAA64.EFI` and adds those entries in front of the built-in actions.

## Darwin boot

For an entry of type `xnu`, DarwinBoot reads these files from the entry directory:

| File | Required | Contents |
| --- | --- | --- |
| `kernel.macho` | yes | Prelinked XNU kernel |
| `kernel.macho.adt` | yes | Apple-format device tree sidecar |
| `kernel.macho.trustcache` | no | Trust cache bundle |
| the entry `initrd` | no | Data ramdisk seed |

DarwinBoot copies the kernel segments into a contiguous physical window, builds `boot_args`, installs the ADT and the trust cache addresses in the `/chosen/memory-map` placeholders, and exits boot services.

The default window is 256 MiB. The ADT property `/chosen/darwinboot-memory-size` can request a larger window.

## First boot

The first boot needs a userdata image. The image supplies the OS and SystemOS volumes and the root volume UUID that the kernel matches.

```sh
fastboot flash userdata out/<board>/userdata/userdata-root.img
fastboot reboot bootloader
fastboot boot out/<board>/boot/boot.img
```

The userdata image is large. Build it with `unixnu build userdata` and flash it from the device repository report.

The Data seed supplies the writable Data volume. The `--skip-setup` option marks Setup as done in a copy of the seed, so the Hello pages do not run. The procedure and the preference changes are in [Skip Setup](/guide/skip-setup).

## Logs

The UEFI firmware logs to `EFI_SERIAL_IO_PROTOCOL` when the board exposes a UART. UniXNU prefixes its lines with `UNIXNU:`.

The kernel logs to the serial port when the command line selects one, for example `serial=3`. The boot progress layer writes checkpoints to the framebuffer and the serial port.

Useful logs:

| Source | Location |
| --- | --- |
| Build driver | `out/<board>/logs/*.log` |
| Boot manager | Serial console, lines with `UNIXNU:` |
| DarwinBoot | Serial console, lines with `DARWINBOOT:` |
| XNU | Serial console, kernel output |

## Recovery

The image runs from RAM. Reset the device to return to the stock bootloader and the installed OS.

```sh
fastboot reboot bootloader
```

If the firmware stalls before the menu, reset the device and start the same image again. A firmware stall leaves the device in the bootloader; a second `fastboot boot` uses the same image.

## macOS

The boot pipeline is driven by the IPSW. A macOS restore image provides `KernelCache`, `DeviceTree`, `OS`, `Cryptex1,SystemOS`, `StaticTrustCache` and `Cryptex1,SystemTrustCache` in the same member layout.

To boot macOS:

1. Point `[ipsw]` in the board file at a macOS IPSW and set the product, version, build, device class, chip ID and board ID of that image.
2. Pin the member hashes in `[ipsw.sha256]`.
3. Set `[userdata] windows` to `OS` and `Cryptex1,SystemOS`.
4. Build the kernel, payload, boot image and userdata image.
5. Flash the userdata image and start the boot image.

The device tree and the platform drivers supply the hardware description. The userland comes from the macOS disk images.

## Next steps

- [Userdata image](/guide/userdata) describes the partition image.
- [Boot arguments](/xnu/boot-arguments) lists the kernel arguments.
- [Troubleshooting](/reference/troubleshooting) lists failure conditions and checks.
- [Devices](/devices/) lists device specific commands.

### Optional loader memory-map diagnostics

DarwinBoot defaults `DARWINBOOT_MEMORY_MAP_DIAG` to 0. A device diagnostic
configuration may set `DARWINBOOT_MEMORY_MAP_DIAG = "1"` in its existing
`[firmware.defines]` table. The official firmware builder forwards that value
as an EDK II build define. The platform DSC must include
`DarwinBootPkg/Driver/DarwinBoot.dsc.inc` inside `[Components]` in place of the
plain DarwinBoot INF entry. This forwards the compiler define only to DarwinBoot.
The standalone DarwinBoot DSC also uses that include. Other values remain off.
No board default is changed by the generic implementation.

When enabled, `DBMM pre` records describe the already acquired map immediately
before the allocation search; `DBMM final` records describe each successful
GetMemoryMap immediately before its ExitBootServices attempt. Raw records carry
index, EFI type, physical/virtual start, page count and attributes. They do not
classify ownership or declare usable RAM. Invalid maps are labelled; output is
capped at 1024 descriptors per snapshot with an explicit `TRUNCATED` marker.
Every record is below 200 bytes. Output bypasses the UEFI console and uses the
platform's SerialPortLib; that instance must not allocate or call boot services.
The standalone DSC binds a null serial library, so an appropriate platform
binding is required to capture output. No SerialPortInitialize call is added.

The diagnostic itself uses stack storage only and does not allocate/free pages,
change reservations or boot arguments, or extend the owned window. Serial output
adds time and is not suitable as a performance baseline. A complete final map
and a successful allocation are needed before claiming a larger usable window;
adding `MemorySizeActual` alone does not add managed pages.

Host checks (no firmware/hardware execution):

```sh
python3 scripts/check-darwinboot-memory-map.py
python3 scripts/check-darwinboot-memory-map-build.py --edk2-source /absolute/path/to/pinned-mu_basecore
```

The second check verifies the checkout revision against the official `edk2`
source pin in `feeds.toml` before exercising the real DSC parser.

To enable the diagnostic for one build without changing board defaults, the
existing firmware-defines dictionary can be overridden in the build context.
Run this from the UniXNU root after selecting the reviewed source pins (adjust
only checkout paths / the existing output directory as needed):

```sh
python3 - <<'PYTHON'
import sys
sys.path.insert(0, "scripts")
from unixnu.cli import parser, cmd_build
from unixnu.config import Context
args = parser().parse_args([
    "build", "firmware", "-D", "../UniXNU-a04br3",
    "--uefi", "../uefi-a04br3", "--edk2", "out/feeds/mu_basecore-89034cbb",
    "--target", "DEBUG", "-j", "4",
])
ctx = Context(args)
ctx.board["firmware"].setdefault("defines", {})["DARWINBOOT_MEMORY_MAP_DIAG"] = "1"
cmd_build(ctx)
PYTHON
```

This uses the official firmware preparation/build path and only changes the
in-memory dictionary for that invocation; it does not edit `board.toml`, run a
kernel build, or write/boot the device. The normal CLI has no separate
`--firmware-define` option. Verify the build log contains
`-D DARWINBOOT_MEMORY_MAP_DIAG=1` before using the resulting firmware.
