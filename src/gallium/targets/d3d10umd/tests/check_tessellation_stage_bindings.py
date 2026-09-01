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
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

shader_text = shader.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

bindings = {
    "HsSetShaderResources(\n": (
        "SetShaderResources(MESA_SHADER_TESS_CTRL, hDevice, Offset, NumViews,\n"
        "                      phShaderResourceViews);"
    ),
    "DsSetShaderResources(\n": (
        "SetShaderResources(MESA_SHADER_TESS_EVAL, hDevice, Offset, NumViews,\n"
        "                      phShaderResourceViews);"
    ),
    "HsSetSamplers(D3D10DDI_HDEVICE hDevice": (
        "SetSamplers(MESA_SHADER_TESS_CTRL, hDevice, Offset, NumSamplers,\n"
        "               phSamplers);"
    ),
    "DsSetSamplers(D3D10DDI_HDEVICE hDevice": (
        "SetSamplers(MESA_SHADER_TESS_EVAL, hDevice, Offset, NumSamplers,\n"
        "               phSamplers);"
    ),
}

for signature, delegation in bindings.items():
    body = function_body(shader_text, signature, shader)
    require(body, delegation, shader)

for table in ("funcs", "p11DeviceFuncs"):
    for callback in bindings:
        name = callback.split("(", 1)[0]
        require(device_text, f"{table}->pfn{name} = {name};", device)

require(workflow_text, "check_tessellation_stage_bindings.py", workflow)

print("D3D tessellation stage binding contract: PASS")
