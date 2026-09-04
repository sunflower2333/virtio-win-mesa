#!/usr/bin/env python3

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


def function_body(text: str, signature: str, source: Path) -> str:
    offset = 0
    while True:
        start = text.find(signature, offset)
        if start < 0:
            raise AssertionError(f"missing function {signature!r} in {source}")

        opening = text.find("{", start)
        semicolon = text.find(";", start)
        if opening < 0:
            raise AssertionError(f"missing function body for {signature!r} in {source}")
        if 0 <= semicolon < opening:
            offset = semicolon + 1
            continue
        break

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

validation_body = function_body(
    device_text, "ValidateMultisampleQualityLevelsQuery(", device
)
null_guard = validation_body.find("if (!pNumQualityLevels)")
zero_init = validation_body.find("*pNumQualityLevels = 0;")
format_guard = validation_body.find("if (!IsDefinedDxgiFormat(Format))")
if min(null_guard, zero_init, format_guard) < 0:
    raise AssertionError("missing multisample query validation sequence")
if not null_guard < zero_init < format_guard:
    raise AssertionError("multisample query validation order is unsafe")
if validation_body.count("SetError(hDevice, E_INVALIDARG);") != 2:
    raise AssertionError("multisample validation must report both invalid arguments")

base_body = function_body(
    device_text, "CheckMultisampleQualityLevels(D3D10DDI_HDEVICE", device
)
validation = base_body.find("ValidateMultisampleQualityLevelsQuery(")
single_sample = base_body.find("if (SampleCount == 1)")
if min(validation, single_sample) < 0:
    raise AssertionError("missing base multisample query sequence")
if not validation < single_sample:
    raise AssertionError("validation must precede sample-count-one handling")
require(base_body, "*pNumQualityLevels = 1;", device)

# This entry decides whether a D3D11 device can be created at all.  Measured on
# Windows 11 ARM64 against a WDDM adapter carrying Turnip: with the screen query
# in place D3D11CreateDevice returns DXGI_ERROR_DRIVER_INTERNAL_ERROR for every
# feature level, and replacing only this one device function table entry makes
# the same call succeed at feature level 11_0.  Keep the query out until the
# underlying fault is found.
for screen_query in (
    "CastPipeContext(",
    "IsYttriumMsaaFormatSupported(",
    "is_format_supported_with_fallback(",
):
    if screen_query in base_body:
        raise AssertionError(
            "CheckMultisampleQualityLevels must not query the screen: "
            f"{screen_query} breaks D3D11 device creation"
        )

wddm_body = function_body(
    device_text,
    "CheckMultisampleQualityLevelsWDDM1_3(D3D10DDI_HDEVICE",
    device,
)
require(wddm_body, "if (!Flags)", device)
require(wddm_body, "CheckMultisampleQualityLevels(hDevice, Format, SampleCount,", device)
require(wddm_body, "ValidateMultisampleQualityLevelsQuery(", device)
require(wddm_body, "if (SampleCount == 1)", device)
for unrelated_quality_value in (
    "D3D10_1_DDIARG_STANDARD_MULTISAMPLE_PATTERN",
    "D3D10_1_DDIARG_CENTER_MULTISAMPLE_PATTERN",
):
    if unrelated_quality_value in wddm_body:
        raise AssertionError(
            f"WDDM 1.3 flags still use unrelated {unrelated_quality_value}"
        )

base_registrations = re.findall(
    r"pfnCheckMultisampleQualityLevels\s*=\s*"
    r"CheckMultisampleQualityLevels\s*;",
    device_text,
)
if len(base_registrations) != 2:
    raise AssertionError("base multisample callback is not registered twice")
if device_text.count("CheckMultisampleQualityLevelsWDDM1_3;") != 1:
    raise AssertionError("WDDM 1.3 multisample callback is not registered once")

require(workflow_text, "check_multisample_quality_levels.py", workflow)

print("D3D multisample quality-level contract: PASS")
