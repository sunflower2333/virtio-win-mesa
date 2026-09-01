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


device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

device_text = device.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

failure = function_body(
    device_text,
    "FailDevicePipelineStateCreation(Device *pDevice)",
    device,
)
for fragment in (
    "if (pDevice->default_depth_stencil_state)",
    "pipe->delete_depth_stencil_alpha_state(",
    "pDevice->default_depth_stencil_state = NULL;",
    "if (pDevice->empty_fs)",
    "DeleteEmptyShader(pDevice, MESA_SHADER_FRAGMENT, pDevice->empty_fs);",
    "pDevice->empty_fs = NULL;",
    "if (pDevice->empty_vs)",
    "DeleteEmptyShader(pDevice, MESA_SHADER_VERTEX, pDevice->empty_vs);",
    "pDevice->empty_vs = NULL;",
    "cso_destroy_context(pDevice->cso);",
    "pDevice->cso = NULL;",
    "pipe->destroy(pipe);",
    "pDevice->pipe = NULL;",
    "screen->destroy(screen);",
    "pDevice->screen = NULL;",
    "mtx_destroy(&pDevice->CreateResourceMtx);",
    "return E_OUTOFMEMORY;",
):
    require(failure, fragment, device)

depth_cleanup = failure.index("pipe->delete_depth_stencil_alpha_state")
fragment_cleanup = failure.index("DeleteEmptyShader(pDevice, MESA_SHADER_FRAGMENT")
vertex_cleanup = failure.index("DeleteEmptyShader(pDevice, MESA_SHADER_VERTEX")
cso_cleanup = failure.index("cso_destroy_context")
pipe_cleanup = failure.index("pipe->destroy")
screen_cleanup = failure.index("screen->destroy")
mutex_cleanup = failure.index("mtx_destroy")
oom = failure.index("return E_OUTOFMEMORY;")
if not (
    depth_cleanup
    < fragment_cleanup
    < vertex_cleanup
    < cso_cleanup
    < pipe_cleanup
    < screen_cleanup
    < mutex_cleanup
    < oom
):
    raise AssertionError("device creation rollback is misordered")

create = function_body(device_text, "CreateDevice(D3D10DDI_HADAPTER hAdapter", device)
vertex_create = create.index(
    "pDevice->empty_vs = CreateEmptyShader(pDevice, MESA_SHADER_VERTEX);"
)
vertex_failure = create.index("if (!pDevice->empty_vs)", vertex_create)
vertex_rollback = create.index(
    "return FailDevicePipelineStateCreation(pDevice);", vertex_failure
)
fragment_create = create.index(
    "pDevice->empty_fs = CreateEmptyShader(pDevice, MESA_SHADER_FRAGMENT);",
    vertex_failure,
)
fragment_failure = create.index("if (!pDevice->empty_fs)", fragment_create)
fragment_rollback = create.index(
    "return FailDevicePipelineStateCreation(pDevice);", fragment_failure
)
depth_create = create.index("pipe->create_depth_stencil_alpha_state", fragment_failure)
depth_failure = create.index(
    "if (!pDevice->default_depth_stencil_state)", depth_create
)
depth_rollback = create.index(
    "return FailDevicePipelineStateCreation(pDevice);", depth_failure
)
bind_vertex = create.index("pipe->bind_vs_state", depth_failure)
if not (
    vertex_create
    < vertex_failure
    < vertex_rollback
    < fragment_create
    < fragment_failure
    < fragment_rollback
    < depth_create
    < depth_failure
    < depth_rollback
    < bind_vertex
):
    raise AssertionError("default pipeline failures are not checked before bind")

failure_calls = create.count("return FailDevicePipelineStateCreation(pDevice);")
if failure_calls != 3:
    raise AssertionError(
        f"expected three default pipeline rollback calls, found {failure_calls}"
    )

empty_shader = function_body(shader_text, "CreateEmptyShader(Device *pDevice", shader)
if "assert(handle);" in empty_shader:
    raise AssertionError("empty shader backend failure still aborts before propagation")

require(workflow_text, "check_device_creation_failures.py", workflow)

print("D3D device creation failure contract: PASS")
