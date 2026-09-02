#!/usr/bin/env python3

import re
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


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", text)


resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

resource_text = resource.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

invalidate = canonical(
    function_body(resource_text, "InvalidateBufferShadow(Resource *resource)", resource)
)
for fragment in (
    "free(resource->buffer_shadow);",
    "resource->buffer_shadow = NULL;",
    "resource->buffer_shadow_size = 0;",
    "resource->constant_shadow_valid = false;",
):
    require(invalidate, fragment, resource)

update = canonical(
    function_body(resource_text, "UpdateBufferShadow(Resource *resource", resource)
)
overflow = update.index("if (offset > UINT_MAX - size)")
overflow_invalidate = update.index("InvalidateBufferShadow(resource);", overflow)
overflow_return = update.index("return false;", overflow_invalidate)
allocation = update.index("realloc(resource->buffer_shadow, required_size)")
allocation_failure = update.index("if (!shadow)", allocation)
allocation_invalidate = update.index(
    "InvalidateBufferShadow(resource);", allocation_failure
)
allocation_return = update.index("return false;", allocation_invalidate)
copy = update.index("memcpy(", allocation_return)
success = update.index("return true;", copy)
if not (
    overflow
    < overflow_invalidate
    < overflow_return
    < allocation
    < allocation_failure
    < allocation_invalidate
    < allocation_return
    < copy
    < success
):
    raise AssertionError("buffer shadow update failure handling is misordered")

ensure = canonical(
    function_body(resource_text, "EnsureBufferShadow(Resource *resource", resource)
)
ensure_allocation = ensure.index("realloc(resource->buffer_shadow, size)")
ensure_failure = ensure.index("if (!shadow)", ensure_allocation)
ensure_invalidate = ensure.index("InvalidateBufferShadow(resource);", ensure_failure)
ensure_return = ensure.index("return false;", ensure_invalidate)
if not ensure_allocation < ensure_failure < ensure_invalidate < ensure_return:
    raise AssertionError("full buffer shadow allocation failure is not invalidated")

create = canonical(
    function_body(resource_text, "CreateResource(D3D10DDI_HDEVICE hDevice", resource)
)
initial_update = create.index("const bool shadow_updated = UpdateBufferShadow(")
initial_valid = create.index(
    "pResource->constant_shadow_valid = shadow_updated &&", initial_update
)
if not initial_update < initial_valid:
    raise AssertionError("initial buffer shadow validity ignores mirror failure")

update_subresource = canonical(
    function_body(
        resource_text,
        "ResourceUpdateSubResourceUP(D3D10DDI_HDEVICE hDevice",
        resource,
    )
)
real_write = update_subresource.index("pipe->buffer_subdata(pipe,")
mirror_update = update_subresource.index(
    "const bool shadow_updated = UpdateBufferShadow(", real_write
)
candidate = update_subresource.index(
    "ConstantBufferPublicationCandidate(pDevice, pDstResource)", mirror_update
)
mirror_gate = update_subresource.index("shadow_updated &&", candidate)
full_shadow = update_subresource.index("EnsureBufferShadow(", mirror_gate)
valid = update_subresource.index(
    "pDstResource->constant_shadow_valid =", full_shadow
)
branch_return = update_subresource.index("return;", valid)
if not real_write < mirror_update < candidate < mirror_gate < full_shadow < valid < branch_return:
    raise AssertionError("buffer subdata shadow validity is not failure-gated")
if "SetError(" in update_subresource[real_write:branch_return]:
    raise AssertionError("optional shadow failure incorrectly fails the real buffer write")

mapped_update = update_subresource.index("UpdateBufferShadow(", branch_return)
if mapped_update <= branch_return:
    raise AssertionError("mapped buffer write no longer mirrors through invalidating helper")

require(workflow_text, "check_buffer_shadow_failure.py", workflow)

print("D3D buffer shadow failure contract: PASS")
