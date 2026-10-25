"""The Hunch Agent's card, skills, prompt and workflow declaration agree with each other."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from hunch.agent_tools import PROJECT_AGENT_TOOLS
from hunch.api.app.mcp_server import MCP_SERVER_NAME, MCP_SKILLS_DIRECTORY
from hunch.api.app.site_agent import CARD_PATH, agent_card_name

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".mainsequence/workflows/hunch-api.yaml"
SYSTEM_PROMPT = ROOT / ".tau/SYSTEM.md"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _resource(kind: str, key: str | None = None) -> dict:
    matches = [
        item
        for item in _workflow()["resources"]
        if item["kind"] == kind and (key is None or item["key"] == key)
    ]
    assert len(matches) == 1, (kind, key)
    return matches[0]


def test_agent_card_names_the_agent_and_lists_existing_skills() -> None:
    assert CARD_PATH == ROOT / ".agents/agent_card.json"
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    assert agent_card_name() == "Hunch Agent"
    assert card["description"].strip()
    assert card["version"] == "0.2.0"
    kinds = card["capabilities"]["extensions"][0]["params"]["supportedResponseKinds"]
    assert kinds == ["message"]
    skill_paths = {skill["path"] for skill in card["skills"]}
    published = {
        str(path.relative_to(ROOT)) for path in (ROOT / MCP_SKILLS_DIRECTORY).glob("*/SKILL.md")
    }
    assert skill_paths == published and skill_paths


def test_published_skills_have_matching_frontmatter_names() -> None:
    for path in (ROOT / MCP_SKILLS_DIRECTORY).glob("*/SKILL.md"):
        frontmatter = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
        assert frontmatter is not None, path
        meta = yaml.safe_load(frontmatter.group(1))
        assert meta["name"] == path.parent.name
        assert meta["description"].strip()


def test_system_prompt_routes_every_operation_through_the_hunch_application() -> None:
    prompt = SYSTEM_PROMPT.read_text(encoding="utf-8")
    assert f"{MCP_SERVER_NAME}__list_tools" in prompt
    assert f"{MCP_SERVER_NAME}__call_tool" in prompt
    assert f"{MCP_SERVER_NAME}__read_resource" in prompt
    assert "never talk to a brokerage" in prompt
    assert "not a registered investment adviser" in prompt
    for definition in PROJECT_AGENT_TOOLS:
        if definition.name == "hunch_project_state":
            assert definition.name in prompt


def test_workflow_declares_the_api_the_one_agent_and_the_migration() -> None:
    workflow = _workflow()
    assert workflow["api_version"] == "3.0.0"
    api = _resource("fastapi")
    assert api["key"] == MCP_SERVER_NAME
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,39}", api["key"])
    assert api["spec"]["mcp_enabled"] is True
    assert (ROOT / api["spec"]["source_path"]).is_file()

    agent = _resource("harness_agent")
    assert agent["acts_for_requester"] is True
    assert agent["spec"]["mcp_applications"] == [{"resource": api["key"]}]
    assert (ROOT / agent["spec"]["source_path"]).is_file()
    env = {item["name"]: item["value"] for item in agent["spec"]["env_vars"]}
    assert env == {"TAU_EXCLUDE_BASE_TOOLS": "true", "TAU_EXCLUDE_MAINSEQUENCE_MCP": "true"}
    assert {"key": agent["key"], "policy": "user"} in api["access"]["resources"]
    assert {"key": api["key"], "policy": "user"} in agent["access"]["resources"]

    jobs = [item for item in workflow["resources"] if item["kind"] == "job"]
    assert {job["key"] for job in jobs} == {
        "hunch-migrate",
        "hunch-take-build",
        "hunch-portfolio-refresh",
        "hunch-portfolio-refresh-dispatcher",
        "hunch-daily-review",
        "hunch-daily-review-dispatcher",
        "hunch-execution-sync",
        "hunch-leaderboard",
        "hunch-email-digest",
    }
    for job in jobs:
        assert (ROOT / job["spec"]["execution_path"]).is_file(), job["key"]
    migrate = _resource("job", "hunch-migrate")
    assert {"key": "hunch-take-build", "policy": "runner"} in api["access"]["resources"]
    dispatcher = _resource("job", "hunch-portfolio-refresh-dispatcher")
    assert dispatcher["spec"]["scheduled_command_args"] == ["--scheduled"]
    assert {"key": "hunch-portfolio-refresh", "policy": "runner"} in dispatcher["access"][
        "resources"
    ]
    steps = workflow["execution"]["steps"]
    assert steps["migrate"]["run_job"] == migrate["key"]
    assert steps["deploy_api"]["needs"] == ["migrate"]
    assert "deploy_api" in steps["deploy_agent"]["needs"]
