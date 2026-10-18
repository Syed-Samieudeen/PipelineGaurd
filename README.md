# PipelineGuard

Self-healing data pipelines for IBM Z / LinuxONE (s390x): predictive failure
classification (scikit-learn, optional Snap ML) + an optional **local IBM
Granite** diagnosis step + an isolated sandbox where every repair is tested
**before** it is allowed anywhere near live data.

Granite is **optional**. PipelineGuard works fully with no model server, no
network access and no extra Python dependencies.

---

## Quick start

```bash
pip install -r requirements.txt

python guard.py train                          # build dataset from real failures + train classifier (models/metrics.json)
python guard.py demo --fault schema            # schema|type|nulls|duplicates|corrupt   (or --all)
python guard.py demo --fault nulls --approve   # accept the REVIEW-level fix like a human would
python monitor.py                              # terminal 1: always-on watcher
python guard.py inject --fault nulls           # terminal 2: break the live file
python guard.py pending                        # fixes waiting for a human
python guard.py approve <id> [--force]         # human approves (--force for HOLD-level)
python guard.py reset                          # restore clean data
python -m pytest test_pipelineguard.py -q      # run the test suite (no model server needed)
```

Outputs: `reports/incident_<id>.md`, `logs/audit.jsonl`, `runs/<id>/`
(sandbox workspace), `data/backup/` (rollback copies), `data/pending/`
(fixes waiting for approval).

---

## Architecture

```
                 ┌────────────────────────────────────────────────────────────┐
                 │                     pipeline (etl.py)                      │
                 │   clean CSV ──> validate / transform ──> amount_with_tax   │
                 └───────────────┬────────────────────────────────────────────┘
                                 │ failure (non-zero exit + error text)
   ┌─────────────────────────────▼─────────────────────────────────────────────┐
   │ 1 DETECT      monitor.py / guard.py watch the live input + pipeline exit  │
   │ 2 CLASSIFY    Random Forest on (error text + data profile features);      │
   │               optional Snap ML accelerator, sklearn fallback              │
   │ 3 REPRODUCE   failure re-run in the sandbox (docker, or process fallback) │
   │ 4 DIAGNOSE    optional IBM Granite (local LLM) returns a JSON *proposal*  │
   │               root_cause / repair_strategy / proposed_changes / risks /   │
   │               confidence — validated against a per-failure allowlist      │
   │ 5 FIX         PipelineGuard generates repair.py from ITS OWN              │
   │               deterministic template (never model-written code)           │
   │ 6 SANDBOX     repair.py + etl.py run in the sandbox, never on live data   │
   │ 7 VALIDATE    row/column/pk/null/median/output checks on sandbox output   │
   │ 8 RISK        score -> PROCEED (<0.25) / REVIEW (<0.50) / HOLD           │
   │ 9 APPROVE     auto-apply | human approves (pending queue) | escalate      │
   │ 10 APPLY      live input backed up first, then replaced, pipeline re-run  │
   │ 11 AUDIT      every step -> logs/audit.jsonl + reports/incident_<id>.md   │
   └───────────────────────────────────────────────────────────────────────────┘
```

Module map: `monitor.py`/`guard.py` (detection & orchestration),
`classifier.py` + `snapml_adapter.py` + `datafeatures.py` (classification),
`fixer.py` (Granite diagnosis + repair templates), `sandbox.py` (isolated
execution), `validate.py` (repair quality checks), `risk.py` (scoring gate),
`report.py` (audit trail + human report), `faults.py`/`dataset.py`
(realistic failure injection for demos/training), `etl.py` (the pipeline
being protected).

### Safety model — what Granite can and cannot do

Granite is a **diagnosis advisor, never an executor**:

* It receives only incident context (failure class, truncated error message,
  column names, a 3-row data sample, ETL rules). **No credentials, no API keys,
  no secrets, no full datasets** are ever sent to the model.
* It must answer with one strict JSON object
  (`root_cause`, `repair_strategy`, `proposed_changes`, `reasoning`, `risks`,
  `confidence`). The response is parsed and structurally validated; malformed
  JSON, missing fields, wrong types or an out-of-range confidence are rejected.
