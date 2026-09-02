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


shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

shader_text = shader.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

create = function_body(shader_text, "CreateUnorderedAccessView(\n", shader)
pack_float = function_body(shader_text, "PackUAVClearFloat(", shader)
fill_buffer = function_body(shader_text, "FillUAVBufferClear(", shader)
clear_uint = function_body(
    shader_text, "ClearUnorderedAccessViewUint(\n", shader
)
clear_float = function_body(
    shader_text, "ClearUnorderedAccessViewFloat(\n", shader
)

require(
    create,
    "pUAView->clear_format = PIPE_FORMAT_NONE;",
    shader,
)
require(pack_float, "format == PIPE_FORMAT_NONE", shader)
require(pack_float, "util_format_pack_rgba(format, pattern, values, 1);", shader)

for fragment in (
    "uav->pipe_resource->target != PIPE_BUFFER",
    "unsigned offset = uav->image.u.buf.offset;",
    "unsigned size = uav->image.u.buf.size;",
    "if (offset >= resource->width0)",
    "if (!size || size > resource->width0 - offset)",
    "size = resource->width0 - offset;",
):
    require(fill_buffer, fragment, shader)

for body, packer in (
    (clear_uint, "PackUAVClearUint"),
    (clear_float, "PackUAVClearFloat"),
):
    buffer_branch = body.find("uav->pipe_resource->target == PIPE_BUFFER")
    pack = body.find(packer, buffer_branch)
    fill = body.find("FillUAVBufferClear(pipe, uav, pattern, pattern_size);", pack)
    if min(buffer_branch, pack, fill) < 0 or not buffer_branch < pack < fill:
        raise AssertionError(f"{packer} buffer clear ordering is incomplete")

require(clear_float, "ClearUAVTextureFloat(pipe, uav, Values);", shader)
require(workflow_text, "check_uav_buffer_float_clear.py", workflow)

print("D3D typed buffer UAV Float clear contract: PASS")
