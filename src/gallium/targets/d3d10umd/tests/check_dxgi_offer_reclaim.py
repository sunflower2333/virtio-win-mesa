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

collect = function_body(
    dxgi_text,
    "dxgi_collect_d3dkmt_render_allocations(",
    dxgi,
)
for fragment in (
    "resource_count && !resources",
    "*out_allocations = NULL;",
    "calloc(",
    "CastResource(resources[i])",
    "!resource || !resource->resource",
    "dxgi_get_d3dkmt_render_allocation(device, resource)",
    "free(allocations);",
    "return E_OUTOFMEMORY;",
    "return E_INVALIDARG;",
    "return E_FAIL;",
    "*out_allocations = allocations;",
):
    require(collect, fragment, dxgi)
if "GetZinkPresentAllocation" in collect or "dxgi_get_d3dkmt_allocation" in collect:
    raise AssertionError("offer/reclaim substitutes a paired Present allocation")

offer = function_body(
    dxgi_text,
    "_OfferResources(DXGI_DDI_ARG_OFFERRESOURCES *Offer)",
    dxgi,
)
for fragment in (
    "Offer->Resources && !Offer->pResources",
    "if (!Offer->Resources)",
    "!device->pipe->flush_resource",
    "!device->pipe->flush",
    "!device->device.KTCallbacks.pfnOfferAllocationsCb",
    "return E_NOTIMPL;",
    "dxgi_collect_d3dkmt_render_allocations(",
    "device->pipe->flush_resource(device->pipe, resource->resource);",
    "yttrium_gdi_flush_labeled(device->pipe, NULL, 0,",
    '"D3D10 DXGI OfferResources");',
    "D3DDDICB_OFFERALLOCATIONS offer = {};",
    "offer.pResources = NULL;",
    "offer.HandleList = allocations;",
    "offer.NumAllocations = Offer->Resources;",
    "offer.Priority = Offer->Priority;",
    "pfnOfferAllocationsCb(",
    "device->device.hRTDevice, &offer);",
    "free(allocations);",
    "return result;",
):
    require(offer, fragment, dxgi)

collect_position = offer.index("dxgi_collect_d3dkmt_render_allocations(")
resource_flush_position = offer.index("device->pipe->flush_resource(")
context_flush_position = offer.index("yttrium_gdi_flush_labeled(")
callback_position = offer.index("pfnOfferAllocationsCb(")
free_position = offer.rindex("free(allocations);")
if not (
    collect_position
    < resource_flush_position
    < context_flush_position
    < callback_position
    < free_position
):
    raise AssertionError("OfferResources prepare/submit/callback order is invalid")

reclaim = function_body(
    dxgi_text,
    "_ReclaimResources(DXGI_DDI_ARG_RECLAIMRESOURCES *Reclaim)",
    dxgi,
)
for fragment in (
    "Reclaim->Resources && !Reclaim->pResources",
    "if (!Reclaim->Resources)",
    "!device->device.KTCallbacks.pfnReclaimAllocationsCb",
    "return E_NOTIMPL;",
    "dxgi_collect_d3dkmt_render_allocations(",
    "D3DDDICB_RECLAIMALLOCATIONS reclaim = {};",
    "reclaim.pResources = NULL;",
    "reclaim.HandleList = allocations;",
    "reclaim.pDiscarded = Reclaim->pDiscarded;",
    "reclaim.NumAllocations = Reclaim->Resources;",
    "pfnReclaimAllocationsCb(",
    "device->device.hRTDevice, &reclaim);",
    "free(allocations);",
    "return result;",
):
    require(reclaim, fragment, dxgi)
if "Reclaim->pDiscarded[i]" in reclaim or "= FALSE" in reclaim:
    raise AssertionError("ReclaimResources fabricates retained contents")

reclaim_collect = reclaim.index("dxgi_collect_d3dkmt_render_allocations(")
reclaim_callback = reclaim.index("pfnReclaimAllocationsCb(")
reclaim_free = reclaim.rindex("free(allocations);")
if not reclaim_collect < reclaim_callback < reclaim_free:
    raise AssertionError("ReclaimResources callback/cleanup order is invalid")

require(workflow_text, "check_dxgi_offer_reclaim.py", workflow)

print("DXGI offer/reclaim contract: PASS")
