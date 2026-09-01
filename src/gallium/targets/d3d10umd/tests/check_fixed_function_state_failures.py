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
output_merger = ROOT / "src/gallium/frontends/d3d10umd/OutputMerger.cpp"
rasterizer = ROOT / "src/gallium/frontends/d3d10umd/Rasterizer.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

shader_text = shader.read_text(encoding="utf-8")
output_merger_text = output_merger.read_text(encoding="utf-8")
rasterizer_text = rasterizer.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

sampler = function_body(shader_text, "CreateSampler(D3D10DDI_HDEVICE hDevice", shader)
for fragment in (
    "pSamplerState->handle = pipe->create_sampler_state(pipe, &state);",
    "if (!pSamplerState->handle)\n      SetError(hDevice, E_OUTOFMEMORY);",
):
    require(sampler, fragment, shader)

for signature in (
    "CreateBlendState(D3D10DDI_HDEVICE hDevice",
    "CreateBlendState1(D3D10DDI_HDEVICE hDevice",
    "CreateBlendState11_1Impl(D3D10DDI_HDEVICE hDevice",
):
    blend = function_body(output_merger_text, signature, output_merger)
    for fragment in (
        "pBlendState->handle = pipe->create_blend_state(pipe, &state);",
        "if (!pBlendState->handle)\n      SetError(hDevice, E_OUTOFMEMORY);",
    ):
        require(blend, fragment, output_merger)

depth_stencil = function_body(
    output_merger_text,
    "CreateDepthStencilState(",
    output_merger,
)
for fragment in (
    "pipe->create_depth_stencil_alpha_state(pipe, &state);",
    "if (!pDepthStencilState->handle)\n      SetError(hDevice, E_OUTOFMEMORY);",
):
    require(depth_stencil, fragment, output_merger)

raster = function_body(
    rasterizer_text,
    "CreateRasterizerState(",
    rasterizer,
)
for fragment in (
    "pRasterizerState->handle = NULL;",
    "pRasterizerState->discard_handle = NULL;",
    "pRasterizerState->handle = pipe->create_rasterizer_state(pipe, &state);",
    "if (!pRasterizerState->handle)",
    "pRasterizerState->discard_handle =",
    "if (!pRasterizerState->discard_handle)",
    "pipe->delete_rasterizer_state(pipe, pRasterizerState->handle);",
    "pRasterizerState->handle = NULL;",
    "SetError(hDevice, E_OUTOFMEMORY);",
):
    require(raster, fragment, rasterizer)

first_create = raster.index("pRasterizerState->handle = pipe->create_rasterizer_state")
first_failure = raster.index("if (!pRasterizerState->handle)")
second_create = raster.index("pRasterizerState->discard_handle =", first_create)
second_failure = raster.index("if (!pRasterizerState->discard_handle)")
cleanup = raster.index("pipe->delete_rasterizer_state", second_failure)
set_error = raster.index("SetError(hDevice, E_OUTOFMEMORY);", second_failure)
if not first_create < first_failure < second_create < second_failure:
    raise AssertionError("Rasterizer allocation checks are not ordered")
if not second_failure < cleanup < set_error:
    raise AssertionError("Rasterizer partial allocation is not released before error")

require(workflow_text, "check_fixed_function_state_failures.py", workflow)

print("D3D fixed-function state creation failure contract: PASS")
