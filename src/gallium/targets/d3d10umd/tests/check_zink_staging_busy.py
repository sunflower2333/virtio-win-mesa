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


threaded_header = ROOT / "src/gallium/auxiliary/util/u_threaded_context.h"
threaded_source = ROOT / "src/gallium/auxiliary/util/u_threaded_context.c"
resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
zink_context = ROOT / "src/gallium/drivers/zink/zink_context.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

threaded_header_text = threaded_header.read_text(encoding="utf-8")
threaded_source_text = threaded_source.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
zink_context_text = zink_context.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

for fragment in (
    "threaded_context_is_resource_busy(struct pipe_context *pipe,",
    "struct pipe_resource *resource,",
    "unsigned usage);",
):
    require(threaded_header_text, fragment, threaded_header)

threaded_busy = function_body(
    threaded_source_text,
    "threaded_context_is_resource_busy(struct pipe_context *pipe,",
    threaded_source,
)
for fragment in (
    "!pipe || !resource || !pipe->priv",
    "!tc->options.is_resource_busy",
    "resource->target == PIPE_BUFFER",
    "tc_is_buffer_busy(tc, tres, usage)",
    "tc_resource_batch_usage_test_busy(tc, resource)",
    "tc->options.is_resource_busy(tc->pipe->screen, resource, usage)",
):
    require(threaded_busy, fragment, threaded_source)
if threaded_busy.count("return true;") < 3:
    raise AssertionError("threaded busy query does not fail conservatively")

staging_busy = function_body(
    resource_text,
    "ResourceIsStagingBusy(D3D10DDI_HDEVICE hDevice,",
    resource,
)
for fragment in (
    "Device *device = CastDevice(hDevice);",
    "Resource *resource = CastResource(hResource);",
    "!device || !device->pipe || !resource || !resource->resource",
    "threaded_context_is_resource_busy(device->pipe,",
    "resource->resource,",
    "PIPE_MAP_READ",
    "? TRUE : FALSE",
):
    require(staging_busy, fragment, resource)
if "return false;" in staging_busy or "zink_" in staging_busy:
    raise AssertionError("D3D staging busy query bypasses Gallium semantics")

zink_busy = function_body(
    zink_context_text,
    "zink_context_is_resource_busy(struct pipe_screen *pscreen,",
    zink_context,
)
for fragment in (
    "usage & PIPE_MAP_READ",
    "check_usage |= ZINK_RESOURCE_ACCESS_WRITE",
    "!zink_resource_usage_check_completion(screen, res, check_usage)",
):
    require(zink_busy, fragment, zink_context)

require(workflow_text, "check_zink_staging_busy.py", workflow)

print("Zink D3D staging busy contract: PASS")
