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

require(dxgi_text, "#include <d3d9.h>", dxgi)
for fragment in (
    "#define S_NOT_RESIDENT",
    "#define S_RESIDENT_IN_SHARED_MEMORY",
    "MAKE_D3DSTATUS(2165)",
    "MAKE_D3DSTATUS(2166)",
):
    if fragment in dxgi_text:
        raise AssertionError(f"residency status is redefined locally: {fragment}")

render_allocation = function_body(
    dxgi_text,
    "dxgi_get_d3dkmt_render_allocation(Device *device,",
    dxgi,
)
for fragment in (
    "WINSYS_HANDLE_TYPE_D3DKMT_ALLOC",
    "resource_get_handle(device->screen, device->pipe,",
):
    require(render_allocation, fragment, dxgi)
if "GetZinkPresentAllocation" in render_allocation:
    raise AssertionError("render residency substitutes the paired Present allocation")

present_allocation = function_body(
    dxgi_text,
    "dxgi_get_d3dkmt_allocation(Device *device,",
    dxgi,
)
for fragment in (
    "GetZinkPresentAllocation(resource)",
    "dxgi_get_d3dkmt_render_allocation(device, resource)",
):
    require(present_allocation, fragment, dxgi)

set_priority = function_body(
    dxgi_text,
    "_SetResourcePriority( DXGI_DDI_ARG_SETRESOURCEPRIORITY *SetResourcePriority )",
    dxgi,
)
for fragment in (
    "dxgi_get_d3dkmt_render_allocation(device, resource)",
    "D3DDDICB_SETPRIORITY priority = {};",
    "priority.NumAllocations = 1;",
    "priority.HandleList = &allocation;",
    "priority.pPriorities = &SetResourcePriority->Priority;",
    "device->device.KTCallbacks.pfnSetPriorityCb(",
    "device->device.hRTDevice, &priority)",
):
    require(set_priority, fragment, dxgi)
if "/* ignore */" in set_priority or "GetZinkPresentAllocation" in set_priority:
    raise AssertionError("resource priority remains ignored or uses a Present proxy")

query_residency = function_body(
    dxgi_text,
    "_QueryResourceResidency( DXGI_DDI_ARG_QUERYRESOURCERESIDENCY *QueryResourceResidency )",
    dxgi,
)
for fragment in (
    "QueryResourceResidency->pResources[i]",
    "dxgi_get_d3dkmt_render_allocation(device, resource)",
    "D3DDDICB_QUERYRESIDENCY query = {};",
    "query.NumAllocations = 1;",
    "query.HandleList = &allocation;",
    "query.pResidencyStatus = &residency;",
    "device->device.KTCallbacks.pfnQueryResidencyCb(",
    "if (FAILED(result))",
    "D3DDDI_RESIDENCYSTATUS_RESIDENTINGPUMEMORY",
    "DXGI_DDI_RESIDENCY_FULLY_RESIDENT",
    "D3DDDI_RESIDENCYSTATUS_RESIDENTINSHAREDMEMORY",
    "DXGI_DDI_RESIDENCY_RESIDENT_IN_SHARED_MEMORY",
    "D3DDDI_RESIDENCYSTATUS_NOTRESIDENT",
    "DXGI_DDI_RESIDENCY_EVICTED_TO_DISK",
    "return S_NOT_RESIDENT;",
    "return S_RESIDENT_IN_SHARED_MEMORY;",
):
    require(query_residency, fragment, dxgi)
if "GetZinkPresentAllocation" in query_residency:
    raise AssertionError("resource residency uses a paired Present proxy")

require(workflow_text, "check_dxgi_resource_residency.py", workflow)

print("DXGI resource priority and residency contract: PASS")
