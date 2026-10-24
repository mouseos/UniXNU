# Vendor-neutral Metal plugin

`drivers/NativeMetal/NativeVulkanMetalPlugin.mm` runs the native Metal frontend (metal2vulkan) on any Vulkan driver that exports
`vkGetInstanceProcAddr`, such as a Mesa driver with a Darwin kernel interface. The Adreno plugin (`NativeAdrenoMetalPlugin.mm`) is
separate and unchanged; this plugin is used only when a device repository builds it.

## Board hooks

A board supplies four functions (`drivers/NativeMetal/NativeMetalBoard.h`), compiled into the plugin:

| Function | Role |
| --- | --- |
| `native_metal_board_prepare(port)` | Environment of the board's Vulkan driver (its kernel service and open type), once per process |
| `native_metal_board_mark(value)` | Progress marker to the board's log |
| `native_metal_board_text(line)` | One text line to the board's log |
| `native_metal_board_scanout(transport)` | The display hand-off transport (`GpuScanoutClient.h`, boot argument `sheng-fb-gpu=1`), or false |

## Modes

Files beside the bundle in the GPU addon view of `/System/Library/Extensions` choose what the plugin does:

| File | Effect |
| --- | --- |
| `<Name>.selftest` | backboardd runs the bridge self-test (compute, render, host import, QuartzCore translation) and returns no device |
| `<Name>.publish` | backboardd returns the native device; the render server composites through it and serves the scanout hand-off |
| `<Name>.clients` | Other processes that get their own device (`*` for all) |
| `<Name>.prime` | Shader priming 90 s after the device opened (`PrimeShaders.h`) |

## Build

```sh
python3 scripts/build-vulkan-metal-plugin.py --name NAME --principal-class CLASS --vulkan-driver LIBRARY.dylib \
  --board-source BOARD.mm [--include DIR ...]
```

The output is `build/vulkan-metal-plugin/NAME/NAME.bundle` with the driver inside, 4 KiB-page signed, and `trust.json` with the
CDHashes for an owner trust module. The board also publishes an accelerator for the discovery: an IOAcceleratorES subclass with
`MetalPluginName` and `MetalPluginClassName`, staged with `scripts/build-native-adreno-accelerator.py --source FILE --into ARCHIVE`.

The first user is the Benesse TAB-A04-BR3 (PowerVR GE8300, Mesa's PowerVR driver):
[UniXNU-a04br3](https://github.com/mouseos/UniXNU-a04br3).
