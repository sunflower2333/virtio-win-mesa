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

for signature in (
    "CreateShaderResourceView(\n",
    "CreateShaderResourceView1(\n",
):
    create = function_body(shader_text, signature, shader)

    initialize = create.index("pSRView->handle = NULL;")
    invalid = create.index("default:", initialize)
    invalid_error = create.index("SetError(hDevice, E_INVALIDARG);", invalid)
    invalid_return = create.index("return;", invalid_error)
    backend_create = create.index(
        "pSRView->handle = pipe->create_sampler_view(pipe, resource, &desc);",
        invalid_return,
    )
    oom_check = create.index("if (!pSRView->handle)", backend_create)
    oom_error = create.index("SetError(hDevice, E_OUTOFMEMORY);", oom_check)
    oom_return = create.index("return;", oom_error)
    event = create.index("ResourceEvent(RESOURCE_EVENT_SRV_CREATE", oom_return)
    publish = create.index("list_addtail", event)

    if not (
        initialize
        < invalid
        < invalid_error
        < invalid_return
        < backend_create
        < oom_check
        < oom_error
        < oom_return
        < event
        < publish
    ):
        raise AssertionError(
            f"SRV failure handling or publication is misordered in {signature.strip()}"
        )

create11 = function_body(shader_text, "CreateShaderResourceView11(\n", shader)
delegate = create11.index("CreateShaderResourceView1(")
failure_check = create11.index("if (!pSRView || !pSRView->handle)", delegate)
failure_return = create11.index("return;", failure_check)
buffer_metadata = create11.index("pSRView->buffer_raw =", failure_return)
if not delegate < failure_check < failure_return < buffer_metadata:
    raise AssertionError("D3D11 SRV wrapper mutates metadata after delegated failure")

require(workflow_text, "check_shader_resource_view_creation_failure.py", workflow)

print("D3D shader resource view creation failure contract: PASS")
