"""Anchor fallback ownership guards for the settled activity scene.

The Stable Assistant Turn Anchor should own settled activity when a message has
`_anchor_activity_scene`. Raw `content[]` ordering and legacy settled tool-card
rebuilds are still required for historical/non-anchor transcripts, but they must
exit before competing with anchor-owned turns.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_JS = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
PHASE0_DOC = (
    ROOT / "docs" / "architecture" / "stable-assistant-turn-anchor-phase0.md"
).read_text(encoding="utf-8")


def _run_node_script(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _function_body(src: str, name: str) -> str:
    start = src.find(f"function {name}")
    assert start != -1, f"{name} not found"
    params = src.find("(", start)
    assert params != -1, f"{name} params not found"
    depth = 0
    close = -1
    for idx in range(params, len(src)):
        if src[idx] == "(":
            depth += 1
        elif src[idx] == ")":
            depth -= 1
            if depth == 0:
                close = idx
                break
    assert close != -1, f"{name} params did not close"
    brace = src.find("{", close)
    assert brace != -1, f"{name} body not found"
    depth = 0
    for idx in range(brace, len(src)):
        if src[idx] == "{":
            depth += 1
        elif src[idx] == "}":
            depth -= 1
            if depth == 0:
                return src[brace + 1 : idx]
    raise AssertionError(f"{name} body did not close")


def test_phase0_doc_records_settled_fallback_ownership_matrix():
    assert "### Settled Fallback Ownership Matrix" in PHASE0_DOC
    assert "_anchor_activity_scene` is the semantic" in PHASE0_DOC
    assert "| Settled Compact Worklog activity |" in PHASE0_DOC
    assert "| Settled Transparent Stream activity |" in PHASE0_DOC
    assert "| Historical / non-anchor transcripts |" in PHASE0_DOC
    assert "This matrix is an audit baseline, not permission to delete fallbacks." in PHASE0_DOC


def test_transparent_raw_content_helper_is_fallback_only_when_anchor_scene_absent():
    helper = _function_body(UI_JS, "_transparentStreamOrderedParts")

    transparent_gate = helper.index("!isTransparentStream()) return null;")
    role_gate = helper.index("!message||message.role!=='assistant'||message._live")
    anchor_exit = helper.index("if(message._anchor_activity_scene) return null;")
    content_loop = helper.index("for(const part of message.content)")
    fallback_return = helper.index("return hasText&&hasTool?ordered:null;")

    assert transparent_gate < role_gate < anchor_exit < content_loop < fallback_return
    assert "part.type==='text'" in helper
    assert "part.type==='tool_use'" in helper


def test_transparent_raw_content_fallback_exits_for_anchor_owned_messages():
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const uiPath = {json.dumps(str(ROOT / "static" / "ui.js"))};
        const src = fs.readFileSync(uiPath, 'utf8');

        function functionSource(source, name) {{
          const start = source.indexOf(`function ${{name}}`);
          if (start < 0) throw new Error(`${{name}} not found`);
          const params = source.indexOf('(', start);
          let depth = 0;
          let close = -1;
          for (let idx = params; idx < source.length; idx += 1) {{
            if (source[idx] === '(') depth += 1;
            else if (source[idx] === ')') {{
              depth -= 1;
              if (depth === 0) {{
                close = idx;
                break;
              }}
            }}
          }}
          const brace = source.indexOf('{{', close);
          depth = 0;
          for (let idx = brace; idx < source.length; idx += 1) {{
            if (source[idx] === '{{') depth += 1;
            else if (source[idx] === '}}') {{
              depth -= 1;
              if (depth === 0) return source.slice(start, idx + 1);
            }}
          }}
          throw new Error(`${{name}} body did not close`);
        }}

        let transparentStream = true;
        function isTransparentStream() {{
          return transparentStream;
        }}

        eval(functionSource(src, '_transparentStreamOrderedParts'));

        const anchorOwned = {{
          role: 'assistant',
          content: [
            {{ type: 'text', text: 'Checked the repo state.' }},
            {{ type: 'tool_use', id: 'toolu_anchor', name: 'terminal', input: {{ cmd: 'git status' }} }},
          ],
          _anchor_activity_scene: {{
            schema_version: 'activity_scene_v1',
            activity_rows: [],
          }},
        }};
        const historical = {{
          role: 'assistant',
          content: [
            {{ type: 'text', text: 'Checked the repo state.' }},
            {{ type: 'tool_use', id: 'toolu_history', name: 'terminal', input: {{ cmd: 'git status' }} }},
          ],
        }};

        const anchorResult = _transparentStreamOrderedParts(anchorOwned);
        const historicalResult = _transparentStreamOrderedParts(historical);
        transparentStream = false;
        const disabledResult = _transparentStreamOrderedParts(historical);

        console.log(JSON.stringify({{
          anchorResult,
          historicalResult,
          disabledResult,
        }}));
        """
    )

    result = json.loads(_run_node_script(script))

    assert result["anchorResult"] is None
    assert result["disabledResult"] is None
    assert [part["kind"] for part in result["historicalResult"]] == ["text", "tool"]
    assert result["historicalResult"][0]["text"] == "Checked the repo state."
    assert result["historicalResult"][1] == {
        "kind": "tool",
        "toolUseId": "toolu_history",
        "name": "terminal",
        "input": {"cmd": "git status"},
    }


