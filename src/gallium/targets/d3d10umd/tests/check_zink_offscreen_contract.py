#!/usr/bin/env python3

import hashlib
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
producer_hlsl = (
    ROOT / "src/gallium/targets/d3d10umd/tests/counter_producer_cs_5_0.hlsl"
)
consumer_hlsl = (
    ROOT / "src/gallium/targets/d3d10umd/tests/counter_consumer_cs_5_0.hlsl"
)
producer_header = (
    ROOT / "src/gallium/targets/d3d10umd/tests/counter_producer_cs_5_0.h"
)
consumer_header = (
    ROOT / "src/gallium/targets/d3d10umd/tests/counter_consumer_cs_5_0.h"
)
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

meson_text = meson.read_text(encoding="utf-8")
target_text = target.read_text(encoding="utf-8")
target_meson_text = target_meson.read_text(encoding="utf-8")
stubs_text = stubs.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
atomic_text = atomic.read_text(encoding="utf-8")
probe_text = probe.read_text(encoding="utf-8")
producer_hlsl_text = producer_hlsl.read_text(encoding="utf-8")
consumer_hlsl_text = consumer_hlsl.read_text(encoding="utf-8")
producer_header_text = producer_header.read_text(encoding="utf-8")
consumer_header_text = consumer_header.read_text(encoding="utf-8")
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
venus_header = stubs_text.index(
    '#include "gallium/winsys/yttrium/gdi/yttrium_venus.h"'
)
venus_header_c_block = stubs_text.rfind('extern "C" {', 0, venus_header)
venus_header_c_close = stubs_text.index("\n}\n", venus_header)
stub_c_block = stubs_text.index('extern "C" {', venus_header_c_close)
gdi_flush = stubs_text.index("yttrium_gdi_flush_labeled", venus_destroy)
if not (
    venus_header_c_block
    < venus_header
    < venus_header_c_close
    < stub_c_block
    < trace_stub
    < venus_create
    < gdi_flush
):
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
require(probe_text, '#include "tri_vs_4_0.h"', probe)
require(probe_text, '#include "tri_ps_4_0.h"', probe)
require(probe_text, "CreateVertexShader(g_VS, sizeof(g_VS)", probe)
require(probe_text, "CreatePixelShader(g_PS, sizeof(g_PS)", probe)
require(probe_text, "CreateInputLayout(kInputElements", probe)
require(probe_text, "D3D11_USAGE_IMMUTABLE", probe)
require(probe_text, "D3D11_BIND_VERTEX_BUFFER", probe)
require(probe_text, "OMSetRenderTargets", probe)
require(probe_text, "ClearRenderTargetView", probe)
require(probe_text, "IASetInputLayout", probe)
require(probe_text, "IASetVertexBuffers", probe)
require(probe_text, "D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST", probe)
require(probe_text, "RSSetViewports", probe)
require(probe_text, "VSSetShader", probe)
require(probe_text, "PSSetShader", probe)
require(probe_text, "Draw(ARRAYSIZE(kFullscreenTriangle), 0)", probe)
require(probe_text, "D3D11_DRAW_INSTANCED_INDIRECT_ARGS indirect_args", probe)
require(probe_text, "static_assert(sizeof(indirect_args) == 16)", probe)
require(
    probe_text,
    "indirect_desc.ByteWidth = static_cast<UINT>(sizeof(indirect_args))",
    probe,
)
require(probe_text, "indirect_desc.Usage = D3D11_USAGE_IMMUTABLE", probe)
require(
    probe_text,
    "indirect_desc.MiscFlags = D3D11_RESOURCE_MISC_DRAWINDIRECT_ARGS",
    probe,
)
require(probe_text, "CreateBuffer(&indirect_desc, &indirect_data", probe)
require(probe_text, "DrawInstancedIndirect(indirect_buffer.Get(), 0)", probe)
require(probe_text, "CopyResource", probe)
require(probe_text, "D3D11_MAP_READ", probe)
require(probe_text, "pixel[0] != 0 || pixel[1] != 255 || pixel[2] != 255", probe)
require(probe_text, "kExpectedChecksum = 3133440", probe)
require(probe_text, '#include "counter_producer_cs_5_0.h"', probe)
require(probe_text, '#include "counter_consumer_cs_5_0.h"', probe)
require(probe_text, "D3D11_BUFFER_UAV_FLAG_COUNTER", probe)
require(probe_text, "D3D11_KEEP_UNORDERED_ACCESS_VIEWS", probe)
require(probe_text, "CopyStructureCount(count_buffer, 0, counter_uav)", probe)
require(probe_text, "CreateComputeShader(\n      g_counter_producer_cs", probe)
require(probe_text, "CreateComputeShader(\n      g_counter_consumer_cs", probe)
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

for fragment in (
    "Microsoft.Windows.SDK.CPP",
    "5d31b38205bdd9ac761b4cb39fbbc6b7209b01c11194324afc674d7d119483a0",
    "05dca4e48ce764234f045d7ccd5687398564d762823955dc81624ba5c6f3f3c4",
    "ec07559efadf04371bbe1253a39aecd366d08617f7c0eb00ac9df99f79fba444",
    "bfe3e2d09d175e82649b58c22a570d3df93c5a56325ed191d4734b6f530c4a92",
    "9dc4fa9552346dd508911c1a0e055dc0b63157a58f91f339a67d600a73022b72",
    "imm_atomic_alloc",
    "imm_atomic_consume",
    "store_uav_typed",
    "/T cs_5_0",
):
    require(workflow_text, fragment, workflow)
