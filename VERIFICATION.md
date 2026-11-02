# DSH HarnessMM 0.1.4 verification — 2 November 2026

The persistent `@local/dsh-harnessmm` bundle is installed, enabled and active in the existing DSH desktop profile. Installation used DSH's native plugin-manager API. Existing dependency specifications and earlier bundle entries were retained. Codex standalone 0.165.0 and desktop app-server 0.166.0 selections and Codex configuration were not changed.

## Delivered behavior

- The authors' unmodified ExecutableSubdag/GDR/CCS implementation is integrated at native `llm/stream` boundaries, with exact tool arguments and native dispatch/approval/cancellation.
- Foreground shell exit metadata is materialized into the logged result and authenticated locally; printed stdout cannot forge it. Denied/nonexecuted calls do not receive substitution certificates.
- Graph state, cost priors and learned policy application are separated by native session and provider/model/reasoning route. Title/compaction calls remain unchanged.
- The authors' IndustrialEfficiencyController supplies iterative TRAIN proposals, protected validation, source/policy freeze and their shared base controller's paired TEST on a declared fresh local corpus. The upstream historical-TEST restriction remains unchanged in upstream source; the local adapter explicitly qualifies base-method dispatch for its independent corpus.
- Model weights stay fixed. Learned procedures use the evaluated user-prompt suffix placement and exact FrozenPolicy routing. Source changes and mismatched routes reject policy application.
- Defaults: automatic improvement after 20 completed turns on a route, a 24-hour cooldown, two feedback-guided proposal iterations, and a 300-second deadline per episode. Training uses a 20-unit synthetic coding corpus with the authors' grouped 20/20/60 split. It does not read personal chats as training examples.
- Background training is guarded by a process lock. Each actor and optimizer gets a private external audit/state directory and fresh task workspace. Cancellation and parent death terminate owned workers.
- A frozen candidate activates only after complete observed TEST quality does not regress and complete measured tokens decrease. Failed, incomplete, noop and rejected candidates leave deployment unchanged.

## Fresh checks

15 Node tests and 22 Python/native-SDK tests passed: **37 total**. The native cases ran both source and installed packages through real DSH SDK profiles, scripted LLM adapters, the ordinary tool pipeline and actual Bash execution.

| Native case, repeated for source and installed bundle | Executed sequence | Original adapter calls | Certified substitutions |
| --- | --- | ---: | ---: |
| fixture-alpha | root → A → B | 2 | 2 |
| fixture-beta | root → A → B | 2 | 2 |
| Native policy denies A | root | 2 | 0 |

These are keyless fixtures. Their 80,000-token counters are scripted native accounting fixtures, not paid usage or evidence of real token savings. See `verification/native-graph/native-graph-summary.json` and individual case receipts.

A real native SDK/API text smoke check on the existing BharatCode Flash route completed with the expected response and 8,890 measured tokens. The tools were present in that native profile. This establishes one live route, not all account/provider entitlements.

An early background acceptance run was cancelled to fix shared training-child state; its records were preserved and the coordinator returned to idle after the fix. A separate bounded 90-second real coding episode reached a native Bash read but timed out before completing the task. Its complete usage stays unknown and it did not pass the verifier. Production defaults allow 300 seconds. No complete live optimization/evaluation campaign has finished, no learned policy is active, and no quality/token-saving improvement is claimed.

## Limits and use

The integration commits a unique locally eligible stored action. Ambiguous cases abstain and return to the original provider/model; the paper's optional one-token probability selector is not enabled across heterogeneous providers. Benchmark-specific remote runners are bundled as upstream source but are not automatically launched or represented as reproduced benchmark results.

Use `harnessmm_status` for current statistics/job state, `harnessmm_improve` to start a background run on the current or explicitly selected provider/model, and `harnessmm_cancel` to stop the owning instance's active run. The separate `harnessmm-training` SDK profile shares only the normal native credential service and provider configuration; it excludes desktop UI and Conductor orchestration. Existing provider and Conductor configuration in the desktop profile was retained.

The package and source archive checksums are in `SHA256SUMS`. Native installation state, test logs, actual API smoke usage, the timed-out coding probe, and native fixture receipts are saved under `verification/`.

## Public release check

Before publishing 0.1.4, I reran the source checks on the clean publication tree: **15 Node tests and 22 Python/native-SDK tests passed**, with no skipped tests. These checks made no model/provider calls. Runtime files were retained unchanged; caches and generated test receipts were excluded. The captured development-path fallbacks remain, and another machine needs the README’s path/profile configuration.
