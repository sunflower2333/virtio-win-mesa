#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


def function_body(text: str, signature: str, source: Path) -> str:
    start = text.find(signature)
    if start < 0:
        raise AssertionError(f"missing function {signature!r} in {source}")
    opening = text.find("{", start)
    if opening < 0:
        raise AssertionError(f"missing function body for {signature!r} in {source}")

    depth = 0
    for position in range(opening, len(text)):
        character = text[position]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[opening : position + 1]

    raise AssertionError(f"unterminated function {signature!r} in {source}")


front = ROOT / "src/gallium/frontends/d3d10umd"
dxgi = front / "DxgiFns.cpp"
device = front / "Device.cpp"
state = front / "State.h"
output_merger = front / "OutputMerger.cpp"
shader = front / "Shader.cpp"
shader_header = front / "Shader.h"
yttrium = ROOT / "src/gallium/winsys/yttrium/gdi/yttrium_resource.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

dxgi_text = dxgi.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
state_text = state.read_text(encoding="utf-8")
output_text = output_merger.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
shader_header_text = shader_header.read_text(encoding="utf-8")
yttrium_text = yttrium.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

for view_list in (
    "render_target_views",
    "depth_stencil_views",
    "shader_resource_view_objects",
    "unordered_access_view_objects",
):
    require(state_text, f"struct list_head {view_list};", state)
    require(device_text, f"list_inithead(&pDevice->{view_list});", device)

for view_struct in (
    "struct RenderTargetView\n{\n   struct list_head list;",
    "struct DepthStencilView\n{\n   struct list_head list;",
    "struct ShaderResourceView\n{\n   struct list_head list;",
    "struct UnorderedAccessView\n{\n   struct list_head list;",
):
    require(state_text, view_struct, state)
require(state_text, "struct pipe_surface surface;\n   Resource *resource;", state)

for fragment in (
    "list_addtail(&pRTView->list,",
    "&CastDevice(hDevice)->render_target_views",
    "list_delinit(&pRTView->list);",
    "list_addtail(&pDSView->list,",
    "&CastDevice(hDevice)->depth_stencil_views",
    "list_delinit(&pDSView->list);",
    "pDSView->resource = CastResource(",
    "GetPipeDepthStencilView(",
):
    require(output_text, fragment, output_merger)

for fragment in (
    "&CastDevice(hDevice)->shader_resource_view_objects",
    "list_delinit(&pSRView->list);",
    "&CastDevice(hDevice)->unordered_access_view_objects",
    "list_delinit(&pUAView->list);",
    "RefreshBoundUnorderedAccessViews(Device *pDevice)",
    "pDevice->shader_images[stage][slot] = view->image;",
    "pDevice->pipe->set_shader_images(",
):
    require(shader_text, fragment, shader)
require(
    shader_header_text,
    "void RefreshBoundUnorderedAccessViews(Device *pDevice);",
    shader_header,
)

rotate = function_body(
    dxgi_text,
    "_RotateResourceIdentities(DXGI_DDI_ARG_ROTATE_RESOURCE_IDENTITIES",
    dxgi,
)
for fragment in (
    "if (!RotateResourceIdentities)",
    "if (!device || !device->pipe)",
    "if (!hResources ||",
    "dxgi_device_owns_resource(device, resource)",
    "resources[j].frontend == resource",
    "resources[j].backing == resource->resource",
    "paired_count && paired_count != NumResources",
    "dxgi_is_zink_screen(device) && paired_count != NumResources",
    "!resource->zink_present_resource",
    "!resource->zink_present_allocation",
    "resource->zink_present_pitch !=",
    "resource->zink_present_width * 4",
    "&device->shader_resource_view_objects",
    "&device->render_target_views",
    "&device->depth_stencil_views",
    "&device->unordered_access_view_objects",
    "device->pipe->create_sampler_view(",
    "yttrium_gdi_resource_rotate_runtime_handles(backings, NumResources)",
    "resource->resource = resources[next].backing;",
    "resource->zink_present_allocation =",
    "resources[next].zink_present_allocation;",
    "pipe_sampler_view_reference(&sampler_views[i].view->handle,",
    "pipe_resource_reference(&view->surface.texture,",
    "pipe_resource_reference(&view->pipe_resource,",
    "view->image.resource = view->pipe_resource;",
    "RefreshBoundShaderResourceViews(device);",
    "RefreshBoundUnorderedAccessViews(device);",
    "dxgi_release_rotation_sampler_views(sampler_views, sampler_view_count);",
):
    require(rotate, fragment, dxgi)

if "resource->zink_present_resource =" in rotate:
    raise AssertionError("RotateResourceIdentities rotates a fixed RT resource handle")
if "CastResource(hResources" in rotate or "CastPipeResource(hResources" in rotate:
    raise AssertionError("RotateResourceIdentities casts before live-resource validation")

ownership = rotate.index("dxgi_device_owns_resource(device, resource)")
first_dereference = rotate.index("resources[i].backing = resource->resource")
view_validation = rotate.index("&device->unordered_access_view_objects")
srv_stage = rotate.index("device->pipe->create_sampler_view(")
trace = rotate.index("trace = dxgi_trace_enabled(device);")
yttrium_commit = rotate.index(
    "yttrium_gdi_resource_rotate_runtime_handles(backings, NumResources)"
)
identity_commit = rotate.index("resource->resource = resources[next].backing;")
view_commit = rotate.index("pipe_sampler_view_reference(&sampler_views[i].view->handle,")
refresh = rotate.index("RefreshBoundShaderResourceViews(device);")
cleanup = rotate.index(
    "dxgi_release_rotation_sampler_views(sampler_views, sampler_view_count);"
)
if not (
    ownership
    < first_dereference
    < view_validation
    < srv_stage
    < trace
    < yttrium_commit
    < identity_commit
    < view_commit
    < refresh
    < cleanup
):
    raise AssertionError("RotateResourceIdentities validate/stage/commit order is invalid")

yttrium_rotate = function_body(
    yttrium_text,
    "yttrium_gdi_resource_rotate_runtime_handles(",
    yttrium,
)
mixed_validation = yttrium_rotate.index("runtime_handle_count != count")
first_handle_write = yttrium_rotate.index("dst->hResource = src->hResource;")
if mixed_validation >= first_handle_write:
    raise AssertionError("Yttrium handle rotation mutates before full validation")

require(workflow_text, "check_dxgi_rotate_resource_identities.py", workflow)

print("DXGI RotateResourceIdentities contract: PASS")
