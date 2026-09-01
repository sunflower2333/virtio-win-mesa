#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {fragment!r} in {source}")


def function_body(text: str, signature: str, source: Path) -> str:
    search_start = 0
    while True:
        start = text.find(signature, search_start)
        if start < 0:
            raise AssertionError(f"missing function {signature!r} in {source}")
        opening = text.find("{", start)
        if opening < 0:
            raise AssertionError(f"missing function body for {signature!r} in {source}")
        declaration_end = text.find(";", start, opening)
        if declaration_end < 0:
            break
        search_start = declaration_end + 1

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
zink = ROOT / "src/gallium/drivers/zink/zink_context.c"
yttrium = ROOT / "src/gallium/winsys/yttrium/gdi/yttrium_venus2_batch.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

device_text = device.read_text(encoding="utf-8")
zink_text = zink.read_text(encoding="utf-8")
yttrium_text = yttrium.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

reset_query = function_body(device_text, "DeviceHasReset(Device *pDevice)", device)
for fragment in (
    "pDevice ? pDevice->pipe : NULL",
    "pipe->get_device_reset_status",
    "pipe->get_device_reset_status(pipe) != PIPE_NO_RESET",
):
    require(reset_query, fragment, device)

flush = function_body(
    device_text,
    "Flush11_1(D3D10DDI_HDEVICE hDevice, UINT FlushFlags)",
    device,
)
for fragment in (
    "Device *device = CastDevice(hDevice);",
    "(void)FlushFlags;",
    "if (DeviceHasReset(device))\n      return FALSE;",
    "Flush(hDevice);",
    "return DeviceHasReset(device) ? FALSE : TRUE;",
):
    require(flush, fragment, device)
if flush.index("if (DeviceHasReset(device))") > flush.index("Flush(hDevice);"):
    raise AssertionError("Flush does not reject an already removed device")
if flush.strip().endswith("return TRUE;\n}"):
    raise AssertionError("Flush still reports unconditional success")

zink_flush = function_body(
    zink_text,
    "zink_flush(struct pipe_context *pctx,",
    zink,
)
for fragment in (
    "bool has_work = ctx->bs->has_work",
    "if (!has_work)",
    "flush_batch(ctx, false);",
):
    require(zink_flush, fragment, zink)
if zink_flush.index("if (!has_work)") > zink_flush.index("flush_batch(ctx, false);"):
    raise AssertionError("Zink submits before checking for pending work")

yttrium_batch = function_body(
    yttrium_text,
    "yttrium_venus_flush_command_batch(struct yttrium_venus *venus,",
    yttrium,
)
require(
    yttrium_batch,
    "if (!venus || !venus->display_copy_batch_recording)\n      return true;",
    yttrium,
)

yttrium_pending = function_body(
    yttrium_text,
    "yttrium_venus_flush_pending_submits(struct yttrium_venus *venus,",
    yttrium,
)
for fragment in (
    "const uint32_t count = venus->pending_submit_count;",
    "if (!count)\n      return true;",
):
    require(yttrium_pending, fragment, yttrium)

require(workflow_text, "check_zink_flush_device_removed.py", workflow)

print("Zink D3D Flush device-removal contract: PASS")
