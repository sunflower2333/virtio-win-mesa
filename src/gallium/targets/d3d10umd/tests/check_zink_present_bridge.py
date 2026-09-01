#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


def require_order(text: str, fragments: tuple[str, ...], source: Path) -> None:
    positions = []
    start = 0
    for fragment in fragments:
        position = text.find(fragment, start)
        if position < 0:
            raise AssertionError(f"missing ordered fragment {fragment!r} in {source}")
        positions.append(position)
        start = position + len(fragment)
    if positions != sorted(positions):
        raise AssertionError(f"incorrect ordering in {source}: {fragments!r}")


abi = ROOT / "src/gallium/frontends/d3d10umd/VioGpuWddmPresentAbi.h"
gdikmt_header = ROOT / "src/gallium/auxiliary/gdikmt/gdikmt.h"
gdikmt_runtime = ROOT / "src/gallium/frontends/d3d10umd/gdikmt_d3dddi.cpp"
resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
resource_header = ROOT / "src/gallium/frontends/d3d10umd/Resource.h"
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
dxgi = ROOT / "src/gallium/frontends/d3d10umd/DxgiFns.cpp"
target = ROOT / "src/gallium/targets/d3d10umd/d3d10_gdi.c"
zink_resource = ROOT / "src/gallium/drivers/zink/zink_resource.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

abi_text = abi.read_text(encoding="utf-8")
gdikmt_header_text = gdikmt_header.read_text(encoding="utf-8")
gdikmt_runtime_text = gdikmt_runtime.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
resource_header_text = resource_header.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
dxgi_text = dxgi.read_text(encoding="utf-8")
target_text = target.read_text(encoding="utf-8")
zink_resource_text = zink_resource.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

# Exact revision-0 KMD allocation ABI. This is intentionally a minimal subset.
for fragment in (
    "#define VIOGPU_WDDM_ABI_MAGIC 0x504D5644U",
    "#define VIOGPU_WDDM_ABI_VERSION 0U",
    "#define VIOGPU_WDDM_ALLOCATION_PRIMARY 0x00000001U",
    "#define VIOGPU_WDDM_ALLOCATION_CPU_VISIBLE 0x00000002U",
    "#define VIOGPU_WDDM_FORMAT_B8G8R8A8_UNORM 1U",
    "#define VIOGPU_WDDM_FORMAT_B8G8R8X8_UNORM 2U",
    "sizeof(VioGpuWddmAllocationInfo) == 80",
    "offsetof(VioGpuWddmAllocationInfo, Flags) == 48",
    "offsetof(VioGpuWddmAllocationInfo, ContextId) == 76",
):
    require(abi_text, fragment, abi)

# Only the D3D target marks the selected screen. Zink itself must keep rejecting
# attempts to reinterpret a Vulkan allocation as a D3DKMT allocation.
require(target_text, "device->d3d10_zink = true;", target)
guard = zink_resource_text.index(
    "whandle->type == WINSYS_HANDLE_TYPE_D3DKMT_ALLOC"
)
reject = zink_resource_text.index("return false;", guard)
first_resource_use = zink_resource_text.index(
    "if (tex->target == PIPE_BUFFER)", guard
)
if not guard < reject < first_resource_use:
    raise AssertionError("Zink D3DKMT allocation export is not fail-closed")

# pfnAllocateCb receives an empty resource-private payload and one exact
# per-allocation KMD payload. Runtime resource ownership is preserved.
allocation_start = resource_text.index("D3DDDI_ALLOCATIONINFO allocation_info = {};")
allocation_end = resource_text.index(
    "device->device.base.createAllocation", allocation_start
)
allocation_block = resource_text[allocation_start:allocation_end]
for forbidden in ("allocation.pPrivateDriverData", "allocation.PrivateDriverDataSize"):
    if forbidden in allocation_block:
        raise AssertionError(f"resource-private payload is not empty: {forbidden}")
for fragment in (
    "allocation_info.pPrivateDriverData = &private_info;",
    "allocation_info.PrivateDriverDataSize = sizeof(private_info);",
    "allocation.force_allocation_handle = false;",
):
    require(allocation_block, fragment, resource)
