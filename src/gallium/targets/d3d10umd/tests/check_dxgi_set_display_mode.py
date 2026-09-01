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


dxgi = ROOT / "src/gallium/frontends/d3d10umd/DxgiFns.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

dxgi_text = dxgi.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

set_mode = function_body(
    dxgi_text,
    "_SetDisplayMode( DXGI_DDI_ARG_SETDISPLAYMODE *SetDisplayMode )",
    dxgi,
)
for fragment in (
    "if (!SetDisplayMode)",
    "!device || !device->screen || !res || !res->resource",
    "SetDisplayMode->SubResourceIndex >= res->NumSubResources",
    "if (!device->device.base.setDisplayMode ||",
    "!device->device.KTCallbacks.pfnSetDisplayModeCb",
    "return E_NOTIMPL;",
    "res->zink_present_primary ? GetZinkPresentAllocation(res) : 0",
    "handle.type = WINSYS_HANDLE_TYPE_D3DKMT_ALLOC;",
    "if (!device->screen->resource_get_handle)",
    "device->screen->resource_get_handle(device->screen, NULL,",
    "!handle.handle",
    "return E_FAIL;",
    "HRESULT result =",
    "device->device.base.setDisplayMode(&device->device.base, kmt_handle)",
    "return result;",
):
    require(set_mode, fragment, dxgi)

if "return S_OK;" in set_mode:
    raise AssertionError("SetDisplayMode hides an allocation or callback failure")

primary_position = set_mode.index("res->zink_present_primary")
export_position = set_mode.index("resource_get_handle", primary_position)
callback_position = set_mode.index("device->device.base.setDisplayMode(")
status_position = set_mode.index("return result;")
if not primary_position < export_position < callback_position < status_position:
    raise AssertionError("SetDisplayMode handle/callback/status order is invalid")

require(workflow_text, "check_dxgi_set_display_mode.py", workflow)

print("DXGI SetDisplayMode contract: PASS")