* `repair_strategy` must be on a **per-failure allowlist**:

  | Failure class      | Allowed strategies              |
  |--------------------|---------------------------------|
  | `schema_mismatch`  | `rename_columns_to_expected`    |
  | `type_mismatch`    | `coerce_amount_numeric`         |
  | `null_explosion`   | `impute_missing_values`         |
  | `duplicate_keys`   | `drop_duplicate_keys`           |
  | any                | `escalate_to_human`             |

  Anything else is rejected as `unsafe` and PipelineGuard falls back to its
  deterministic template.
* The executed `repair.py` is **always PipelineGuard's own template** for the
  chosen strategy. Model text is never written into the script and never
  executed. The model's contribution is limited to *which* restricted strategy
  is used, plus the human-readable diagnosis in the report.
* The repair still has to pass **the same sandbox test, validation checks,
  risk scoring and approval gate** as a purely template-generated fix. The
  model cannot authorize anything.
* The report and audit trail always state the repair source:
  * `Granite (<model>) strategy '<x>' executed via deterministic template`
  * `template (Granite unavailable/invalid/rejected: ...)`
  * `deterministic template (GRANITE_ENABLED not set)`

---

## Configuring the optional IBM Granite step

Environment variables (all optional):

| Variable           | Default                                   | Meaning |
|--------------------|-------------------------------------------|---------|
| `GRANITE_ENABLED`  | *(unset = disabled)*                      | `1`/`true`/`yes`/`on` enables the diagnosis step |
| `GRANITE_BASE_URL` | `http://127.0.0.1:8080/v1`                | OpenAI-compatible endpoint (`llama-server` default) |
| `GRANITE_MODEL`    | `ibm-granite/granite-3.3-2b-instruct`     | model name sent to the server (informational for `llama-server`; must match the pulled tag for Ollama) |
| `GRANITE_TIMEOUT`  | `30`                                      | seconds to wait for a proposal; on timeout/error PipelineGuard falls back to templates |
| `GRANITE_API_KEY`  | *(unset)*                                 | optional bearer token if your server requires one (never logged) |

Any OpenAI-compatible server works (`llama-server`, Ollama's `/v1`, vLLM, …).
The HTTP call uses only the Python standard library (`urllib`) — **no new pip
dependencies**, which matters on s390x where wheels can be scarce.

### Running with Granite

```bash
export GRANITE_ENABLED=1
export GRANITE_BASE_URL=http://127.0.0.1:8080/v1
export GRANITE_MODEL=ibm-granite/granite-3.3-2b-instruct
export GRANITE_TIMEOUT=30
python guard.py demo --fault type --approve
```

The incident report gains a "Diagnosis proposal (advisory — not
authorization)" section with the model's root cause, strategy, reasoning and
self-reported risks. A confidence below 0.5 is flagged `⚠️ LOW — treat as
uncertain` for the human reader; it does **not** change which gates run.

### Running without Granite

Do nothing — with `GRANITE_ENABLED` unset there is **no network call at all**
and repairs come straight from the deterministic templates
(source: `deterministic template (GRANITE_ENABLED not set)`). The same is true
mid-incident if the model is slow, down, returns garbage or proposes something
off-allowlist: you get the template fallback, the pipeline keeps healing, and
the report records why Granite was not used. PipelineGuard never blocks on the
model.

---

## Installing the model server on IBM Z / LinuxONE

These are the **official llama.cpp instructions for s390x**
(`docs/build-s390x.md`, verified 2026-09). We use `llama-server` because it
exposes the OpenAI-compatible API that `fixer.py` speaks.

1. Build llama.cpp with BLAS (strongly recommended — the VXE/VXE2 SIMD path
   depends on it):

   ```bash
   git clone https://github.com/ggml-org/llama.cpp
   cd llama.cpp
   cmake -S . -B build             \
       -DCMAKE_BUILD_TYPE=Release  \
       -DGGML_BLAS=ON              \
       -DGGML_BLAS_VENDOR=OpenBLAS
   cmake --build build --config Release -j $(nproc)
   ```

