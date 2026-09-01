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


output_merger = ROOT / "src/gallium/frontends/d3d10umd/OutputMerger.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

output_merger_text = output_merger.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

for signature, view in (
    ("CreateRenderTargetView(\n", "pRTView"),
    ("CreateDepthStencilView(\n", "pDSView"),
):
    create = function_body(output_merger_text, signature, output_merger)

    retain = create.index("pipe_resource_reference(&desc.texture, resource);")
    invalid = create.index("default:", retain)
    release = create.index(
        "pipe_resource_reference(&desc.texture, NULL);",
        invalid,
    )
    clear_resource = create.index(f"{view}->resource = NULL;", release)
    error = create.index("SetError(hDevice, E_INVALIDARG);", clear_resource)
    failure_return = create.index("return;", error)
    assign_surface = create.index(f"{view}->surface = desc;", failure_return)
    event = create.index("ResourceEvent(", assign_surface)
    publish = create.index("list_addtail", event)

    if not (
        retain
        < invalid
        < release
        < clear_resource
        < error
        < failure_return
        < assign_surface
        < event
        < publish
    ):
        raise AssertionError(
            f"view failure cleanup or publication is misordered in {signature.strip()}"
        )

require(workflow_text, "check_render_depth_view_creation_failure.py", workflow)

print("D3D render/depth view creation failure contract: PASS")
