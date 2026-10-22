"""Generate clickable cards for every public merged PR, without dependencies."""

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
import urllib.error
import urllib.request

START = "<!-- MERGED-PRS:START -->"
END = "<!-- MERGED-PRS:END -->"
QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    pullRequests(first: 100, after: $cursor, states: MERGED,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title url mergedAt repository { nameWithOwner isPrivate } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def graphql(variables):
    payload = json.dumps({"query": QUERY, "variables": variables}).encode()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request = urllib.request.Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "profile-merged-pr-cards",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"GitHub API returned HTTP {error.code}") from None
    else:
        response = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"], input=payload,
            capture_output=True, check=False,
        )
        if response.returncode:
            raise RuntimeError("GitHub query failed; authenticate gh or set GITHUB_TOKEN")
        result = json.loads(response.stdout)
    if result.get("errors"):
        raise RuntimeError("GraphQL returned errors; keeping existing contributions")
    return result


def fetch_prs(login, request=graphql):
    """Walk all pages, excluding private repositories before data is persisted."""
    cursor = None
    cursors = set()
    contributions = {}
    while True:
        result = request({"login": login, "cursor": cursor})
        if result.get("errors"):
            raise RuntimeError("GraphQL returned errors; refusing a partial update")
        connection = result["data"]["user"]["pullRequests"]
        for node in connection["nodes"]:
            repo = node["repository"]
            if repo["isPrivate"] is not False:
                continue
            name = repo["nameWithOwner"]
            number = node["number"]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
                raise ValueError("Invalid repository name")
            if type(number) is not int or number < 1 or not node["mergedAt"]:
                raise ValueError("Expected a merged pull request")
            url = f"https://github.com/{name}/pull/{number}"
            if node["url"] != url:
                raise ValueError("Unexpected pull request URL")
            contributions[url] = {
                "repository": name, "number": number, "url": url,
                "title": " ".join(node["title"].split()),
                "merged_at": node["mergedAt"],
            }
        page = connection["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
        if not cursor or cursor in cursors:
            raise RuntimeError("Invalid pagination cursor; refusing a partial update")
        cursors.add(cursor)
    return sorted(contributions.values(), key=lambda pr: (pr["merged_at"], pr["url"]), reverse=True)


def wrap_title(title, limit=57):
    lines = []
    line = ""
    width = 0
    for char in title:
        size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if width + size > limit:
            lines.append(line.rstrip())
            line, width = "", 0
        line += char
        width += size
    if line:
        lines.append(line.rstrip())
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip()[:-1] + "…"
    return lines or ["Untitled pull request"]


def render_card(pr):
    escape = html.escape
    title_lines = wrap_title(pr["title"])
    height = 142 + 26 * len(title_lines)
    title = "".join(
        f'<text class="title" x="28" y="{94 + 26 * index}">{escape(line)}</text>'
        for index, line in enumerate(title_lines)
    )
    label = f'{pr["repository"]} #{pr["number"]}: {pr["title"]}'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{height}" viewBox="0 0 720 {height}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(label)}</title>
  <desc id="desc">Merged on {escape(pr["merged_at"][:10])}. Open the pull request for the diff and review.</desc>
  <style>
    .bg {{ fill: #ffffff; stroke: #d9e0e8; }}
    text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
    .repo {{ fill: #536173; font-size: 16px; }}
    .title {{ fill: #18243a; font-size: 19px; font-weight: 600; }}
    .muted {{ fill: #627084; font-size: 13px; }}
    .pill {{ fill: #f1eafa; }} .status {{ fill: #8250df; font-size: 12px; font-weight: 600; }}
    @media (prefers-color-scheme: dark) {{
      .bg {{ fill: #0d1117; stroke: #30363d; }} .repo, .muted {{ fill: #9ba8b7; }}
      .title {{ fill: #e6edf3; }} .pill {{ fill: #282038; }} .status {{ fill: #c5a4ff; }}
    }}
  </style>
  <rect class="bg" x="0.5" y="0.5" width="719" height="{height - 1}" rx="14"/>
  <rect class="pill" x="594" y="22" width="98" height="28" rx="14"/>
  <text class="status" x="643" y="41" text-anchor="middle">MERGED</text>
  <text class="repo" x="28" y="41">{escape(pr["repository"])}</text>
  {title}
  <text class="muted" x="28" y="{height - 25}">#{pr["number"]} · Merged {escape(pr["merged_at"][:10])}</text>
  <text class="muted" x="692" y="{height - 25}" text-anchor="end">View pull request →</text>
</svg>
'''


def generate(root, login, prs):
    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    if readme.count(START) != 1 or readme.count(END) != 1 or readme.index(START) > readme.index(END):
        raise ValueError("README must contain one correctly ordered pair of MERGED-PRS markers")
    images = {}
    repo_count = len({pr["repository"] for pr in prs})
    search = f"https://github.com/pulls?q=is%3Apr+is%3Amerged+author%3A{login}"
    lines = [f"**{len(prs)} merged PR{'s' if len(prs) != 1 else ''} · {repo_count} repositor{'y' if repo_count == 1 else 'ies'}** · [查看全部]({search})", ""]
    for pr in prs:
        content = render_card(pr)
        name = "pr-" + hashlib.sha256(pr["url"].encode()).hexdigest()[:16] + ".svg"
        images[name] = content
        digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        image_url = f"https://raw.githubusercontent.com/{login}/{login}/main/assets/merged-prs/{name}?v={digest}"
        alt = f'{pr["repository"]} #{pr["number"]}: {pr["title"]}'
        alt = alt.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        lines.extend([f'[![{alt}]({image_url})]({pr["url"]})', ""])
    if not prs:
        lines.append("公开 PR 合并后将在这里自动显示。")
    block = START + "\n\n" + "\n".join(lines).rstrip() + "\n\n" + END
    updated = readme[:readme.index(START)] + block + readme[readme.index(END) + len(END):]
    # All API pages, metadata and SVGs are validated/rendered before any file is changed.
    image_dir = root / "assets" / "merged-prs"
    image_dir.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    for name, content in images.items():
        (image_dir / name).write_text(content, encoding="utf-8", newline="\n")
    (data_dir / "merged-prs.json").write_text(
        json.dumps({"login": login, "pull_requests": prs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    readme_path.write_text(updated, encoding="utf-8", newline="\n")
    for stale in image_dir.glob("pr-*.svg"):
        if stale.name not in images:
            stale.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", default=os.environ.get("PROFILE_LOGIN", "Cordis798"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", args.login):
        parser.error("Invalid GitHub username")
    root = Path(__file__).resolve().parents[1]
    prs = fetch_prs(args.login)
    generate(root, args.login, prs)
    print(f"Rendered {len(prs)} public merged pull request(s) for {args.login}")


if __name__ == "__main__":
    main()
