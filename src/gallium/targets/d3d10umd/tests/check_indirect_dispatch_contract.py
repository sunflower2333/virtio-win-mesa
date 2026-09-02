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


state = ROOT / "src/gallium/frontends/d3d10umd/State.h"
shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

state_text = state.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

validation_body = canonical(function_body(state_text, "ValidateIndirectBuffer(", state))
require(
    validation_body,
    "return resource && resource->resource && "
    "resource->resource->target == PIPE_BUFFER && "
    "(resource->MiscFlags & D3D11_DDI_RESOURCE_MISC_DRAWINDIRECT_ARGS) && "
    "(resource->resource->bind & PIPE_BIND_COMMAND_ARGS_BUFFER) && "
    "!(offset & 3) && offset <= resource->resource->width0 && "
    "size <= resource->resource->width0 - offset;",
    state,
)

dispatch_body = canonical(
    function_body(shader_text, "DispatchIndirect(D3D10DDI_HDEVICE", shader)
)
require(dispatch_body, "ValidateIndirectBuffer(", shader)
require(dispatch_body, "SetError(hDevice, E_INVALIDARG);", shader)

emulation_guard = dispatch_body.find(
    "cs->compute_emulation != COMPUTE_EMULATION_NONE"
)
fallback_read = dispatch_body.find("ReadBufferRange(", emulation_guard)
fallback_dispatch = dispatch_body.find("Dispatch(hDevice", fallback_read)
handle_guard = dispatch_body.find("if (!cs->handle)", fallback_dispatch)
native_info = dispatch_body.find("struct pipe_grid_info info", handle_guard)
native_submit = dispatch_body.find("launch_grid(pipe, &info);", native_info)
if min(
    emulation_guard,
    fallback_read,
    fallback_dispatch,
    handle_guard,
    native_info,
    native_submit,
) < 0:
    raise AssertionError("indirect dispatch native/fallback paths are incomplete")
if not (
    emulation_guard
    < fallback_read
    < fallback_dispatch
    < handle_guard
    < native_info
    < native_submit
):
    raise AssertionError("indirect dispatch native/fallback ordering is invalid")

for fragment in (
    "info.work_dim = 3;",
    "info.block[0] = cs->thread_group_size[0] ? cs->thread_group_size[0] : 1;",
    "info.block[1] = cs->thread_group_size[1] ? cs->thread_group_size[1] : 1;",
    "info.block[2] = cs->thread_group_size[2] ? cs->thread_group_size[2] : 1;",
    "info.indirect = args->resource;",
    "info.indirect_offset = AlignedByteOffsetForArgs;",
):
    require(dispatch_body, fragment, shader)

if dispatch_body.count("ReadBufferRange(") != 1:
    raise AssertionError("indirect dispatch must read back only for emulation")

if device_text.count("pfnDispatchIndirect") != 2:
    raise AssertionError("indirect dispatch callback is not registered twice")
require(workflow_text, "check_indirect_dispatch_contract.py", workflow)

print("D3D indirect dispatch contract: PASS")
