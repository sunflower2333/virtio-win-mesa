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

failure = function_body(
    shader_text,
    "FailShaderCreation(D3D10DDI_HDEVICE hDevice",
    shader,
)
for fragment in (
    "if (shader->state.tokens)",
    "ureg_free_tokens(shader->state.tokens);",
    "shader->state.tokens = NULL;",
    "shader->compute_state.prog = NULL;",
    "SetError(hDevice, error);",
):
    require(failure, fragment, shader)
if failure.index("ureg_free_tokens") > failure.index("SetError"):
    raise AssertionError("shader tokens are released after the runtime error")

creation_contracts = (
    (
        "CreateVertexShader(D3D10DDI_HDEVICE hDevice",
        "Shader_tgsi_translate",
        "pipe->create_vs_state",
    ),
    (
        "CreateGeometryShader(D3D10DDI_HDEVICE hDevice",
        "Shader_tgsi_translate",
        "pipe->create_gs_state",
    ),
    (
        "CreatePixelShader(D3D10DDI_HDEVICE hDevice",
        "Shader_tgsi_translate",
        "pipe->create_fs_state",
    ),
    (
        "CreateComputeShader(D3D10DDI_HDEVICE hDevice",
        "Shader_tgsi_translate",
        "pipe->create_compute_state",
    ),
)
for signature, translate, create in creation_contracts:
    body = function_body(shader_text, signature, shader)
    for fragment in (
        translate,
        "if (!pShader->state.tokens)",
        "FailShaderCreation(hDevice, pShader, E_FAIL);",
        create,
        "if (!pShader->handle)",
        "FailShaderCreation(hDevice, pShader, E_OUTOFMEMORY);",
    ):
        require(body, fragment, shader)
    if not (
        body.index(translate)
        < body.index("if (!pShader->state.tokens)")
        < body.index("FailShaderCreation(hDevice, pShader, E_FAIL);")
        < body.index(create)
        < body.index("if (!pShader->handle)")
        < body.index("FailShaderCreation(hDevice, pShader, E_OUTOFMEMORY);")
    ):
        raise AssertionError(f"shader failure checks are misordered in {signature}")

stream_output = function_body(
    shader_text,
    "CreateGeometryShaderWithStreamOutput(\n",
    shader,
)
for fragment in (
    "if (pData->pShaderCode)",
    "if (!pShader->state.tokens)",
    "FailShaderCreation(hDevice, pShader, E_FAIL);",
    "pShader->handle = pipe->create_gs_state(pipe, &pShader->state);",
    "if (!pShader->handle)",
    "FailShaderCreation(hDevice, pShader, E_OUTOFMEMORY);",
):
    require(stream_output, fragment, shader)
if stream_output.index("if (!pShader->state.tokens)") > stream_output.index(
    "pShader->handle = pipe->create_gs_state"
):
    raise AssertionError("stream-output translation failure is checked too late")
if stream_output.index("if (!pShader->handle)") > stream_output.index(
    "FailShaderCreation(hDevice, pShader, E_OUTOFMEMORY);"
):
    raise AssertionError("stream-output allocation failure is reported too early")

require(workflow_text, "check_shader_creation_failures.py", workflow)

print("D3D shader creation failure contract: PASS")
