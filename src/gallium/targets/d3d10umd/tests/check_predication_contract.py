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


query = ROOT / "src/gallium/frontends/d3d10umd/Query.cpp"
resource = ROOT / "src/gallium/frontends/d3d10umd/Resource.cpp"
shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
output_merger = ROOT / "src/gallium/frontends/d3d10umd/OutputMerger.cpp"
zink_draw = ROOT / "src/gallium/drivers/zink/zink_draw.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

query_text = query.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
output_merger_text = output_merger.read_text(encoding="utf-8")
zink_draw_text = zink_draw.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

set_predication = function_body(
    query_text,
    "SetPredication(D3D10DDI_HDEVICE hDevice",
    query,
)
for fragment in (
    "D3D10DDI_QUERY_MISCFLAG_PREDICATEHINT",
    "PIPE_RENDER_COND_NO_WAIT : PIPE_RENDER_COND_WAIT",
    "pipe->render_condition(pipe, state, PredicateValue, wait)",
    "pDevice->pPredicate = pQuery",
    "pDevice->PredicateValue = PredicateValue",
):
    require(set_predication, fragment, query)

check_predicate = function_body(query_text, "CheckPredicate(Device *pDevice)", query)
is_predicate_query = function_body(
    query_text,
    "IsPredicateQuery(D3D10DDI_QUERY query)",
    query,
)
expected_predicate_types = {
    "D3D10DDI_QUERY_OCCLUSIONPREDICATE",
    "D3D10DDI_QUERY_STREAMOVERFLOWPREDICATE",
    "D3D11DDI_QUERY_STREAMOVERFLOWPREDICATE_STREAM0",
    "D3D11DDI_QUERY_STREAMOVERFLOWPREDICATE_STREAM1",
    "D3D11DDI_QUERY_STREAMOVERFLOWPREDICATE_STREAM2",
    "D3D11DDI_QUERY_STREAMOVERFLOWPREDICATE_STREAM3",
}
actual_predicate_types = set(
    re.findall(r"case (D3D(?:10|11)DDI_QUERY_[A-Z0-9_]+):", is_predicate_query)
)
if actual_predicate_types != expected_predicate_types:
    raise AssertionError(
        "predicate query classification mismatch: "
        f"expected {sorted(expected_predicate_types)!r}, "
        f"found {sorted(actual_predicate_types)!r}"
    )
for fragment in ("return true;", "default:\n      return false;"):
    require(is_predicate_query, fragment, query)

wait_fragment = (
    "const bool wait =\n"
    "      !(pQuery->Flags & D3D10DDI_QUERY_MISCFLAG_PREDICATEHINT);"
)
result_fragment = "pipe->get_query_result(pipe, query, wait, &result)"
for fragment in (
    "assert(IsPredicateQuery(pQuery->Type));",
    wait_fragment,
    result_fragment,
    "if (!ret) {\n      return true;",
    "if (!!result.b == !!pDevice->PredicateValue) {\n      return false;",
):
    require(check_predicate, fragment, query)

if "get_query_result(pipe, query, false" in check_predicate:
    raise AssertionError("guaranteed resource predication still uses NO_WAIT")
if check_predicate.index(wait_fragment) > check_predicate.index(result_fragment):
    raise AssertionError("resource predication computes WAIT mode too late")

for text, source, signature in (
    (resource_text, resource, "ResourceCopy(D3D10DDI_HDEVICE hDevice"),
    (resource_text, resource, "ResourceCopyRegion(D3D10DDI_HDEVICE hDevice"),
    (resource_text, resource, "ResourceUpdateSubResourceUP(D3D10DDI_HDEVICE hDevice"),
    (shader_text, shader, "GenMips(D3D10DDI_HDEVICE hDevice"),
):
    body = function_body(text, signature, source)
    require(body, "if (!CheckPredicate(pDevice))", source)

emulation_predicate_guard = (
    "if (!CheckPredicate(pDevice)) {\n"
    "      return true;\n"
    "   }"
)
for signature in (
    "RunComputeEmulation(Device *pDevice,",
    "RunPixelShaderEmulation(Device *pDevice)",
):
    body = function_body(shader_text, signature, shader)
    emulation_type = body.find("COMPUTE_EMULATION_NONE")
    predicate_guard = body.find(emulation_predicate_guard)
    fallback_warning = body.find("WarnSoftwareEmulationFallback(")
    if min(emulation_type, predicate_guard, fallback_warning) < 0:
        raise AssertionError(f"incomplete predicated emulation path in {signature!r}")
    if not emulation_type < predicate_guard < fallback_warning:
        raise AssertionError(f"invalid predicated emulation ordering in {signature!r}")

