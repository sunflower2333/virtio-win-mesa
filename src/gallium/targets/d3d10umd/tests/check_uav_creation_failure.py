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

create = function_body(
    shader_text,
    "CreateUnorderedAccessView(\n",
    shader,
)

for dimension in (
    "D3D10DDIRESOURCE_BUFFER",
    "D3D10DDIRESOURCE_TEXTURE1D",
    "D3D10DDIRESOURCE_TEXTURE2D",
    "D3D10DDIRESOURCE_TEXTURE3D",
):
    require(create, f"case {dimension}:", shader)

failure = """default:
      LOG_UNSUPPORTED(true);
      pUAView->image.resource = NULL;
      pipe_resource_reference(&pUAView->pipe_resource, NULL);
      pUAView->resource = NULL;
      SetError(hDevice, E_INVALIDARG);
      return;"""
require(create, failure, shader)

failure_start = create.index("default:")
release = create.index(
    "pipe_resource_reference(&pUAView->pipe_resource, NULL);",
    failure_start,
)
set_error = create.index("SetError(hDevice, E_INVALIDARG);", failure_start)
failure_return = create.index("return;", set_error)
publish = create.index("list_addtail", failure_return)
if not failure_start < release < set_error < failure_return < publish:
    raise AssertionError("UAV failure cleanup, error, return, and publication are misordered")

require(workflow_text, "check_uav_creation_failure.py", workflow)

print("D3D UAV creation failure contract: PASS")
