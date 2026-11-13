# Commit plans — who commits what

There's one file per implementation plan (`planing/`). Each lists **every commit in merge order**: the member,
their branch, the commit message, the files, and the Jira task. That makes each member's contribution
visible in `git log` and `git shortlog -sn`, and separately assessable, as the proposal requires.

| Plan | Weeks | File | Status |
|---|---|---|---|
| 1 | 1–2 | [commit-plan-01.md](commit-plan-01.md) + [plan-01-commits.sh](plan-01-commits.sh) | **Implemented.** All files exist and the script is verified |
| 2 | 3–5 | [commit-plan-02.md](commit-plan-02.md) | Projected |
| 3 | 6–7 | [commit-plan-03.md](commit-plan-03.md) | Projected |
| 4 | 8–9 | [commit-plan-04.md](commit-plan-04.md) | Projected |
| 5 | 10–11 | [commit-plan-05.md](commit-plan-05.md) | Projected |
| 6 | 12–13 | [commit-plan-06.md](commit-plan-06.md) | Projected |
| 7 | 14–15 | [commit-plan-07.md](commit-plan-07.md) | Projected |
| 8 | 16 | [commit-plan-08.md](commit-plan-08.md) | Projected |

"Projected" means the file paths are where the code *should* go under the repository layout from Plan 1. When a
plan is implemented, update its file to match what was actually committed.

## Workflow for every commit

```bash
git switch main && git pull
git switch -c <member>/<jira-id>-<topic>          # e.g. naitik/19-bid-validation
# ... work ...
git add <the files listed for your commit>
git commit -m "<message from the plan>"            # Conventional Commits + Jira id
git push -u origin HEAD                            # open a PR; 2 approvals + green CI to merge
```

Rules (from `docs/engineering-conventions.md`):

- **Commit only the files listed for you.** If you need to touch another owner's files, ask them, or get their
  approval on the PR.
- **Merge order matters.** A commit that depends on another is listed after it. Don't merge ahead of your
  dependencies.
- **Each plan ends with a milestone tag** (`plan-01` … `plan-08`), created by the milestone owner once the
  plan's definition of done is checked off.
- Every commit message carries its Jira id, so hours and commits can be reconciled at the week 5, 9 and 13 audits.

## Replaying Plan 1 on one machine

Right now all the Plan 1 files are sitting uncommitted in one working tree. You have two ways to commit them:

- **Team workflow**: each member commits their own files (listed in `commit-plan-01.md`) on their branch and opens a PR.
- **One machine**: edit the emails at the top of `plan-01-commits.sh`, then run:

  ```bash
  bash commits/plan-01-commits.sh --check   # every file is in exactly one commit
  bash commits/plan-01-commits.sh           # dry run
  bash commits/plan-01-commits.sh --apply   # 33 commits, each authored by its member
  ```
