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
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

device_text = device.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

defined_body = function_body(device_text, "IsDefinedDxgiFormat(", device)
for fragment in (
    "value >= DXGI_FORMAT_R32G32B32A32_TYPELESS",
    "value <= DXGI_FORMAT_B4G4R4A4_UNORM",
    "value >= DXGI_FORMAT_P208 && value <= DXGI_FORMAT_V408",
    "value >= DXGI_FORMAT_SAMPLER_FEEDBACK_MIN_MIP_OPAQUE",
    "value <= DXGI_FORMAT_A4B4G4R4_UNORM",
):
    require(defined_body, fragment, device)

unsupported_body = function_body(device_text, "IsNotSupportedDxgiFormat(", device)
unsupported_formats = (
    "A8P8",
    "AI44",
    "AYUV",
    "IA44",
    "NV11",
    "P010",
    "P016",
    "P8",
    "R10G10B10_XR_BIAS_A2_UNORM",
    "Y210",
    "Y216",
    "Y410",
    "Y416",
)
for format_name in unsupported_formats:
    require(unsupported_body, f"case DXGI_FORMAT_{format_name}:", device)

check_body = function_body(device_text, "void APIENTRY\nCheckFormatSupport(", device)
null_guard = check_body.find("if (!pFormatCaps)")
zero_init = check_body.find("*pFormatCaps = 0;")
validity_guard = check_body.find("if (!IsDefinedDxgiFormat(Format))")
translation = check_body.find("FormatTranslate(Format, false)")
if min(null_guard, zero_init, validity_guard, translation) < 0:
    raise AssertionError("missing CheckFormatSupport validation sequence")
if not null_guard < zero_init < validity_guard < translation:
    raise AssertionError("CheckFormatSupport validation order is unsafe")

require(check_body, "SetError(hDevice, E_INVALIDARG);", device)
require(check_body, "SetError(hDevice, E_FAIL);", device)
require(
    check_body,
    "if (format == PIPE_FORMAT_NONE) {\n"
    "      if (IsNotSupportedDxgiFormat(Format))\n"
    "         *pFormatCaps = D3D10_DDI_FORMAT_SUPPORT_NOT_SUPPORTED;\n"
    "      return;\n"
    "   }",
    device,
)

if device_text.count("->pfnCheckFormatSupport = CheckFormatSupport;") < 2:
    raise AssertionError("CheckFormatSupport is not registered in both device tables")

require(workflow_text, "check_format_support_errors.py", workflow)

print("D3D CheckFormatSupport error contract: PASS")