2. Get a **big-endian** GGUF Granite model. On s390x, little-endian GGUF
   files do not load. Either use a pre-verified one from the
   `s390x-verified-models` Hugging Face collection, or convert from safetensors:

   ```bash
   git clone https://huggingface.co/ibm-granite/granite-3.3-2b-instruct
   python3 convert_hf_to_gguf.py \
       --outfile granite-3.3-2b-instruct-be.f16.gguf \
       --outtype f16 --bigendian \
       granite-3.3-2b-instruct/
   ```

   If you get `... mismatch between the host and model endianness?` when
   loading, the file is little-endian — re-convert as above.

3. Serve it (this is the default URL PipelineGuard expects):

   ```bash
   ./build/bin/llama-server \
       -m granite-3.3-2b-instruct-be.f16.gguf \
       -c 4096 -t 3 --host 127.0.0.1 --port 8080
   ```

   Sanity check from another shell:

   ```bash
   curl http://127.0.0.1:8080/v1/models
   ```

4. Point PipelineGuard at it (`GRANITE_ENABLED=1`, see above) and run a demo.

Keep the server on `127.0.0.1` unless you deliberately expose it — it has no
authentication by default. If you must remote-enable it, put it behind a
reverse proxy and set `GRANITE_API_KEY`.

### LinuxONE resource limits (our target: ~3 vCPU / 8 GB RAM)

Honest constraints for this project's target configuration:

* The official llama.cpp guidance recommends **≥ 8 IFLs** for an LPAR; 3 vCPU
  is well below that. Prompt processing will be slow — expect the diagnosis
  call to take several seconds to tens of seconds. That is why
  `GRANITE_TIMEOUT` exists and why the timeout path falls back to templates
  instead of stalling the incident.
* Use the **2B** model (Granite 3.3 2B, ~4 GB in f16) and keep `-c 4096`
  (context) small so total memory stays under 8 GB together with the PipelineGuard
  process (pandas + sklearn ≈ a few hundred MB). Larger Granite variants will
  not fit comfortably.
* Prefer f16 or Q8_0/Q4_K quants — the s390x SIMD support matrix covers
  f16/bf16/Q4_0/Q4_1/Q5_0/Q5_1/Q8_0/Q4_K/Q5_K/Q4_NL; several IQ* and TQ*
  quantizations have **no** SIMD acceleration (they still run, just slower),
  and endian-conversion tooling may not support every quantization.
* SMT off and LPAR (Type-1) virtualization are recommended by IBM for
  inference performance.
* Everything in PipelineGuard itself is comfortably within budget: the
  heaviest step is the scikit-learn classifier on a 500-row CSV.

### Verified on this development machine

The end-to-end demos and the test suite were run and verified on a Windows
dev box (Python 3.13, no Docker, no model server). The s390x commands above
are reproduced from the official llama.cpp documentation; **the Granite path
has not yet been exercised against a real Granite model on real s390x
hardware** — the automated tests mock the OpenAI-compatible endpoint. See
"Current status & limitations" below.

---

## Sandbox: what it protects against, and what it does not

`repair.py` (and the ETL re-run) **only ever execute inside the sandbox**.
The sandbox first re-runs the original pipeline to prove it can reproduce the
failure, then runs the repair on a copy of the data in `runs/<id>/`.

* **With Docker** (`sandbox.py` docker path) the container runs with
  `--network none`, `--read-only` root, `--memory 256m`, `--cpus 1`,
  `--pids-limit 128`, `--user <your uid>`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, a hard timeout, and `docker kill` on
  timeout. This is real isolation.
* **Without Docker** (`sandbox_mode: "process-fallback"`, e.g. this project's
  Windows dev box) there is **no container-level isolation** — only a separate
  working directory and a subprocess. Do not describe the fallback as a
  security boundary; on a shared machine, run with Docker. The sandbox mode is
  always printed and recorded in the audit trail so nobody has to guess.

