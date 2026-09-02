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


shader = ROOT / "src/gallium/frontends/d3d10umd/Shader.cpp"
workflow = ROOT / ".github/workflows/windows-zink-d3d10umd-arm64.yml"

shader_text = shader.read_text(encoding="utf-8")
workflow_text = workflow.read_text(encoding="utf-8")
body = canonical(function_body(shader_text, "SoSetTargets(", shader))

for fragment in (
    "struct pipe_stream_output_target *candidate_targets[PIPE_MAX_SO_BUFFERS] = {};",
    "Resource *candidate_resources[PIPE_MAX_SO_BUFFERS] = {};",
    "if (!pipe->set_stream_output_targets)",
    "candidate_resources[i] = resource;",
    "candidate_resources[j] == resource",
    "candidate_targets[i] = so_target;",
    "pipe_so_target_reference(&candidate_targets[i], so_target);",
    "if (allocation_failed)",
    "pipe_so_target_reference(&candidate_targets[i], NULL);",
    "SetError(hDevice, E_OUTOFMEMORY);",
    "resource->so_target != candidate_targets[i]",
    "pipe_so_target_reference(&resource->so_target, candidate_targets[i]);",
    "pipe_so_target_reference(&pDevice->so_targets[i], candidate_targets[i]);",
    "pipe->set_stream_output_targets(pipe, SOTargets, pDevice->so_targets,",
):
    require(body, fragment, shader)

if "pipe_so_target_reference(&resource->so_target, NULL);" in body:
    raise AssertionError("SoSetTargets still releases cached state before allocation")

create = body.index("pipe->create_stream_output_target")
failure = body.index("if (!so_target)", create)
rollback = body.index("if (allocation_failed)", failure)
error = body.index("SetError(hDevice, E_OUTOFMEMORY);", rollback)
commit = body.index("resource->so_target != candidate_targets[i]", error)
bind = body.index("pipe->set_stream_output_targets", commit)
if not create < failure < rollback < error < commit < bind:
    raise AssertionError("stream-output target creation is not transactional")

cleanup = "pipe_so_target_reference(&candidate_targets[i], NULL);"
if body.count(cleanup) != 2:
    raise AssertionError("candidate targets need failure and success cleanup")

require(workflow_text, "check_stream_output_target_failure.py", workflow)

print("D3D stream-output target failure contract: PASS")
