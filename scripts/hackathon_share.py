"""How much of the repository was written during the hackathon, as the README reports it.

Run from the repository root: `uv run scripts/hackathon_share.py`. A commit counts by its author
time. Each line of a tracked text file counts for the author time of the commit that last wrote it
(`git blame -w -M -C`), so whitespace-only edits and moved or copied lines keep their original
time. The lock file, the requirements exported from it, the instrument universe, the stored model
answer and binary files are left out.
"""

from __future__ import annotations

import collections
import subprocess

KICKOFF = 1793034000  # 2026-10-26T17:00:00Z, when the hackathon started
EXCLUDED = {
    "uv.lock",
    "requirements.txt",
    "src/hunch/instruments/universe.json",
    "docs/examples/muse-wonder-research.json",
}


def git(*args: str) -> str:
    return subprocess.run(("git", *args), check=True, capture_output=True, text=True).stdout


def area(path: str) -> str:
    if path.startswith("tests/"):
        return "tests"
    if path.startswith(("docs/", "films/")) or (path.endswith(".md") and "/" not in path):
        return "docs"
    return "code"


def share(counts: collections.Counter) -> str:
    total = counts["before"] + counts["during"]
    return f"{counts['during']:6} of {total:6} during ({counts['during'] / total:.0%})"


times = [int(value) for value in git("log", "--format=%at", "HEAD").split()]
commits = collections.Counter("during" if when >= KICKOFF else "before" for when in times)
lines = {name: collections.Counter() for name in ("code", "tests", "docs")}
for path in git("ls-files").splitlines():
    if path in EXCLUDED:
        continue
    with open(path, "rb") as handle:
        if b"\0" in handle.read(8000):
            continue
    for line in git("blame", "-w", "-M", "-C", "--line-porcelain", "--", path).splitlines():
        if line.startswith("author-time "):
            when = int(line.split()[1])
            lines[area(path)]["during" if when >= KICKOFF else "before"] += 1

print(f"commits        {share(commits)}")
for name, counts in lines.items():
    print(f"{name:5} lines    {share(counts)}")
print(f"all lines      {share(sum(lines.values(), collections.Counter()))}")
