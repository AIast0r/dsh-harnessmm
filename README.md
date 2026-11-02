# HarnessMM for DeepSeek Harness

My DSH integration of [HarnessMM](https://github.com/YuhuaJiang2002/HarnessMM): guarded reuse of stored tool decisions, plus protected evaluation of route-specific procedures.

[Download 0.1.4](https://github.com/DSH-Extensions-list/dsh-harnessmm/releases/latest) · [Verification](VERIFICATION.md) · [Provenance](DISTRIBUTION.md)

A persistent provider-independent extension implementing the authors' guarded executable decision graphs and protected recursive harness improvement. Model weights remain fixed. Every selected action executes through the native DSH tool pipeline, retaining its permissions, cancellation and logging.

## Install

This release is **`@local/dsh-harnessmm` 0.1.4**. It targets **Node.js 22.19 or newer** and **DSH `>=0.2.1-rc.2 <0.2.2`**. Another runtime version needs qualification.

1. Download `local-dsh-harnessmm-0.1.4.tgz` and `SHA256SUMS` from [Releases](https://github.com/DSH-Extensions-list/dsh-harnessmm/releases/latest), and verify the checksum.
2. In DSH Desktop, open **Plugins → Add plugin**, enter the archive’s full local path, install it, and choose **Enable now**.
3. Reload/restart DSH when prompted, then start a new session.

For a CLI profile:

```sh
dsh plugin --profile web add /absolute/path/to/local-dsh-harnessmm-0.1.4.tgz
```

Graph reuse uses the existing provider/model route. Self-improvement additionally needs Python 3.11+, a native `harnessmm-training` SDK profile with the required provider plugins, and access to the matching DSH SDK source/build. Set `DSH_SOURCE_ROOT` to your DSH source checkout before starting DSH, and configure `dshExecutable`, `dshHome`, and `pythonExecutable` for your machine. The captured adapter retains the development machine’s fallback source paths; these are not portable defaults. Direct Python CLI use also supports `--dsh-bin`, `--sdk-module`, and `--meter-module`. See [python/README.md](python/README.md).

**Automatic improvement defaults to enabled:** after 20 completed turns on a route, while idle, with a 24-hour cooldown and two proposal iterations. These runs use model calls. Set the plugin’s `autoImprove` configuration to `false` for graph reuse or manually started improvement only. This release does not include my credentials, training-profile configuration, learned policies, or runtime state.

## Runtime behavior

The original slow model authors exact future calls using the published CHISEL_PLAN schema. The authors' ExecutableSubdag controller retains the graph, validates literal arguments and checks actual public receipts. One eligible action can replace a model request; ambiguity, unsupported evidence, errors, changed user input, missing cost prior and graph exhaustion return to the native model. Auxiliary title and compaction calls are untouched. Controllers and usage priors are separated by session and exact provider/model/reasoning route. The optional one-token probability selector is unavailable unless a native provider exposes the required verified interface; this version abstains on ambiguity rather than fabricating probabilities or routing to another provider.

Foreground bash/pwsh results receive a short logged authenticated receipt with actual exit metadata. The extension does not infer a successful process from printed stdout. Certificates require a matching native dispatch and successful final native result; denial and suppressed execution cannot increment certified substitutions. Counts record model-boundary attempts and substitutions, not counterfactual tokens saved.

## Self-improvement

`harnessmm_improve` starts a background run using the current provider/model, or explicit provider/model and optional reasoningEffort. `harnessmm_status` shows progress and durable paths; `harnessmm_cancel` stops the run and its owned native workers.

Automatic improvement is enabled after 20 completed turns on a route, while the observed process is idle, with a 24-hour cooldown and two feedback-guided proposal iterations per run by default. These are configurable extension fields. Training uses the bundled declared 20-unit synthetic coding corpus, not personal chat history or working projects. Every episode gets a fresh native SDK session and temporary task workspace. The verifier stays outside the agent workspace and its program is not supplied to the actor or optimizer.

The Python adapter calls the authors' exact IndustrialEfficiencyController for TRAIN, protected validation and source/policy freeze. Their shared base controller performs the paired TEST on this fresh local corpus; the published historical-test prohibition is preserved in the untouched upstream source. The split is grouped 20/20/60, seed 20260928. Previous candidate results feed subsequent TRAIN proposals. Validation/test traces never enter optimization. Measured calls, retries, failures, optimization and execution costs remain separately accounted; missing usage is unknown, never zero.

Only complete frozen candidates with nonregressing observed TEST quality and strictly fewer measured tokens can activate automatically. A noop or failed candidate leaves the previous deployed policy in place. Policy routing uses the authors' exact FrozenPolicy implementation and applies the evaluated user-prompt suffix placement. Policies are tied to the tested provider/model/reasoning and runtime source identity, with no assumed cross-provider transfer. A newly observed session establishes its native route before learned hints may apply. An unexpected dynamic route override fails closed before sending an incompatible policy to a provider.

This is a local synthetic coding evaluation, not independent evidence of paper-level benchmark performance or universal savings. No recurring synthetic result alone establishes quality on arbitrary user work.

## Configuration and storage

The native plugin configuration exposes enabled, autoImprove, autoImproveAfterTurns, autoImproveCooldownMs, iterations, episodeTimeoutMs, graph bounds, dataDirectory, corpusPath, trainingProfile, pythonExecutable, dshExecutable and dshHome. Defaults store private logs, job receipts, exact-route policy pointers and audits under `$DSH_HOME/storages/harnessmm`.

The isolated `harnessmm-training` profile must include native SDK/base tools, the user's native provider configuration, provider plugins and this extension. It excludes Conductor orchestration and desktop UI. Provider authentication uses the normal native credential service; no keys are copied into the extension. All providers reachable through the shared DSH model service can use graph reuse. Training additionally requires a provider/model with native tool use and sufficient quality to complete the declared tasks. Reasoning effort is omitted when no explicit selection is supplied.

Set DSH_HARNESSMM_ENABLED=0 to disable graph behavior in an experimental baseline, DSH_HARNESSMM_NO_POLICY=1 to disable learned policy application, and DSH_HARNESSMM_TRAINING=1 in training children to prevent recursive automatic improvement. Unloading the extension cancels its active improvement run; active task histories remain in native storage. The package is additive and does not replace any existing model provider or orchestrator.

## Verify

Run `node --test tests/*.test.mjs` from the source tree. Python checks use `PYTHONPATH=python:vendor/harnessmm python -m pytest python/tests`. Installed upstream verification uses `PYTHONPATH=python:vendor/harnessmm python -m dsh_harnessmm_rsi doctor`. These keyless checks do not establish live model quality or measured token savings.

## Credits and license

Adapted from HarnessMM by Yuhua Jiang, Chang Xu, Feifei Gao, and Li Zhao, pinned to revision `c8f19947e59feaa8103c05155bd79ef3eb084730`. I retain the authors’ implementation and notices; the native DSH integration and packaging are additions. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [LICENSE](LICENSE), and [DISTRIBUTION.md](DISTRIBUTION.md).
