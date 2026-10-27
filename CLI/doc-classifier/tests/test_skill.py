"""SKILL.md 테스트: OpenCode 형식(frontmatter), 버전 일치, 언급한 JSON 키와 명령이 실제로 있는지."""
import os
import re

import _dc_runtime as rt
import doc_classifier

SKILL = os.path.join(rt.TOOL_DIR, "SKILL.md")


def _text():
    with open(SKILL, encoding="utf-8") as f:
        return f.read()


def test_frontmatter_is_opencode_format_and_version_matches():
    fm = _text().split("---")[1]
    assert re.findall(r"^(\w+):", fm, re.M) == ["name", "description", "license", "compatibility", "metadata"]
    assert re.search(r"^name: doc-classifier$", fm, re.M)
    assert f'version: "{rt.VERSION}"' in fm


def test_skill_mentions_only_existing_commands_and_options():
    text = _text()
    parser = doc_classifier.build_cli()
    sub = next(a for a in parser._actions if a.dest == "command").choices
    for cmd in re.findall(r"<DC> (\w+)", text):
        assert cmd in sub, cmd
    options = {o for p in sub.values() for a in p._actions for o in a.option_strings}
    for opt in re.findall(r"(--[a-z][a-z-]+)", text):
        assert opt in options, opt


def test_skill_is_short_for_small_models():
    assert len(_text().splitlines()) <= 90