require(gdikmt_runtime_text, "createAllocation.hResource = hRTResource;", gdikmt_runtime)

# Optional scanout surfaces are CPU-visible Blt sources. Only a non-optional
# front/proxy surface becomes a PRIMARY allocation with a real VidPn source ID.
for fragment in (
    "pPrimaryDesc->Flags & DXGI_DDI_PRIMARY_OPTIONAL",
    "pCreateResource->pPrimaryDesc->DriverFlags |=",
    "DXGI_DDI_PRIMARY_DRIVER_FLAG_NO_SCANOUT",
    "private_info.Flags = VIOGPU_WDDM_ALLOCATION_PRIMARY;",
    "private_info.Flags = VIOGPU_WDDM_ALLOCATION_CPU_VISIBLE;",
    "((yttrium && has_primary_desc) || zink_primary)",
    "has_primary_desc && (!zink || zink_primary)",
):
    require(resource_text, fragment, resource)
require(resource_text, "resource->zink_present_primary || subresource != 0", resource)
require(dxgi_text, '#include "Resource.h"', dxgi)
for fragment in (
    "D3DKMT_HANDLE GetZinkPresentAllocation(const Resource *resource);",
    "HRESULT PublishZinkPresentResource(Device *device, Resource *resource,",
):
    require(resource_header_text, fragment, resource_header)

# Context creation is lazy, uses engine affinity one with zero UMD flags and an
# empty private payload, and is released before the Gallium device is destroyed.
require_order(
    resource_text,
    (
        "if (device->zink_present_context)",
        "device->device.use_legacy_signal_sync = true;",
        "device->device.base.createContext(",
    ),
    resource,
)
require_order(
    gdikmt_runtime_text,
    (
        "memset(&createContext, 0, sizeof(createContext));",
        "if (device->use_legacy_signal_sync)",
        "createContext.EngineAffinity = 1;",
        "pfnCreateContextCb",
    ),
    gdikmt_runtime,
)
for source_text, source in (
    (gdikmt_runtime_text, gdikmt_runtime),
    (resource_text, resource),
):
    for forbidden in ("create_gdi_context", "Flags.GdiContext"):
        if forbidden in source_text:
            raise AssertionError(f"unsupported UMD GDI selector {forbidden!r} in {source}")
require_order(
    device_text,
    (
        "if (pDevice->zink_present_context)",
        "pDevice->zink_present_context->destroy",
        "pipe->destroy(pipe);",
    ),
    device,
)

# Publication waits through a PIPE_MAP_READ, then copies into the CPU-visible
# runtime allocation before issuing pfnPresentCb. Every successful map/lock is
# unwound in reverse order, and DestroyResource releases the paired allocation.
require_order(
    resource_text,
    (
        "texture_map(",
        "lockAllocation(",
        "memcpy(",
        "unlockAllocation(",
        "texture_unmap(",
    ),
    resource,
)
require_order(
    dxgi_text,
    (
        "if (!pDstResource)",
        "PublishZinkPresentResource(",
        "device->device.base.present(",
    ),
    dxgi,
)
require_order(
    resource_text,
    (
        "DestroyResource(D3D10DDI_HDEVICE",
        "ReleaseResourceContents(pipe, pResource);",
        "release_zink_present_allocation(device, pResource);",
    ),
    resource,
)

# The Yttrium measurement knob must never suppress the Zink callback.
for fragment in (
    "boolean force_present_callback;",
    "present_info.version = 4;",
    "present_info.force_present_callback = true;",
    "yttrium_present_throttle_applies(present_info)",
):
    source_text = gdikmt_header_text if fragment.startswith("boolean") else (
        dxgi_text if fragment.startswith("present_info") else gdikmt_runtime_text
    )
    source = gdikmt_header if fragment.startswith("boolean") else (
        dxgi if fragment.startswith("present_info") else gdikmt_runtime
    )
    require(source_text, fragment, source)

require(workflow_text, "check_zink_present_bridge.py", workflow)

print("Zink D3D Present bridge contract: PASS")
