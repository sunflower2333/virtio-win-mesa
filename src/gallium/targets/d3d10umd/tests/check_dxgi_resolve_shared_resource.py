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
zink = ROOT / "src/gallium/drivers/zink/zink_context.c"
threaded = ROOT / "src/gallium/auxiliary/util/u_threaded_context.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

dxgi_text = dxgi.read_text(encoding="utf-8")
zink_text = zink.read_text(encoding="utf-8")
threaded_text = threaded.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

resolve = function_body(
    dxgi_text,
    "_ResolveSharedResource(DXGI_DDI_ARG_RESOLVESHAREDRESOURCE *Resolve)",
    dxgi,
)
for fragment in (
    "if (!Resolve)",
    "Device *device = CastDevice(Resolve->hDevice);",
    "Resource *resource = CastResource(Resolve->hResource);",
    "!device || !device->pipe || !resource || !resource->resource",
    "!device->pipe->flush_resource || !device->pipe->flush",
    "return E_NOTIMPL;",
    "device->pipe->flush_resource(device->pipe, resource->resource);",
    "yttrium_gdi_flush_labeled(device->pipe, NULL, 0,",
    '"D3D10 DXGI ResolveSharedResource");',
    "return S_OK;",
):
    require(resolve, fragment, dxgi)

resource_flush = resolve.index(
    "device->pipe->flush_resource(device->pipe, resource->resource);"
)
context_flush = resolve.index(
    "yttrium_gdi_flush_labeled(device->pipe, NULL, 0,"
)
success = resolve.index("return S_OK;")
if not resource_flush < context_flush < success:
    raise AssertionError("shared-resource preparation is not submitted before success")

zink_flush = function_body(zink_text, "zink_flush_resource(struct pipe_context *pctx,", zink)
for fragment in (
    "res->unflushed_transient",
    "resource_copy_region",
    "VK_QUEUE_FAMILY_FOREIGN_EXT",
):
    require(zink_flush, fragment, zink)
require(zink_text, "ctx->base.flush_resource = zink_flush_resource;", zink)

threaded_flush = function_body(
    threaded_text,
    "tc_flush_resource(struct pipe_context *_pipe, struct pipe_resource *resource)",
    threaded,
)
for fragment in (
    "tc_add_call(tc, TC_CALL_flush_resource,",
    "tc_set_resource_batch_usage(tc, resource);",
    "tc_set_resource_reference(&call->resource, resource);",
):
    require(threaded_flush, fragment, threaded)

require(workflow_text, "check_dxgi_resolve_shared_resource.py", workflow)

print("DXGI ResolveSharedResource contract: PASS")
