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


query = ROOT / "src/gallium/frontends/d3d10umd/Query.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

query_text = query.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")

create = function_body(query_text, "CreateQuery(D3D10DDI_HDEVICE hDevice", query)
for fragment in (
    "if (pQuery->Emulated)\n      return;",
    "if (pQuery->pipe_type >= PIPE_QUERY_TYPES)",
    "SetError(hDevice, E_INVALIDARG);",
    "pQuery->handle = pipe->create_query",
    "if (!pQuery->handle)\n      SetError(hDevice, E_OUTOFMEMORY);",
):
    require(create, fragment, query)

if create.index("if (pQuery->pipe_type >= PIPE_QUERY_TYPES)") > create.index(
    "pipe->create_query"
):
    raise AssertionError("CreateQuery validates the translated type too late")
if create.index("pipe->create_query") > create.index(
    "SetError(hDevice, E_OUTOFMEMORY);"
):
    raise AssertionError("CreateQuery reports allocation failure before allocation")

get_data = function_body(
    query_text,
    "QueryGetData(D3D10DDI_HDEVICE hDevice",
    query,
)
missing_state = """else {
      LOG_UNSUPPORTED(true);
      SetError(hDevice, E_FAIL);
      return;
   }"""
require(get_data, missing_state, query)
if "LOG_UNSUPPORTED(true);\n      ret = true;" in get_data:
    raise AssertionError("QueryGetData still reports missing query state as complete")

require(workflow_text, "check_query_failure_propagation.py", workflow)

print("D3D query failure propagation contract: PASS")
