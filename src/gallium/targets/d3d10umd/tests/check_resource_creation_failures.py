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

create = function_body(resource_text, "CreateResource(D3D10DDI_HDEVICE hDevice", resource)
initialize = create.index("memset(pResource, 0, sizeof *pResource);")
validate = create.index("if (!validate_resource_dimension(pCreateResource))")
pipe_create = create.index("screen->resource_create(screen, &templat)", validate)
subresources = create.index("pResource->NumSubResources =", pipe_create)
transfer_create = create.index("pResource->transfers =", subresources)
transfer_check = create.index("if (!pResource->transfers)", transfer_create)
paired_create = create.index("create_zink_present_allocation", transfer_check)
buffer_map = create.index("pipe->buffer_map", paired_create)
buffer_map_check = create.index("if (!map)", buffer_map)
buffer_failure = create.index("creation_error = E_OUTOFMEMORY;", buffer_map_check)
buffer_rollback = create.index("goto create_failure;", buffer_failure)
buffer_unmap = create.index("pipe_buffer_unmap", buffer_rollback)
texture_map = create.index("pipe->texture_map", buffer_unmap)
texture_map_check = create.index("if (!map)", texture_map)
texture_failure = create.index("creation_error = E_OUTOFMEMORY;", texture_map_check)
texture_rollback = create.index("goto create_failure;", texture_failure)
texture_unmap = create.index("pipe_texture_unmap", texture_rollback)
event = create.index("ResourceEvent(RESOURCE_EVENT_CREATE", texture_unmap)
publish = create.index("RegisterResource(device, pResource", event)
failure_label = create.index("create_failure:", publish)
content_cleanup = create.index("ReleaseResourceContents(pipe, pResource);", failure_label)
present_cleanup = create.index(
    "release_zink_present_allocation(device, pResource);", content_cleanup
)
set_error = create.index("SetError(hDevice, creation_error);", present_cleanup)
unlock = create.index("unlock:", set_error)

if not (
    initialize
    < validate
    < pipe_create
    < subresources
    < transfer_create
    < transfer_check
    < paired_create
    < buffer_map
    < buffer_map_check
    < buffer_failure
    < buffer_rollback
    < buffer_unmap
    < texture_map
    < texture_map_check
    < texture_failure
    < texture_rollback
    < texture_unmap
    < event
    < publish
    < failure_label
    < content_cleanup
    < present_cleanup
    < set_error
    < unlock
):
    raise AssertionError("resource creation failure handling is misordered")

if "assert(map);" in create:
    raise AssertionError("initial-data map failure still relies on a debug assertion")

validation_errors = create[:failure_label].count("SetError(")
if validation_errors != 1 or "SetError(hDevice, DXGI_DDI_ERR_UNSUPPORTED);" not in create[:pipe_create]:
    raise AssertionError("resource allocation failure reports an error before rollback")

for failure in (
    "unsupported format",
    "failed to create resource",
    "failed to allocate resource transfers",
    "failed to create paired Zink Present allocation",
    "failed to map initial buffer data",
    "failed to map initial texture data",
):
    position = create.index(failure)
    oom = create.index("creation_error = E_OUTOFMEMORY;", position)
    rollback = create.index("goto create_failure;", oom)
    if not position < oom < rollback < failure_label:
        raise AssertionError(f"{failure} does not enter transactional rollback")

create11 = function_body(resource_text, "CreateResource11(D3D10DDI_HDEVICE hDevice", resource)
delegate = create11.index("CreateResource(hDevice, &create10, hResource, hRTResource);")
failure_check = create11.index("if (!resource || !resource->resource)", delegate)
failure_return = create11.index("return;", failure_check)
misc_flags = create11.index("resource->MiscFlags =", failure_return)
byte_stride = create11.index("resource->ByteStride =", misc_flags)
if not delegate < failure_check < failure_return < misc_flags < byte_stride:
    raise AssertionError("D3D11 resource wrapper mutates metadata after failure")

require(workflow_text, "check_resource_creation_failures.py", workflow)

print("D3D resource creation failure contract: PASS")