if "zink-d3d11-counter-fixtures" in workflow_text:
    raise AssertionError("temporary counter fixture artifact remains enabled")

for text, source, fragments in (
    (
        producer_hlsl_text,
        producer_hlsl,
        (
            "RWStructuredBuffer<uint> values : register(u0);",
            "RWBuffer<uint> markers : register(u1);",
            "[numthreads(4, 1, 1)]",
            "values.IncrementCounter()",
            "values[index] = 98u + index;",
            "markers[dispatch_id.x] = index;",
        ),
    ),
    (
        consumer_hlsl_text,
        consumer_hlsl,
        (
            "RWStructuredBuffer<uint> values : register(u0);",
            "RWBuffer<uint> markers : register(u1);",
            "[numthreads(2, 1, 1)]",
            "values.DecrementCounter()",
            "markers[dispatch_id.x] = values[index];",
        ),
    ),
):
    for fragment in fragments:
        require(text, fragment, source)

for text, source, fragments in (
    (
        producer_header_text,
        producer_header,
        ("cs_5_0", "imm_atomic_alloc", "store_structured", "store_uav_typed"),
    ),
    (
        consumer_header_text,
        consumer_header,
        ("cs_5_0", "imm_atomic_consume", "ld_structured", "store_uav_typed"),
    ),
):
    for fragment in fragments:
        require(text, fragment, source)

expected_fixture_hashes = {
    producer_header: "8c2f2a58b81ce481784025799684a2758b1b3f0e6c53dbca5a1362c4e65c4c16",
    consumer_header: "06a8361ed5510e0b59d8ce4ecc64858f8fe7a11ec4839328ba8374144b8582c2",
}
for fixture, expected_hash in expected_fixture_hashes.items():
    fixture_bytes = fixture.read_bytes().replace(b"\r\n", b"\n")
    if b"\r" in fixture_bytes:
        raise AssertionError(f"counter fixture has a bare carriage return: {fixture}")
    actual_hash = hashlib.sha256(fixture_bytes).hexdigest()
    if actual_hash != expected_hash:
        raise AssertionError(
            f"counter fixture hash mismatch for {fixture}: {actual_hash}"
        )

for forbidden in (
    "CreateSwapChain",
    "CreateDeviceAndSwapChain",
    "D3DCompile",
    "Present(",
):
    if forbidden in probe_text:
        raise AssertionError(f"offscreen probe contains forbidden {forbidden!r}")

validation_start = probe_text.index("validate_cyan_frame(ID3D11DeviceContext")
validation_end = probe_text.index("\n}\n\nbool\nset_environment", validation_start)
validation_body = probe_text[validation_start:validation_end]
for fragment in (
    "CopyResource(staging, render_target)",
    "Map(staging, 0, D3D11_MAP_READ",
    "Unmap(staging, 0)",
):
    require(validation_body, fragment, probe)

main_start = probe_text.index("\nint\nmain()", validation_end)
main_body = probe_text[main_start:]
draw_order = (
    "OMSetRenderTargets",
    "ClearRenderTargetView",
    "CreateVertexShader",
    "CreatePixelShader",
    "CreateInputLayout",
    "CreateBuffer(&vertex_desc",
    "IASetInputLayout",
    "IASetVertexBuffers",
    "IASetPrimitiveTopology",
    "RSSetViewports",
    "VSSetShader",
    "PSSetShader",
    "Draw(ARRAYSIZE(kFullscreenTriangle), 0)",
    '"direct draw"',
    "ClearRenderTargetView",
    "DrawInstancedIndirect(indirect_buffer.Get(), 0)",
    '"indirect draw"',
)
draw_position = 0
for fragment in draw_order:
    draw_position = main_body.index(fragment, draw_position) + len(fragment)
if main_body.count("validate_cyan_frame(context.Get()") != 2:
    raise AssertionError("direct and indirect draws need independent readback checks")

counter_start = probe_text.index("validate_uav_counters(ID3D11Device")
counter_end = probe_text.index("\nbool\nvalidate_cyan_frame", counter_start)
counter_body = probe_text[counter_start:counter_end]
for fragment in (
    "initial_counts[] = {2, D3D11_KEEP_UNORDERED_ACCESS_VIEWS}",
    'counter_uav.Get(), 2,\n                                 "initial counter"',
    'counter_uav.Get(), 6,\n                                 "producer counter"',
    "validate_u32_sequence(&counter_values[2], 4, 100",
    "validate_u32_set(marker_values, ARRAYSIZE(marker_values), 2",
    "preserved_counts[]",
    'counter_uav.Get(), 4,\n                                 "consumer counter"',
    'validate_u32_set(marker_values, 2, 102, "consumer values")',
):
    require(counter_body, fragment, probe)
if counter_body.count("context->Dispatch(1, 1, 1)") != 2:
    raise AssertionError("counter producer and consumer need separate dispatches")
if counter_body.count("validate_structure_count(context") != 3:
    raise AssertionError("initial, producer, and consumer counts need validation")

guard = resource_text.index(
    "whandle->type == WINSYS_HANDLE_TYPE_D3DKMT_ALLOC"
)
reject = resource_text.index("return false;", guard)
first_resource_use = resource_text.index("if (tex->target == PIPE_BUFFER)", guard)
if not guard < reject < first_resource_use:
    raise AssertionError("D3DKMT allocation rejection is not fail-closed")

print("Zink D3D offscreen contract: PASS")
