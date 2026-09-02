#!/usr/bin/env python3

import re
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


dxgi = ROOT / "src/gallium/frontends/d3d10umd/DxgiFns.cpp"
device = ROOT / "src/gallium/frontends/d3d10umd/Device.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

dxgi_text = dxgi.read_text(encoding="utf-8")
device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

gamma = function_body(
    dxgi_text,
    "_GetGammaCaps( DXGI_DDI_ARG_GET_GAMMA_CONTROL_CAPS *GetCaps )",
    dxgi,
)
for fragment in (
    "if (!GetCaps || !GetCaps->pGammaCapabilities)",
    "Device *device = CastDevice(GetCaps->hDevice);",
    "if (!device)",
    "DXGI_GAMMA_CONTROL_CAPABILITIES *pCaps = GetCaps->pGammaCapabilities;",
    "memset(pCaps, 0, sizeof(*pCaps));",
    "if (dxgi_is_zink_screen(device))",
    "return DXGI_DDI_ERR_UNSUPPORTED;",
    "pCaps->ScaleAndOffsetSupported = false;",
    "pCaps->NumGammaControlPoints = 17;",
):
    require(gamma, fragment, dxgi)

ordered_fragments = (
    "if (!GetCaps || !GetCaps->pGammaCapabilities)",
    "Device *device = CastDevice(GetCaps->hDevice);",
    "if (!device)",
    "DXGI_GAMMA_CONTROL_CAPABILITIES *pCaps = GetCaps->pGammaCapabilities;",
    "memset(pCaps, 0, sizeof(*pCaps));",
    "if (dxgi_is_zink_screen(device))",
    "return DXGI_DDI_ERR_UNSUPPORTED;",
    "pCaps->ScaleAndOffsetSupported = false;",
)
positions = [gamma.index(fragment) for fragment in ordered_fragments]
if positions != sorted(positions):
    raise AssertionError("DXGI gamma validation/output/backend order is invalid")

registrations = re.findall(
    r"\bpfnGetGammaCaps\s*=\s*_GetGammaCaps\s*;", device_text
)
if len(registrations) != 3:
    raise AssertionError("GetGammaCaps must remain registered in all three DXGI tables")

require(workflow_text, "check_dxgi_gamma_caps.py", workflow)

print("DXGI gamma capability contract: PASS")
