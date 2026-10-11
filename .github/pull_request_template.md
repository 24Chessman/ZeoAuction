## What and why

<!-- One or two sentences. Link the Jira task: #NN -->

Jira: #

## Checklist

- [ ] One Jira task (or a clearly related set) per PR
- [ ] `ruff check .` passes and the unit tests pass locally
- [ ] Tests added or updated (coverage at least 80% for this service)
- [ ] Contract changes (`contracts/`) approved by the interface owner, and the versioning rule followed
- [ ] Schema changes (`infra/postgres/init/`) approved by the schema owner
- [ ] Money handled as decimal strings, never floats
- [ ] No secrets, KYC document bytes or signed URLs in code or logs

## How to verify

<!-- Commands or steps a reviewer can run, e.g. `make up` then `curl localhost:8004/healthz` -->
