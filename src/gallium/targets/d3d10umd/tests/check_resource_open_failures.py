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


resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

resource_text = resource.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

open_resource = function_body(
    resource_text, "OpenResource(D3D10DDI_HDEVICE hDevice", resource
)
initialize = open_resource.index("memset(pResource, 0, sizeof *pResource);")
hook_check = open_resource.index("if (!pDevice->screen->resource_from_handle)")
hook_error = open_resource.index("SetError(hDevice, E_OUTOFMEMORY);", hook_check)
hook_return = open_resource.index("return;", hook_error)
lock = open_resource.index("mtx_lock(&pDevice->CreateResourceMtx);", hook_return)
import_resource = open_resource.index("pDevice->screen->resource_from_handle", lock)
import_check = open_resource.index("if (!pResource->resource)", import_resource)
import_rollback = open_resource.index("goto open_failure;", import_check)
transfer_create = open_resource.index("pResource->transfers =", import_rollback)
transfer_check = open_resource.index("if (!pResource->transfers)", transfer_create)
transfer_rollback = open_resource.index("goto open_failure;", transfer_check)
event = open_resource.index("ResourceEvent(RESOURCE_EVENT_OPEN", transfer_rollback)
publish = open_resource.index("RegisterResource(pDevice, pResource", event)
success_unlock = open_resource.index("goto unlock;", publish)
failure_label = open_resource.index("open_failure:", success_unlock)
cleanup = open_resource.index(
    "ReleaseResourceContents(pDevice->pipe, pResource);", failure_label
)
set_error = open_resource.index("SetError(hDevice, E_OUTOFMEMORY);", cleanup)
unlock = open_resource.index("unlock:", set_error)

if not (
    initialize
    < hook_check
    < hook_error
    < hook_return
    < lock
    < import_resource
    < import_check
    < import_rollback
    < transfer_create
    < transfer_check
    < transfer_rollback
    < event
    < publish
    < success_unlock
    < failure_label
    < cleanup
    < set_error
    < unlock
):
    raise AssertionError("opened-resource failure handling is misordered")

if open_resource[:failure_label].count("SetError(") != 1:
    raise AssertionError("opened-resource allocation failure reports before rollback")

require(workflow_text, "check_resource_open_failures.py", workflow)

print("D3D resource open failure contract: PASS")
