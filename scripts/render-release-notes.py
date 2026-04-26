from __future__ import annotations

import argparse
from pathlib import Path


def extract_section(changelog: str, heading: str) -> str:
    lines = changelog.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        raise SystemExit(f"Could not find changelog section: {heading}")

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    return "\n".join(lines[start:end]).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render GitHub release notes from CHANGELOG.md")
    parser.add_argument("version", help="Release version, for example v0.1.0")
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--output", default="release-notes.md")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    changelog = Path(args.changelog).read_text(encoding="utf-8")
    version_heading = f"## [{args.version.lstrip('v')}]"
    dated_version_prefix = f"## [{args.version.lstrip('v')}] - "

    body = ""
    lines = changelog.splitlines()
    try:
        body = extract_section(changelog, version_heading)
    except SystemExit:
        for line in lines:
            if line.startswith(dated_version_prefix):
                body = extract_section(changelog, line.strip())
                break
        if not body:
            raise SystemExit(
                f"CHANGELOG.md must contain a versioned section for {args.version}, "
                f"for example: ## [{args.version.lstrip('v')}] - YYYY-MM-DD. "
                "Do not release directly from [Unreleased]; move entries into the release section first."
            )

    if not body.strip():
        raise SystemExit(f"Changelog section for {args.version} is empty.")

    output = f"""Container image:

```text
{args.image}
```

{body}
"""
    Path(args.output).write_text(output.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