Limitations in both modes: the sandbox tests the repair against the *current*
data snapshot; it cannot predict downstream consumers' behaviour, and the
validation heuristics (median shift ≤ 20%, extra row loss ≤ 5%, …) are
conservative but not a formal specification of "correct".

---

## Approval, backup, recovery and audit

* **Risk gate** (`risk.py`): score = failure-type base risk + classifier
  uncertainty + fraction of data touched + unvalidated-fix penalty.
  `PROCEED` (< 0.25) auto-applies, `REVIEW` (< 0.50) queues for a human,
  `HOLD` (≥ 0.50) requires `python guard.py approve <id> --force` after
  inspecting `runs/<id>/repair.py`.
* **Approval queue**: REVIEW/HOLD fixes wait in `data/pending/<id>.json`.
  Nothing is applied until `approve` runs. `guard.py pending` lists them.
* **Backup & recovery**: `apply` copies the live input to
  `data/backup/orders_<id>.csv` *before* replacing it, then re-runs the
  pipeline to confirm recovery. Rollback = copy the backup file back.
* **Audit**: every stage (`WATCH`, `CLASSIFY`, `REPRODUCE`, `DIAGNOSE`, `FIX`,
  `VALIDATE`, `RISK`, `APPROVAL`, `APPLY`, `RECOVER`, `ESCALATE`) is appended
  to `logs/audit.jsonl` (machine-readable) and rendered into
  `reports/incident_<id>.md` (human-readable), including the repair source and
  — when Granite ran — its full proposal.
* **Failure behaviour**: if the repair script crashes, or fails validation,
  the live file is untouched, nothing is applied, and the incident is
  escalated with the sandbox output attached.

---

## Tests

```bash
python -m pytest test_pipelineguard.py -q     # or: python test_pipelineguard.py
```

44 tests, all passing on the development machine. They need **no model
download, no Docker and no s390x hardware**: a local OpenAI-compatible mock
server (stdlib `http.server`) stands in for `llama-server`, so the real HTTP,
JSON-parsing, allowlist and fallback code paths are exercised end to end
through the real `guard.py` flow. Scenarios covered: valid proposal; malformed
JSON; empty completion; timeout (and that `GRANITE_TIMEOUT` is honoured);
connection refused; low confidence flagging; disallowed strategy rejection;
`escalate_to_human` blocking application; missing/wrong-typed proposal fields;
`GRANITE_ENABLED` unset/`0` disabling (no network attempt); repair runtime
error leaving live data untouched; sandbox gate integrity (model text never
enters executed code); report/audit source statements; and the unchanged
validation/risk/approval gates, including the pending-queue → approve →
backup → recover flow.

---

## Current status & limitations (honest list)

Implemented and verified by tests:
* The full Granite integration code path (prompt → HTTP → JSON → allowlist →
  template → sandbox → gates) against a **mocked** OpenAI-compatible server.
* Fallback behaviour for every failure mode of the model (down, slow, garbage,
  malicious/off-allowlist strategy, low confidence).

Verified end-to-end on this machine (no Granite): all four repairable fault
types recover, sandbox process-fallback works on Windows/Linux alike.

**Not yet done / known limits:**
* Never run against a **real Granite model on real s390x hardware** — the
  model-quality aspects (does Granite actually pick the right strategy, is the
  JSON clean, how slow is it on 3 vCPU) are unmeasured. The safety design does
  not depend on this: a wrong or missing proposal is rejected or ignored.
* `snapml_adapter.py` is a shim that uses Snap ML only if the package *and* a
  trained Snap ML model are present; otherwise the sklearn classifier is used
  (the tested default).
* The repair allowlist covers the four demo fault classes; new failure classes
  need a new template + allowlist entry (deliberately — no free-form repair).
* The sandbox without Docker is not a security boundary (see above).
* Windows console output may mangle box-drawing characters on cp1252 code
  pages (cosmetic; LinuxONE runs UTF-8).
