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


resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

resource_text = resource.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

copy_region_body = function_body(
    resource_text, "void APIENTRY\nResourceCopyRegion(", resource
)
empty_guard = copy_region_body.find("if (pSrcBox &&")
restore = copy_region_body.find("RestoreConstantBufferOriginal(")
box_math = copy_region_body.find("src_box.width  = pSrcBox->right")
backend_copy = copy_region_body.find("pipe->resource_copy_region(")
if min(empty_guard, restore, box_math, backend_copy) < 0:
    raise AssertionError("missing ResourceCopyRegion empty-box ordering elements")
if not empty_guard < restore < box_math < backend_copy:
    raise AssertionError("empty boxes must return before copy-side effects")

for fragment in (
    "pSrcBox->left >= pSrcBox->right",
    "pSrcBox->top >= pSrcBox->bottom",
    "pSrcBox->front >= pSrcBox->back",
):
    require(copy_region_body, fragment, resource)

if device_text.count("pfnResourceCopyRegion = ResourceCopyRegion;") < 1:
    raise AssertionError("legacy ResourceCopyRegion registration is missing")
if device_text.count("pfnResourceConvertRegion = ResourceCopyRegion;") < 2:
    raise AssertionError("D3D10.1/11 ResourceConvertRegion aliases are missing")
require(device_text, "pfnResourceConvertRegion = ResourceCopyRegion11_1;", device)
require(workflow_text, "check_resource_copy_region_empty_box.py", workflow)

print("D3D ResourceCopyRegion empty-box contract: PASS")
