# Developing the Rubrik SDK

For working on the SDK itself: how it is built, how to add a query, the
checks, and the weekly release cadence. For using it, see the
[README](../README.md).

## How it is built

```
client.py      RubrikClient: connection, the groups, execute / change
auth.py        ServiceAccount, and the token exchange (sdk-primer's)
errors.py      RubrikError, GraphQLError, ChangesNotAllowed
query.py       ConnectionQuery: one GraphQL document, parsed and paged
pagination.py  Page, PageInfo, Collection
common.py      small shared models (cluster and SLA references)
activity.py  cluster.py  sla_domain.py  mssql.py      the groups
probe.py       rubrik-probe
```

It sits on `sdk-primer-core` for transport - retries, typed exceptions,
request logging, the service-account token exchange. RSC has one
endpoint, `POST /api/graphql`, so every group calls
`RubrikClient.execute` (queries) or `RubrikClient.change` (mutations:
refused on a read-only client, never retried).

## Adding a query

1. Find the operation in Rubrik's PowerShell SDK
   (`docs/graphql/operations/*.graphql` in
   github.com/rubrikinc/rubrik-powershell-sdk) - those are real
   documents RSC accepts. Copy the fields you need, not the whole
   fragment.
2. Add a model with those fields and a method on the group it belongs
   to. A mutation goes through `change`, however harmless it looks.
3. Run it against a real RSC account before relying on it. A field the
   schema does not have fails the **whole** query, not just that field;
   add the field names to `rubrik-probe`'s checks so the first run says
   which are real.
4. Add it to the README's table, with whether it has been run.

## Checks

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The tests mock HTTP with respx; none needs an RSC account. Before
trusting a new query, run it against a real one.

## Releases

This SDK is released on the same weekly clock as blt, with the same
branch names. `main` holds only released code; nothing is committed to
it directly.

### The week

| Day | What happens |
|---|---|
| Monday | The previous week's release branch is merged to `main` and tagged. The new week's release branch opens from `main`. |
| Monday - Thursday | Work happens on short branches and is merged into the week's release branch as each piece is finished. |
| Thursday, end of day | Cut-off. What is not merged waits for next week. |
| Friday | The release branch is tested as a whole (see below). No new work goes in - only fixes for what the testing finds. |
| Monday | If Friday's tests passed, release. If not, the release is held until they do, or skipped. A week in which nothing was merged has no release. |

### Names

A release is named for the Monday it is released on: `YYYY.MM.Wnn`,
where `nn` counts the Mondays of that month. Work done in the week of
12 October 2026 goes into `release/2026.10.W03` and is released on
Monday 19 October, the third Monday of October. So the branch to be on
is always the one named for **next** Monday.

| Thing | Name | Example |
|---|---|---|
| Release branch | `release/<release>` | `release/2026.10.W03` |
| Feature branch | `<release>/F/<What_it_does>` | `2026.10.W03/F/Job_details` |
| Bug-fix branch | `<release>/B/<What_it_fixes>` | `2026.10.W03/B/Paging_stops_early` |
| Hotfix branch | `<release>/H/<What_it_fixes>` | `2026.10.W03/H/Token_renewal_loop` |
| Release tag, on `main` | `v<major>.<minor>.<patch>` | `v0.2.0` |

The one difference from blt is the tag. blt is deployed, and its tag is
the week's name. This is a library that other projects pin, so its tag
and the version in `pyproject.toml` say what a caller needs to know
about the change: a new call or option is a minor step (`v0.1.0` to
`v0.2.0`), a week of only fixes is a patch step (`v0.2.0` to `v0.2.1`),
and a change that would break a caller is a major step. The tag's
message names the release branch it came from.

### The loop for one piece of work

```
git checkout release/2026.10.W03 && git pull
git checkout -b 2026.10.W03/F/Job_details
# small commits, each with its tests; run the checks before every one
git push -u origin 2026.10.W03/F/Job_details     # and push often
git checkout release/2026.10.W03
git merge --no-ff 2026.10.W03/F/Job_details
git push
```

- **Commit small and often.** One call, one fix or one finding per
  commit, with its tests in the same commit, and `ruff`, `mypy` and
  `pytest` passing at each one (see Checks). Push as you go; the
  branch on GitHub should never be far behind.
- **A new or changed call is run against a real RSC account before it
  is called proven**, and the commit message says what that showed.
  Until then the README marks it "written, not run". (The Commvault SDK
  found that nearly every endpoint differed from its documentation in
  some way; expect the same here.)
- **Feature and bug-fix branches** start from the week's release branch
  and merge back into it.
- **Hotfix branches** are for something a user of the SDK cannot wait
  until Monday for. They start from `main`, merge to `main` with a patch
  tag, and are then merged into the open release branch as well.

### Friday's test

By Thursday's cut-off, the release branch already carries the new
version: `version` in `pyproject.toml` set to the coming tag without its
`v`, then `uv lock`, on an `H/` branch like any other change. Friday
then tests what Monday ships, and the tag and the package agree.

On the release branch, all of:

1. `ruff check`, `ruff format --check`, `mypy`, and the unit tests.
2. Every call added or changed that week, run against a real RSC account
   (`rubrik-probe`), and the README's table saying truthfully which are
   proven.
3. blt's own tests with its `rubrik-sdk` source pointed at this
   checkout (`{ path = "../yoki-py-rubrik-sdk", editable = true }`),
   so a change that breaks its first user is found before the tag.

If no RSC account is reachable, step 2 has not happened: the calls stay
marked "written, never run" and the tag message says so.

### Releasing, on Monday

```
git checkout main && git pull
git merge --no-ff release/2026.10.W03 -m "Release v0.2.0 (2026.10.W03)"
git tag -a v0.2.0 -m "2026.10.W03: what changed, in a line or two"
git push origin main v0.2.0
git checkout -b release/2026.10.W04 && git push -u origin release/2026.10.W04
```

The tag has to be pushed by name, as above: a plain `git push` does not
send tags, and blt cannot pin a tag that is not on GitHub.

blt takes the new SDK on its own release branch for the following week:
change the tag for `rubrik-sdk` under `[tool.uv.sources]` in its
`pyproject.toml`, run `uv lock`, run blt's tests, commit.

The same Monday, the branches of any release that went out a month or
more ago come off GitHub (see Tidying up).

### Tidying up

A branch is deleted locally once it has been merged, and from GitHub a
month after the release it went out in.

Locally, straight after the merge:

```
git branch -d 2026.10.W03/F/Job_details
```

`git branch -d` refuses to delete a branch that has not been merged
into the branch you are on, which is the check that nothing is lost. A
release branch is deleted locally the same way after its Monday
release; the tag keeps that release reachable.

On GitHub, each release's branches - its work branches and the release
branch itself - stay up for a month after that release, so a week's
work can still be looked at branch by branch while it is recent. They
come off on the first release Monday a month or more after the
release: `2026.10.W03`, released Monday 19 October, has its branches
deleted from GitHub on Monday 23 November, as part of releasing
`2026.11.W04`.

```
git fetch --prune
git branch -r --list 'origin/2026.10.W03/*' 'origin/release/2026.10.W03'
git push origin --delete 2026.10.W03/F/Job_details 2026.10.W03/F/Job_task_details ... release/2026.10.W03
git fetch --prune
```

Only a release that has been tagged is tidied this way. A branch that
was never merged stays until someone decides about it.