def test_settled_legacy_tool_rebuild_excludes_anchor_owned_turns():
    render = _function_body(UI_JS, "renderMessages")

    set_decl = render.index("const anchorOwnedAssistantRawIdxs=new Set();")
    collect_segments = render.index("turn.querySelectorAll('.assistant-segment[data-msg-idx]')")
    metadata_scan = render.index("const hasMessageToolMetadata=")
    fallback_sources = render.index("const fallbackToolSources=[];")
    source_collect = render.index("fallbackToolSources.push({m,rawIdx});")

    assert set_decl < collect_segments < metadata_scan < fallback_sources < source_collect
    assert "!anchorOwnedAssistantRawIdxs.has(S.messages.indexOf(m))" in render
    assert "if(anchorOwnedAssistantRawIdxs.has(rawIdx)) return;" in render


def test_settled_legacy_activity_buckets_skip_anchor_owned_turns_before_rendering():
    render = _function_body(UI_JS, "renderMessages")

    tool_loop = render.index("for(const tc of (S.toolCalls||[])){")
    tool_skip = render.index("if(anchorOwnedAssistantRawIdxs.has(aIdx)) continue;", tool_loop)
    thinking_loop = render.index("for(const aIdx of assistantThinking.keys()){")
    thinking_skip = render.index("if(anchorOwnedAssistantRawIdxs.has(aIdx)) continue;", thinking_loop)
    worklog_loop = render.index("for(const [aIdx,seg] of assistantSegments){")
    worklog_skip = render.index("if(anchorOwnedAssistantRawIdxs.has(aIdx)) continue;", worklog_loop)
    anchor_render = render.index("_renderSettledAnchorSceneForMessage(msg, seg, rawIdx)")

    assert tool_loop < tool_skip < thinking_loop < thinking_skip < worklog_loop < worklog_skip
    assert worklog_skip < anchor_render


def test_anchor_settled_renderers_remain_the_primary_scene_path():
    settled = _function_body(UI_JS, "_renderSettledAnchorSceneForMessage")
    transparent = _function_body(UI_JS, "_renderSettledAnchorSceneTransparentForMessage")

    assert "if(!message||!message._anchor_activity_scene||!segment) return false;" in settled
    assert "return _renderSettledAnchorSceneTransparentForMessage(message,segment,rawIdx);" in settled
    assert "_anchorSceneRowsForRendering(scene,{settled:true})" in settled
    assert "group.setAttribute('data-anchor-settled-scene-owner','1');" in settled

    assert "if(!message||!message._anchor_activity_scene||!segment) return false;" in transparent
    assert "_anchorSceneRowsForRendering(scene,{settled:true})" in transparent
    assert "_anchorSceneTransparentNodeForRow(row,{settled:true,finalAnswer})" in transparent