for signature in (
    "ClearUnorderedAccessViewUint(\n",
    "ClearUnorderedAccessViewFloat(\n",
):
    body = function_body(shader_text, signature, shader)
    device = body.find("Device *pDevice = CastDevice(hDevice);")
    validation = body.find("if (!pDevice || !pDevice->pipe || !uav ||")
    predicate_guard = body.find("if (!CheckPredicate(pDevice))")
    pipe = body.find("struct pipe_context *pipe = pDevice->pipe;")
    clear = body.find("uav->pipe_resource->target == PIPE_BUFFER")
    if min(device, validation, predicate_guard, pipe, clear) < 0:
        raise AssertionError(f"incomplete predicated UAV clear in {signature!r}")
    if not device < validation < predicate_guard < pipe < clear:
        raise AssertionError(f"invalid predicated UAV clear ordering in {signature!r}")

clear_view = function_body(
    output_merger_text,
    "ClearView(D3D10DDI_HDEVICE hDevice,",
    output_merger,
)
if "CheckPredicate(pDevice)" in clear_view:
    raise AssertionError("ClearView blocks backend GPU predication")
device = clear_view.find("Device *pDevice = CastDevice(hDevice);")
predicate_gate = clear_view.find("if (!pDevice->pPredicate &&")
upload = clear_view.find("ClearRenderTargetViewRectUpload(", predicate_gate)
skip = clear_view.find("continue;", upload)
conditioned_clear = clear_view.find("pipe->clear_render_target", skip)
if min(device, predicate_gate, upload, skip, conditioned_clear) < 0:
    raise AssertionError("ClearView predicated upload bypass is incomplete")
if not device < predicate_gate < upload < skip < conditioned_clear:
    raise AssertionError("ClearView predicated upload bypass ordering is invalid")
conditioned_clear_end = clear_view.find(");", conditioned_clear)
if "true" not in clear_view[conditioned_clear:conditioned_clear_end]:
    raise AssertionError("ClearView fallback clear disables backend predication")

resolve = function_body(
    resource_text,
    "ResourceResolveSubResource(D3D10DDI_HDEVICE hDevice,",
    resource,
)
if "CheckPredicate" in resolve:
    raise AssertionError("resource resolve blocks backend GPU predication")
valid_resolve = resolve.find("if (pipe->blit &&")
blit_info = resolve.find("struct pipe_blit_info info = {};", valid_resolve)
condition_enable = resolve.find("info.render_condition_enable = true;", blit_info)
blit_submit = resolve.find("pipe->blit(pipe, &info);", blit_info)
copy_fallback = resolve.find("pipe->resource_copy_region", blit_submit)
if min(valid_resolve, blit_info, condition_enable, blit_submit, copy_fallback) < 0:
    raise AssertionError("resource resolve predication is incomplete")
if not valid_resolve < blit_info < condition_enable < blit_submit < copy_fallback:
    raise AssertionError("resource resolve predication ordering is invalid")

dispatch = function_body(shader_text, "Dispatch(D3D10DDI_HDEVICE hDevice,", shader)
dispatch_indirect = function_body(
    shader_text,
    "DispatchIndirect(D3D10DDI_HDEVICE hDevice,",
    shader,
)
for body, source_name in (
    (dispatch, "Dispatch"),
    (dispatch_indirect, "DispatchIndirect"),
):
    if "CheckPredicate(pDevice)" in body:
        raise AssertionError(f"{source_name} blocks native backend predication")
require(dispatch, "RunComputeEmulation(pDevice, cs", shader)
require(dispatch, "pipe->launch_grid(pipe, &info)", shader)
require(dispatch_indirect, "Dispatch(hDevice, dispatch_args.ThreadGroupCountX", shader)
require(dispatch_indirect, "pipe->launch_grid(pipe, &info)", shader)

zink_launch_grid = function_body(
    zink_draw_text,
    "zink_launch_grid(struct pipe_context *pctx",
    zink_draw,
)
conditional_start = zink_launch_grid.find("zink_start_conditional_render(ctx)")
indirect_submit = zink_launch_grid.find("CmdDispatchIndirect")
direct_submit = zink_launch_grid.find("CmdDispatch)", indirect_submit)
if min(conditional_start, indirect_submit, direct_submit) < 0:
    raise AssertionError("Zink native dispatch conditioning is incomplete")
if not conditional_start < indirect_submit < direct_submit:
    raise AssertionError("Zink native dispatch conditioning order is invalid")

require(workflow_text, "check_predication_contract.py", workflow)

print("D3D query predication contract: PASS")
