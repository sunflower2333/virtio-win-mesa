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
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

query_text = query.read_text(encoding="utf-8")
resource_text = resource.read_text(encoding="utf-8")
shader_text = shader.read_text(encoding="utf-8")
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

require(workflow_text, "check_predication_contract.py", workflow)

print("D3D query predication contract: PASS")
