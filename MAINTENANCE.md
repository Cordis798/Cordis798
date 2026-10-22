# Merged PR cards

`README.md` is the public profile. Its `MERGED-PRS` block, `assets/merged-prs/pr-*.svg`
and `data/merged-prs.json` are generated from GitHub's public merged PR metadata.
Content outside the markers can be edited freely.

The updater follows every page of `user.pullRequests(states: MERGED)` and excludes
private repositories before writing files. It displays all public merged PRs,
sorted by merge date, without a recent-PR limit. Every card links to its PR.
Titles are escaped for SVG and Markdown; a long title is shortened visually but
remains available in the card's accessible title and source PR.

GitHub Actions runs every six hours, at minute 17 UTC, and supports **Run workflow**
for immediate refresh. Scheduled runs can be delayed by GitHub; GitHub may disable
scheduled workflows after 60 days of inactivity in public repositories. If that
happens, re-enable the workflow in Actions. Updates are committed only when the
generated content changes. GraphQL errors or incomplete pagination fail the run
without replacing the previously published cards.

The workflow uses the repository's built-in `GITHUB_TOKEN` with `contents: write`;
no personal access token, external card server or paid service is needed.

Local refresh (Python 3.10+, authenticated GitHub CLI or `GITHUB_TOKEN`):

```sh
python -m unittest discover -s tests -v
python scripts/update_contributions.py --login Cordis798
```

The script uses GitHub's GraphQL API directly when a token is supplied and otherwise
uses `gh api`. It does not save credentials. Data comes from the account's authored
merged PRs, including PRs in both personal and external public repositories.
