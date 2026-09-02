#!/usr/bin/env python3

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


state = ROOT / "src/gallium/frontends/d3d10umd/State.h"
shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
shader_tgsi = ROOT / "src/gallium/frontends/d3d10umd/ShaderTGSI.c"
output_merger = ROOT / "src/gallium/frontends/d3d10umd/OutputMerger.cpp"
tgsi_to_nir = ROOT / "src/gallium/auxiliary/nir/tgsi_to_nir.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

state_text = state.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
shader_tgsi_text = shader_tgsi.read_text(encoding="utf-8")
output_merger_text = output_merger.read_text(encoding="utf-8")
tgsi_to_nir_text = tgsi_to_nir.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

require(state_text, "struct pipe_resource *counter_resource;", state)

create = function_body(shader_text, "CreateUnorderedAccessView(\n", shader)
for fragment in (
    "PIPE_BIND_SHADER_BUFFER",
    "sizeof(pUAView->counter_value)",
    "UpdateUnorderedAccessViewCounter(pDevice, pUAView, 0)",
    "pipe_resource_reference(&pUAView->counter_resource, NULL);",
    "SetError(hDevice, E_OUTOFMEMORY);",
):
    require(create, fragment, shader)

destroy = function_body(shader_text, "DestroyUnorderedAccessView(\n", shader)
require(destroy, "pipe_resource_reference(&pUAView->counter_resource, NULL);", shader)

update = function_body(
    shader_text,
    "UpdateUnorderedAccessViewCounter(Device *pDevice,",
    shader,
)
require(update, "WriteBufferRange", shader)
require(update, "uav->counter_value = value;", shader)

bind = function_body(
    shader_text,
    "BindUnorderedAccessViewCounters(Device *pDevice,",
    shader,
)
for fragment in (
    "PIPE_MAX_SHADER_BUFFERS",
    "uav->counter_resource",
    "pipe->set_shader_buffers",
):
    require(bind, fragment, shader)

cs_bind = function_body(shader_text, "CsSetUnorderedAccessViews(\n", shader)
require(cs_bind, "UpdateUnorderedAccessViewCounter(pDevice, uav,", shader)
require(cs_bind, "BindUnorderedAccessViewCounters(pDevice, MESA_SHADER_COMPUTE", shader)

graphics_bind = function_body(
    output_merger_text,
    "SetRenderTargets11(\n",
    output_merger,
)
require(graphics_bind, "UpdateUnorderedAccessViewCounter(pDevice, uav,", output_merger)
require(graphics_bind, "BindUnorderedAccessViewCounters(pDevice, stage", output_merger)

copy = function_body(shader_text, "CopyStructureCount(D3D10DDI_HDEVICE", shader)
for fragment in (
    "src->counter_resource",
    "if (!CheckPredicate(pDevice))",
    "pipe->resource_copy_region",
):
    require(copy, fragment, shader)
if "WriteBufferRange" in copy:
    raise AssertionError("CopyStructureCount still uploads the CPU counter shadow")

for signature in (
    "RunWineUAVCounterConsumeCompute(Device *pDevice,",
    "RunWineUAVCounterProduceCompute(Device *pDevice,",
    "RunWineAppendDispatchArgsCompute(Device *pDevice)",
):
    body = function_body(shader_text, signature, shader)
    require(body, "ReadBufferRange", shader)
    require(body, "UpdateUnorderedAccessViewCounter", shader)

atomic_translation = function_body(
    shader_tgsi_text,
    "Shader_tgsi_translate(const unsigned *code,",
    shader_tgsi,
)
for fragment in (
    "ureg_DECL_buffer(ureg, image_index, true)",
    "TGSI_OPCODE_ATOMUADD",
    "PIPE_MAX_SHADER_BUFFERS",
    "DX10_SM5_OPCODE_IMM_ATOMIC_ALLOC",
    "DX10_SM5_OPCODE_IMM_ATOMIC_CONSUME",
):
    require(atomic_translation, fragment, shader_tgsi)
if "ureg_MOV(ureg, result, ureg_imm1u(ureg, 0));" in atomic_translation:
    raise AssertionError("native append/consume still returns a constant zero")

memory = function_body(tgsi_to_nir_text, "ttn_mem(struct ttn_compile *c,", tgsi_to_nir)
for fragment in (
    "nir_intrinsic_ssbo_atomic",
    "nir_intrinsic_ssbo_atomic_swap",
    "nir_intrinsic_set_atomic_op",
):
    require(memory, fragment, tgsi_to_nir)

require(workflow_text, "check_uav_counter_contract.py", workflow)

print("D3D UAV hidden counter contract: PASS")
