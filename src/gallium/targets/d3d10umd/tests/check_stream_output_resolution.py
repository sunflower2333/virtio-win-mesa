#!/usr/bin/env python3

import re
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


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", text)


state = ROOT / "src/gallium/frontends/d3d10umd/State.h"
shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
draw = ROOT / "src/gallium/frontends/d3d10umd/Draw.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

state_text = state.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
draw_text = draw.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

require(
    state_text,
    "unsigned stream_output_register_index[PIPE_MAX_SO_OUTPUTS];",
    state,
)
if "output_resolved" in state_text + shader_text + draw_text:
    raise AssertionError("one-shot stream-output resolution remains")

creation = canonical(
    function_body(
        shader_text,
        "CreateGeometryShaderWithStreamOutput(\n",
        shader,
    )
)
require(
    creation,
    "pShader->stream_output_register_index[idx] = "
    "pOutputStreamDecl->RegisterIndex;",
    shader,
)

resolve = canonical(function_body(draw_text, "ResolveState(", draw))
for fragment in (
    "struct pipe_shader_state resolved_state = gs->state;",
    "vs, gs->stream_output_register_index[i]",
    "void *new_handle = pipe->create_gs_state(pipe, &resolved_state);",
    "if (!new_handle)",
    "DebugPrintf(\"%s: failed to create remapped stream-output state\\n\", "
    "__func__);",
    "SetError(hDevice, E_OUTOFMEMORY);",
    "return false;",
    "old_handle = gs->handle;",
    "gs->state.stream_output = resolved_state.stream_output;",
    "gs->handle = new_handle;",
    "pipe->bind_gs_state(pipe, gs->handle);",
    "pipe->delete_gs_state(pipe, old_handle);",
    "return true;",
):
    require(resolve, fragment, draw)

if "YTTRIUM_WARN" in resolve:
    raise AssertionError("ResolveState uses an unavailable Yttrium logging macro")

create = resolve.index("create_gs_state")
failure = resolve.index("if (!new_handle)", create)
commit = resolve.index("gs->handle = new_handle;", failure)
bind = resolve.index("bind_gs_state", commit)
destroy = resolve.index("delete_gs_state", bind)
if not create < failure < commit < bind < destroy:
    raise AssertionError("stream-output replacement is not transactional")

draw_callbacks = (
    "Draw(D3D10DDI_HDEVICE",
    "DrawIndexed(D3D10DDI_HDEVICE",
    "DrawInstanced(D3D10DDI_HDEVICE",
    "DrawIndexedInstanced(D3D10DDI_HDEVICE",
    "DrawIndexedInstancedIndirect(D3D10DDI_HDEVICE",
    "DrawInstancedIndirect(D3D10DDI_HDEVICE",
    "DrawAuto(D3D10DDI_HDEVICE",
)
for signature in draw_callbacks:
    body = canonical(function_body(draw_text, signature, draw))
    require(body, "if (!ResolveState(hDevice, pDevice))", draw)

require(workflow_text, "check_stream_output_resolution.py", workflow)

print("D3D stream-output resolution contract: PASS")
