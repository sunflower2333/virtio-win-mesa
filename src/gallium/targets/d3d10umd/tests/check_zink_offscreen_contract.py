#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


meson = ROOT / "meson.build"
target = ROOT / "src/gallium/targets/d3d10umd/d3d10_gdi.c"
target_meson = ROOT / "src/gallium/targets/d3d10umd/meson.build"
stubs = ROOT / "src/gallium/frontends/d3d10umd/YttriumStubs.cpp"
resource = ROOT / "src/gallium/drivers/zink/zink_resource.c"
atomic = ROOT / "src/util/u_atomic.h"
probe = ROOT / "src/gallium/targets/d3d10umd/tests/zink_d3d11_offscreen.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

meson_text = meson.read_text(encoding="utf-8")
target_text = target.read_text(encoding="utf-8")
target_meson_text = target_meson.read_text(encoding="utf-8")
stubs_text = stubs.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
atomic_text = atomic.read_text(encoding="utf-8")
probe_text = probe.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

require(meson_text, "with_gallium_zink,", meson)
require(target_meson_text, "driver_zink,", target_meson)
require(target_meson_text, "idep_mesautil, idep_xmlconfig", target_meson)
require(target_meson_text, "'-DGALLIUM_ZINK'", target_meson)
require(target_text, '#include "zink/zink_public.h"', target)
require(target_text, 'default_driver = "zink";', target)
require(target_text, "return zink_win32_create_screen(0);", target)
require(resource_text, "whandle->type == WINSYS_HANDLE_TYPE_D3DKMT_ALLOC", resource)
for symbol in (
    "yttrium_trace_logf",
    "yttrium_venus_create",
    "yttrium_venus_destroy",
    "yttrium_venus_framebuffer_color_sample_counts",
    "yttrium_venus_max_sampler_anisotropy",
):
    require(stubs_text, symbol, stubs)

venus_create = stubs_text.index("yttrium_venus_create(struct gdikmt_device *device)")
venus_reject = stubs_text.index("return NULL;", venus_create)
venus_destroy = stubs_text.index("yttrium_venus_destroy", venus_create)
if not venus_create < venus_reject < venus_destroy:
    raise AssertionError("non-Yttrium Venus creation is not fail-closed")

trace_stub = stubs_text.index("yttrium_trace_logf")
first_c_close = stubs_text.index("\n}\n", trace_stub)
second_c_block = stubs_text.index('extern "C" {', venus_destroy)
gdi_flush = stubs_text.index("yttrium_gdi_flush_labeled", second_c_block)
if not trace_stub < first_c_close < venus_create < second_c_block < gdi_flush:
    raise AssertionError("non-Yttrium stubs use the wrong language linkage")
require(
    atomic_text,
    "defined(__clang__) && defined(USE_GCC_ATOMIC_BUILTINS)",
    atomic,
)
require(target_meson_text, "'zink_d3d11_offscreen'", target_meson)
require(target_meson_text, "files('tests/zink_d3d11_offscreen.cpp')", target_meson)
require(probe_text, 'set_environment(L"GALLIUM_DRIVER", L"zink")', probe)
require(probe_text, 'set_environment(L"LIBGL_ALWAYS_SOFTWARE", nullptr)', probe)
require(probe_text, 'set_environment(L"D3D_ALWAYS_SOFTWARE", nullptr)', probe)
require(probe_text, 'LoadLibraryExW(L"viogpud3d-zink.dll"', probe)
require(probe_text, "D3D_DRIVER_TYPE_SOFTWARE", probe)
require(probe_text, "D3D11CreateDevice(", probe)
require(probe_text, "DXGI_FORMAT_R8G8B8A8_UNORM", probe)
require(probe_text, "ClearRenderTargetView", probe)
require(probe_text, "CopyResource", probe)
require(probe_text, "D3D11_MAP_READ", probe)
require(probe_text, "kExpectedChecksum = 2088960", probe)
require(workflow_text, "viogpud3d-zink zink_d3d11_offscreen", workflow)
require(workflow_text, "artifact/zink_d3d11_offscreen.exe", workflow)
require(workflow_text, "$files.Count -ne 2", workflow)
require(workflow_text, "'-Dvulkan-drivers=[]'", workflow)
require(workflow_text, "'-Dtools=[]'", workflow)
require(workflow_text, '"src/util/u_atomic.h"', workflow)
require(workflow_text, "Microsoft.Windows.WDK.ARM64", workflow)
require(workflow_text, "10.0.26100.6584", workflow)
require(
    workflow_text,
    "e705b2a63eab891def8f98087666f93e8f21da8e3b5def81a624b83fef5bdae9",
    workflow,
)
for header in ("d3d10umddi.h", "d3dumddi.h", "d3dkmddi.h"):
    require(workflow_text, header, workflow)

for forbidden in ("CreateSwapChain", "CreateDeviceAndSwapChain", "Present("):
    if forbidden in probe_text:
        raise AssertionError(f"offscreen probe contains forbidden {forbidden!r}")

guard = resource_text.index(
    "whandle->type == WINSYS_HANDLE_TYPE_D3DKMT_ALLOC"
)
reject = resource_text.index("return false;", guard)
first_resource_use = resource_text.index("if (tex->target == PIPE_BUFFER)", guard)
if not guard < reject < first_resource_use:
    raise AssertionError("D3DKMT allocation rejection is not fail-closed")

print("Zink D3D offscreen contract: PASS")
