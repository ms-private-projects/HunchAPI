"""Check the stored Muse Wonder research in `docs/examples` against the code, with no credentials.

Run from the repository root: `uv run scripts/check_example_research.py`. It reads
`muse-wonder-research.json` (the research as Hunch stored it) and
`muse-wonder-recorded-request.json` (the platform's record of the request that produced it) and
checks, with Hunch's own code rather than copies of it, that:

- the answer matches the research response schema (`hunch.research.inference.response_schema`)
  for the packaged instrument universe, and the recorded request sent exactly that schema;
- every candidate and every evidence item names an instrument of that universe, by ticker and FIGI,
  and no leveraged or inverse product appears when the take allows none;
- every evidence id cited, in `citations`, in a case or in the rationale, is in the stored evidence;
- the recorded system prompt is `SYSTEM_PROMPT`, the recorded user prompt is the one the code
  builds from the take, the universe and the stored evidence, and the recorded answer is the
  stored one.

It prints one line per check and exits 1 when any fails.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from hunch.instruments.services import universe_fixture
from hunch.research.inference import SYSTEM_PROMPT, _user_prompt, response_schema
from hunch.research.sources import Evidence
from hunch.takes.services import TakeConstraints

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"
CITED = re.compile(r"\[(E\d+)\]")
PROMPT = re.compile(
    r"Title: (?P<title>.*?)\n\nThesis:\n(?P<thesis>.*?)\n\n# Constraints\n(?P<constraints>\{.*?\n\})",
    re.S,
)
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def schema_errors(schema: dict, instance: dict) -> list[str]:
    """Each violation as its JSON path and the first words of the validator's message."""
    return [
        f"{'/'.join(map(str, error.absolute_path))}: {error.message[:80]}"
        for error in Draft202012Validator(schema).iter_errors(instance)
    ]


def sorted_enum(schema: dict) -> dict:
    """The schema with its ticker enum sorted, so two universes compare as sets."""
    schema = copy.deepcopy(schema)
    ticker = schema["properties"]["candidates"]["items"]["properties"]["ticker"]
    ticker["enum"] = sorted(ticker["enum"])
    return schema


stored = json.loads((EXAMPLES / "muse-wonder-research.json").read_text(encoding="utf-8"))
record = json.loads((EXAMPLES / "muse-wonder-recorded-request.json").read_text(encoding="utf-8"))
record = record["record"]
# Hunch's universe in the order the code reads it (`list_instruments` sorts by ticker).
universe = sorted(universe_fixture(), key=lambda row: row["ticker"])
by_ticker = {row["ticker"]: row for row in universe}
schema = response_schema([row["ticker"] for row in universe])
evidence = {item["id"]: item for item in stored["evidence"]}
candidates = stored["candidates"]
# The code adds `horizon_months` to the brief after the model answers; the model never sends it.
answer = {
    "brief": {key: value for key, value in stored["brief"].items() if key != "horizon_months"},
    "candidates": candidates,
    "rationale_md": stored["rationale_md"],
}

print(f"Research {stored['uid']} by {stored['provider']} / {stored['model']}\n")
errors = schema_errors(schema, answer)
check(not errors, f"the answer matches the research schema ({'; '.join(errors) or 'no errors'})")
check(
    len(evidence) == len(stored["evidence"]),
    f"{len(evidence)} evidence items, each id used once",
)
check(
    all(
        by_ticker.get(item["ticker"], {}).get("figi") == item["figi"] for item in evidence.values()
    ),
    "every evidence item names a universe instrument by ticker and FIGI",
)
check(
    all(item["ticker"] in by_ticker for item in candidates)
    and len({item["ticker"] for item in candidates}) == len(candidates),
    f"{len(candidates)} candidates, each a distinct universe ticker",
)
citations = [cited for item in candidates for cited in item["citations"]]
in_text = CITED.findall(stored["rationale_md"]) + [
    cited for item in candidates for cited in CITED.findall(item["case"])
]
check(
    all(cited in evidence for cited in citations),
    f"all {len(citations)} cited evidence ids are in the stored evidence",
)
check(
    all(cited in evidence for cited in in_text),
    f"all {len(in_text)} [E..] references in the cases and the rationale are in the stored evidence",
)

print(f"\nRecorded request {record['request_uid']}\n")
check(
    record["request_uid"] in stored["inference_request_uids"]
    and record["conversation_uid"] == stored["conversation_uid"],
    "the stored research names this request and its conversation",
)
check(
    (record["status"], record["provider"], record["model"])
    == ("completed", stored["provider"], stored["model"]),
    f"it completed on {record['provider']} / {record['model']}, "
    f"thinking {record['input']['thinking_level']}",
)
metadata = record["input"]["metadata"]
check(
    (
        metadata["operation"],
        metadata["model_role"],
        metadata["take_uid"],
        metadata["research_number"],
    )
    == ("hunch-take-research", "research", stored["take_uid"], stored["number"]),
    f"its metadata names the research role, the take and research {stored['number']}, "
    f"attempt {metadata['attempt']}",
)
system, user = (message["content"] for message in record["input"]["messages"])
check(system == SYSTEM_PROMPT, "its system prompt is SYSTEM_PROMPT in the code today")
check(
    sorted_enum(record["input"]["response_schema"]) == sorted_enum(schema),
    "its response schema is the one the code builds for the packaged universe",
)
prompt = PROMPT.search(user)
constraints = TakeConstraints.model_validate(json.loads(prompt["constraints"]))
instruments = [
    SimpleNamespace(
        ticker=row["ticker"],
        name=row["name"],
        sector=row.get("sector"),
        themes=row.get("themes") or [],
        is_etf=bool(row.get("is_etf")),
        is_leveraged=bool(row.get("is_leveraged")),
        is_inverse=bool(row.get("is_inverse")),
        is_tradable=True,
    )
    for row in universe
]
rebuilt = _user_prompt(
    SimpleNamespace(title=prompt["title"], thesis_text=prompt["thesis"]),
    constraints,
    instruments,
    [Evidence.model_validate(item) for item in stored["evidence"]],
)
check(
    rebuilt == user,
    "its user prompt is the one the code builds from the take, the universe and the stored evidence",
)
check(
    constraints.allow_leveraged_etf
    or not any(
        flags.get("is_leveraged") or flags.get("is_inverse")
        for flags in (by_ticker.get(item["ticker"], {}) for item in candidates)
    ),
    "no leveraged or inverse candidate, as the take's constraints require",
)
check(record["output"]["content"] == answer, "the recorded answer is the stored answer")
errors = schema_errors(record["input"]["response_schema"], record["output"]["content"])
check(
    not errors,
    f"the recorded answer matches the recorded schema ({'; '.join(errors) or 'no errors'})",
)

seconds = (
    datetime.fromisoformat(record["completed_at"]) - datetime.fromisoformat(record["created_at"])
).total_seconds()
usage = record["usage"]
print(
    f"\nRecorded {record['created_at']} to {record['completed_at']} ({seconds:.1f} s), "
    f"{usage['input_tokens']:,} input and {usage['output_tokens']:,} output tokens; "
    f"{len(stored['brief']['claims'])} claims, {len(candidates)} candidates."
)
print(f"\n{len(failures)} failed." if failures else "\nAll checks passed.")
sys.exit(1 if failures else 0)
