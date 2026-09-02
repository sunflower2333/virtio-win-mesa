#!/usr/bin/env python3

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


def function_body(text: str, signature: str, source: Path) -> str:
    offset = 0
    while True:
        start = text.find(signature, offset)
        if start < 0:
            raise AssertionError(f"missing function {signature!r} in {source}")

        opening = text.find("{", start)
        semicolon = text.find(";", start)
        if opening < 0:
            raise AssertionError(f"missing function body for {signature!r} in {source}")
        if 0 <= semicolon < opening:
            offset = semicolon + 1
            continue
        break

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


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", text)


draw = ROOT / "src/gallium/frontends/d3d10umd/Draw.cpp"
resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

draw_text = draw.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

sanitize_body = function_body(
    resource_text, "sanitize_d3d11_resource_misc_flags(", resource
)
require(sanitize_body, "D3D11_DDI_RESOURCE_MISC_DRAWINDIRECT_ARGS", resource)

create_body = canonical(
    function_body(resource_text, "CreateResource(D3D10DDI_HDEVICE", resource)
)
require(
    create_body,
    "pCreateResource->MiscFlags & D3D11_DDI_RESOURCE_MISC_DRAWINDIRECT_ARGS",
    resource,
)
require(create_body, "templat.bind |= PIPE_BIND_COMMAND_ARGS_BUFFER;", resource)

validation_body = canonical(
    function_body(draw_text, "ValidateIndirectDrawBuffer(", draw)
)
require(
    validation_body,
    "return resource && resource->resource && "
    "resource->resource->target == PIPE_BUFFER && "
    "(resource->MiscFlags & D3D11_DDI_RESOURCE_MISC_DRAWINDIRECT_ARGS) && "
    "(resource->resource->bind & PIPE_BIND_COMMAND_ARGS_BUFFER) && "
    "!(offset & 3) && offset <= resource->resource->width0 && "
    "size <= resource->resource->width0 - offset;",
    draw,
)

indexed_body = canonical(
    function_body(
        draw_text, "DrawIndexedInstancedIndirect(D3D10DDI_HDEVICE", draw
    )
)
require(indexed_body, "ValidateIndirectDrawBuffer(", draw)
require(indexed_body, "SetError(hDevice, E_INVALIDARG);", draw)
native_guard = indexed_body.find(
    "pDevice->index_buffer && pDevice->index_size && !pDevice->ib_offset"
)
native_info = indexed_body.find("struct pipe_draw_indirect_info indirect", native_guard)
fallback_read = indexed_body.find("ReadBufferRange(", native_guard)
fallback_draw = indexed_body.find("DrawIndexedInstanced(hDevice", fallback_read)
if min(native_guard, native_info, fallback_read, fallback_draw) < 0:
    raise AssertionError("indexed indirect native/fallback paths are incomplete")
if not native_guard < native_info < fallback_read < fallback_draw:
    raise AssertionError("indexed indirect native/fallback ordering is invalid")
for fragment in (
    "info.index_size = pDevice->index_size;",
    "info.index.resource = pDevice->index_buffer;",
    "info.primitive_restart = true;",
    "info.restart_index = pDevice->restart_index;",
    "indirect.offset = AlignedByteOffsetForArgs;",
    "indirect.stride = sizeof(DrawIndexedInstancedIndirectArgs);",
    "indirect.draw_count = 1;",
    "indirect.buffer = pArgs->resource;",
    "draw_vbo(pDevice->pipe, &info, 0, &indirect, NULL, 1);",
):
    require(indexed_body, fragment, draw)
require(indexed_body, "SetError(hDevice, E_OUTOFMEMORY);", draw)

nonindexed_body = canonical(
    function_body(draw_text, "DrawInstancedIndirect(D3D10DDI_HDEVICE", draw)
)
require(nonindexed_body, "ValidateIndirectDrawBuffer(", draw)
require(nonindexed_body, "SetError(hDevice, E_INVALIDARG);", draw)
for fragment in (
    "ResolveState(pDevice);",
    "RunPixelShaderEmulation(pDevice)",
    "util_draw_init_info(&info);",
    "info.mode = pDevice->primitive;",
    "indirect.offset = AlignedByteOffsetForArgs;",
    "indirect.stride = sizeof(DrawInstancedIndirectArgs);",
    "indirect.draw_count = 1;",
    "indirect.buffer = pArgs->resource;",
    "draw_vbo(pDevice->pipe, &info, 0, &indirect, NULL, 1);",
):
    require(nonindexed_body, fragment, draw)
if "ReadBufferRange(" in nonindexed_body:
    raise AssertionError("non-indexed indirect draw still performs CPU readback")

if device_text.count("pfnDrawIndexedInstancedIndirect") != 2:
    raise AssertionError("indexed indirect callback is not registered twice")
if device_text.count("pfnDrawInstancedIndirect") != 2:
    raise AssertionError("non-indexed indirect callback is not registered twice")
require(workflow_text, "check_indirect_draw_contract.py", workflow)

print("D3D indirect draw contract: PASS")
