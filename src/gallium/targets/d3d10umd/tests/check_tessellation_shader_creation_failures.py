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
    "FailTessellationShaderCreation(D3D10DDI_HDEVICE hDevice",
    shader,
)
for fragment in (
    "FREE(pShader->tessellation_code);",
    "pShader->tessellation_code = NULL;",
    "pShader->tessellation_code_size = 0;",
    "pShader->tessellation_properties_valid = false;",
    "pShader->tessellation_compiled_properties_valid = false;",
    "FailShaderCreation(hDevice, pShader, error);",
):
    require(failure, fragment, shader)
if failure.index("FREE(pShader->tessellation_code);") > failure.index(
    "FailShaderCreation(hDevice, pShader, error);"
):
    raise AssertionError("tessellation bytecode is released after SetError")

initialize = function_body(
    shader_text,
    "InitD3D11TessellationShader(\n",
    shader,
)
require(
    shader_text,
    "static bool\nInitD3D11TessellationShader(\n",
    shader,
)
copy = initialize.index("CopyTessellationCode")
domain_success = initialize.index("if (stage == MESA_SHADER_TESS_EVAL)", copy)
translate = initialize.index("Shader_tgsi_translate", domain_success)
require(
    initialize[domain_success:translate],
    "if (stage == MESA_SHADER_TESS_EVAL)\n      return true;",
    shader,
)
translation_failure = initialize.index(
    "FailTessellationShaderCreation(hDevice, pShader, E_INVALIDARG);",
    translate,
)
create = initialize.index("pipe->create_tcs_state", translation_failure)
allocation_failure = initialize.index(
    "FailTessellationShaderCreation(hDevice, pShader, E_OUTOFMEMORY);",
    create,
)
success = initialize.rindex("return true;")
if not (
    copy
    < domain_success
    < translate
    < translation_failure
    < create
    < allocation_failure
    < success
):
    raise AssertionError("Hull/Domain creation failure handling is misordered")

hull = function_body(shader_text, "CreateHullShader(\n", shader)
delegate = hull.index("InitD3D11TessellationShader")
failure_return = hull.index("return;", delegate)
primitive = hull.index("tess_output_primitive", failure_return)
if not delegate < failure_return < primitive:
    raise AssertionError("Hull wrapper mutates metadata after initialization failure")

domain = function_body(shader_text, "CreateDomainShader(\n", shader)
require(domain, "InitD3D11TessellationShader", shader)

require(workflow_text, "check_tessellation_shader_creation_failures.py", workflow)

print("D3D tessellation shader creation failure contract: PASS")
