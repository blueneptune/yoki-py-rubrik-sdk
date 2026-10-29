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
tools/         rubrik-probe, rubrik-sample, rubrik-mask and their .env
               settings - see the README's "Running it on its own"
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

While blt and the yoki SDKs are still being built, there is no weekly
release train: it was paused on 2026-10-29, and comes back once
something outside the project depends on these releases. Work is merged
to `main` as soon as it is finished and CI passes, and this SDK gets a
tag when a project needs what changed.

### The loop for one piece of work

```
git checkout main && git pull
git checkout -b F/What_it_does
# small commits, each with its tests; run the checks before every one
git push -u origin F/What_it_does        # and push often: CI runs on every push
git checkout main && git pull
git merge --no-ff F/What_it_does
git push
git branch -d F/What_it_does && git push origin --delete F/What_it_does
```

| Thing | Name | Example |
|---|---|---|
| Feature branch | `F/<What_it_does>` | `F/Job_details` |
| Bug-fix branch | `B/<What_it_fixes>` | `B/Paging_stops_early` |
| Release tag, on `main` | `v<major>.<minor>.<patch>` | `v0.2.0` |

- **Commit small and often.** One change or one fix per commit, with
  its tests in the same commit, and the checks passing at each one.
  Push as you go; the branch on GitHub should never be far behind.
- **A new or changed call is run against a real RSC account before it
  is called proven**, and the commit message says what that showed.
  Until then the README marks it "written, not run". (The Commvault SDK
  found that nearly every endpoint differed from its documentation in
  some way; expect the same here.)
- **`main` always passes.** Merge a branch only once CI is green on it.
- **Delete a branch once it is merged**, locally and on GitHub.
  `git branch -d` refuses a branch that is not merged, which is the
  check that nothing is lost.

### Tagging a release

When a project needs a change that is on `main`, check `main` first:

1. `ruff check`, `ruff format --check`, `mypy`, and the unit tests.
2. Every call added or changed since the last tag, run against a real RSC account
   (`rubrik-probe`), and the README's table saying truthfully which are
   proven.
3. blt's own tests with its `rubrik-sdk` source pointed at this
   checkout (`{ path = "../yoki-py-rubrik-sdk", editable = true }`),
   so a change that breaks its first user is found before the tag.

If no RSC account is reachable, step 2 has not happened: the calls stay
marked "written, never run" and the tag message says so.

Then set the version and tag it:

```
git checkout -b B/Version_0_3_0
# version in pyproject.toml, without the v; then:
uv lock
git commit -am "Version 0.3.0"
git checkout main && git merge --no-ff B/Version_0_3_0 && git push
git tag -a v0.3.0 -m "What changed, in a line or two"
git push origin v0.3.0
```

The version and `uv lock` go in the same commit: a version set without
it leaves the lockfile behind. The tag has to be pushed by name, as
above: a plain `git push` does not send tags, and nothing can pin a tag
that is not on GitHub. A new call or option is a minor step (`v0.1.0`
to `v0.2.0`), only fixes a patch step (`v0.2.0` to `v0.2.1`), and a
change that would break a caller a major step.

blt and the other projects that use it then take the new tag: change the tag for `rubrik-sdk` under
`[tool.uv.sources]` in their `pyproject.toml`, run `uv lock`, run their
tests, commit. Projects pin tags. A pin to a commit is only for a
change still on its way, and is replaced by the tag before that
project's own branch is merged.
