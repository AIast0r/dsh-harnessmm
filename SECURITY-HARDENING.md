# Security and Windows fixes (v0.1.5-security.1)

This community fork changes local safety defaults without modifying the upstream
HarnessMM decision graph algorithms.

## Changes

- A Windows `EPERM` / sharing violation during atomic `stats.json` replacement
  no longer terminates the DSH agent turn. The original stats file is never
  unlinked or overwritten non-atomically: persistence becomes best-effort.
- Audit JSONL now records only event kinds, hashes and selected numeric/boolean
  counters, not full tool-call arguments, native receipts, prompts or model
  responses. **Older audit files may still contain sensitive information.**
- Automatic improvement is disabled by default. The `harnessmm_improve` tool
  requires `allowManualImprove: true`; all unsandboxed RSI additionally
  requires `allowUnsafeCodeExecution: true`. Without these settings,
  graph-based guarded reuse continues to function.
- Windows cancellations use `taskkill.exe /T /F` where available, instead of
  POSIX-only `os.killpg`, to terminate owned child processes. This is a
  compatibility improvement, not a guarantee that every descendant exits.
- Model worker stdout/stderr is hashed rather than copied wholesale into
  per-episode JSON artifacts. Training feedback still goes to the configured
  model provider, as required by the algorithm.
- Custom corpus seed paths reject drive-relative, absolute, UNC, reserved device
  names and trailing-dot/space forms on Windows.

## Security boundary

**This patch does not sandbox generated code.** Opting in to RSI can execute
model-produced Python with the operating-system permissions and network access
of your DSH environment. For actual security isolation, use a separate VM,
restricted OS account or sandbox, with no personal files or provider secrets.

It also does not erase existing audit logs or control DSH's own model, debug
or provider-plugin logs. Review and remove sensitive prior logs manually.

## Validation

```sh
node --check index.mjs
node --check jobs.mjs
node --test tests/security-hardening.test.mjs
PYTHONPATH=python python -m pytest python/tests/test_security_hardening.py
```

CI executes the focused checks on Linux and Windows. Live DSH Desktop and
real provider / cancellation integration still require separate qualification.
