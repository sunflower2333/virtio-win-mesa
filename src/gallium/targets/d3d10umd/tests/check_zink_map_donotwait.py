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


def require_ordered(text: str, fragments: tuple[str, ...], source: Path) -> None:
    positions = []
    for fragment in fragments:
        require(text, fragment, source)
        positions.append(text.index(fragment))
    if positions != sorted(positions):
        raise AssertionError(f"incorrect ordering in {source}: {fragments!r}")


resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
zink_resource = ROOT / "src/gallium/drivers/zink/zink_resource.c"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

resource_text = resource.read_text(encoding="utf-8")
zink_resource_text = zink_resource.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

resource_map = function_body(
    resource_text,
    "ResourceMap(D3D10DDI_HDEVICE hDevice,",
    resource,
)
for fragment in (
    "Flags & D3D10_DDI_MAP_FLAG_DONOTWAIT",
    "threaded_context_is_resource_busy(pipe, resource, usage)",
    "usage |= PIPE_MAP_DONTBLOCK;",
    "do_not_wait ? DXGI_DDI_ERR_WASSTILLDRAWING : E_FAIL",
):
    require(resource_map, fragment, resource)
require_ordered(
    resource_map,
    (
        "threaded_context_is_resource_busy(pipe, resource, usage)",
        "usage |= PIPE_MAP_DONTBLOCK;",
        "RestoreConstantBufferOriginal(",
        "pipe->buffer_map(",
    ),
    resource,
)

destroy = function_body(
    zink_resource_text,
    "destroy_transfer(struct zink_context *ctx,",
    zink_resource,
)
for fragment in (
    "pipe_resource_reference(&trans->staging_res, NULL);",
    "pipe_resource_reference(&trans->base.b.resource, NULL);",
):
    require(destroy, fragment, zink_resource)

buffer_map = function_body(
    zink_resource_text,
    "zink_buffer_map(struct pipe_context *pctx,",
    zink_resource,
)
dontblock_start = buffer_map.find("else if (usage & PIPE_MAP_DONTBLOCK)")
dontblock_end = buffer_map.find("else if (", dontblock_start + 1)
if dontblock_start < 0 or dontblock_end < 0:
    raise AssertionError("missing bounded Zink buffer DONTBLOCK branch")
buffer_dontblock = buffer_map[dontblock_start:dontblock_end]
for fragment in (
    "usage & PIPE_MAP_READ",
    "check_usage |= ZINK_RESOURCE_ACCESS_WRITE",
    "usage & PIPE_MAP_WRITE",
    "check_usage |= ZINK_RESOURCE_ACCESS_RW",
    "zink_resource_usage_check_completion(screen, res, check_usage)",
):
    require(buffer_dontblock, fragment, zink_resource)
if buffer_dontblock.count("goto fail;") < 2 or "goto success;" in buffer_dontblock:
    raise AssertionError("Zink buffer DONTBLOCK failure publishes a transfer")

pending_clear = function_body(
    zink_resource_text,
    "zink_resource_has_pending_clear(const struct zink_context *ctx,",
    zink_resource,
)
for fragment in (
    "ctx->clears_enabled & (PIPE_CLEAR_COLOR0 << i)",
    "ctx->fb_state.cbufs[i].texture == pres",
    "ctx->clears_enabled & PIPE_CLEAR_DEPTHSTENCIL",
    "ctx->fb_state.zsbuf.texture == pres",
):
    require(pending_clear, fragment, zink_resource)

image_map = function_body(
    zink_resource_text,
    "zink_image_map(struct pipe_context *pctx,",
    zink_resource,
)
for fragment in (
    "usage & PIPE_MAP_DONTBLOCK",
    "check_usage |= ZINK_RESOURCE_ACCESS_WRITE",
    "check_usage |= ZINK_RESOURCE_ACCESS_RW",
    "zink_is_swapchain(res)",
    "zink_resource_has_pending_clear(ctx, pres)",
    "!res->linear || !res->obj->host_visible",
    "zink_resource_usage_check_completion(screen, res, check_usage)",
    "usage |= PIPE_MAP_UNSYNCHRONIZED;",
):
    require(image_map, fragment, zink_resource)
require_ordered(
    image_map,
    (
        "usage & PIPE_MAP_DONTBLOCK",
        "zink_resource_has_pending_clear(ctx, pres)",
        "zink_resource_usage_check_completion(screen, res, check_usage)",
        "create_transfer(ctx, pres, usage, box)",
        "zink_fb_clears_apply_region(",
        "zink_transfer_copy_bufimage(",
        "zink_fence_wait(pctx)",
    ),
    zink_resource,
)

require(workflow_text, "check_zink_map_donotwait.py", workflow)

print("Zink D3D ResourceMap DONOTWAIT contract: PASS")
