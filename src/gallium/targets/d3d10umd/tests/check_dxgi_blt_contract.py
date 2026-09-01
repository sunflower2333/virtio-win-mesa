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

subresource = function_body(
    dxgi_text,
    "dxgi_blt_subresource(struct pipe_resource *resource,",
    dxgi,
)
for fragment in (
    "PIPE_TEXTURE_2D",
    "PIPE_TEXTURE_2D_ARRAY",
    "*layer >= resource->array_size",
    "u_minify(resource->width0, *level)",
    "u_minify(resource->height0, *level)",
):
    require(subresource, fragment, dxgi)

blit = function_body(dxgi_text, "dxgi_blt(Device *device,", dxgi)
for fragment in (
    "device->pipe->blit",
    "flags.Reserved",
    "dst_resource->target != PIPE_TEXTURE_2D",
    "src_resource->target != PIPE_TEXTURE_2D",
    "!flags.Stretch",
    "!flags.Convert",
    "flags.Resolve",
    "DXGI_DDI_MODE_ROTATION_UNSPECIFIED",
    "DXGI_DDI_MODE_ROTATION_IDENTITY",
    "DXGI_DDI_MODE_ROTATION_ROTATE180",
    "info.src.box.width = -(int)copy_width;",
    "info.src.box.height = -(int)copy_height;",
    "DXGI_DDI_MODE_ROTATION_ROTATE90",
    "DXGI_DDI_MODE_ROTATION_ROTATE270",
    "return DXGI_DDI_ERR_UNSUPPORTED;",
    "info.dst.format = dst_resource->format;",
    "info.src.format = src_resource->format;",
    "util_format_get_mask(dst_resource->format)",
    "PIPE_MASK_RGBA",
    "flags.Stretch ? PIPE_TEX_FILTER_LINEAR",
    "PIPE_TEX_FILTER_NEAREST",
    "device->pipe->blit(device->pipe, &info);",
    "if (flags.Present)",
    "dxgi_flush_frontbuffer(device, dst_resource, dst_level, dst_layer, NULL);",
):
    require(blit, fragment, dxgi)
if "resource_copy_region" in blit:
    raise AssertionError("DXGI flag-aware Blt falls back to a straight copy")

legacy = function_body(dxgi_text, "_Blt(DXGI_DDI_ARG_BLT *Blt)", dxgi)
for fragment in (
    "const struct dxgi_blt_rect dst_rect",
    "src, Blt->SrcSubresource, NULL,",
    "Blt->Flags, Blt->Rotate",
):
    require(legacy, fragment, dxgi)
if "resource_copy_region" in legacy:
    raise AssertionError("legacy DXGI Blt bypasses the shared contract")

blt1 = function_body(dxgi_text, "_Blt1(DXGI_DDI_ARG_BLT1 *Blt)", dxgi)
for fragment in (
    "const struct dxgi_blt_rect dst_rect",
    "const struct dxgi_blt_rect src_rect",
    "Blt->SrcLeft, Blt->SrcTop, Blt->SrcRight, Blt->SrcBottom",
    "src, Blt->SrcSubresource, &src_rect,",
    "Blt->Flags, Blt->Rotate",
):
    require(blt1, fragment, dxgi)
if "resource_copy_region" in blt1:
    raise AssertionError("DXGI Blt1 bypasses the shared contract")

require(workflow_text, "check_dxgi_blt_contract.py", workflow)

print("DXGI Blt/Blt1 contract: PASS")
