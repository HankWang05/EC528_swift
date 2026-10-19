# OpenStack Swift ring-builder save experiments

These experiments test the **actual OpenStack Swift fork in `EC528_swift`**.
The fix changes `RingBuilder.save()` in `swift/common/ring/builder.py`: it writes
and syncs a temporary file before replacing the existing builder, then syncs the
containing directory. The tests below provide distinct evidence for that change.

| Experiment | Claim or evidence supported | Checks |
| --- | --- | --- |
| [0: unit suite](exp0_unittests.py) | Baseline and regression evidence for upstream Swift | Runs existing unit tests and reports failures, errors, skips, and elapsed time. |
| [1: partial serialization](exp1_run_partial_dump_test.py) | An interrupted serialization should preserve the previous builder | Runs the existing partial-pickle regression test. |
| [2: process interruption](exp2_interrupted_save.py) | Killing a writer leaves the complete old or new builder, depending on whether replacement occurred | Three controlled `SIGKILL` scenarios; reload, placement, and subsequent-save checks. |
| [3: handled failures](exp3_save_failure_cleanup.py) | Handled pre-replacement errors preserve the old builder, propagate the error, and clean up the attempt | Four injected failure points, plus failed-first-save ID recovery. |
| [4: successful-save protocol](exp4_save_durability_order.py) | A successful update follows the temporary-file durability sequence | Observes real serialization, flush, sync, close, and rename operations and validates the installed state. |

## Setup and running

Use the prepared Linux environment. From the fork root:

```bash
cd /path/to/EC528_swift
source .venv/bin/activate
python3 experiments/exp2_interrupted_save.py
echo "exit=$?"
```

On the team's `SwiftBugFix` Lightsail instance, connect using SSH and use the
existing checkout path:

```bash
cd /home/ubuntu/EC528_swift
source .venv/bin/activate
python3 experiments/exp2_interrupted_save.py
python3 experiments/exp3_save_failure_cleanup.py
python3 experiments/exp4_save_durability_order.py
```

If the checkout is at `/opt/ec528-swift`, as in experiment 0's opening example,
use that directory instead. Verify the checkout contains all new scripts and
`atomic_save_support.py`. Run each separately with `echo "exit=$?"` when
recording an individual result; the shell does not stop the sequence above
just because an earlier experiment fails.

The existing `setup.sh` prepares dependencies and scratch storage on a clean
Linux machine. It changes system packages and mounts; it is not an experiment.
No running Swift cluster or production builder file is needed for experiments
2–4: they create populated builders in temporary directories.

## Experiment 0: upstream regression baseline

**Claim supported:** comparing the upstream unit suite before and after the
patch provides evidence that the change has not introduced new test failures.
A single run alone does not establish a before/after comparison.

```bash
python3 experiments/exp0_unittests.py \
    --results-json baseline.json --timeout 1800
```

The runner discovers a Swift checkout, checks the environment, and runs its unit
suite. Record the revision and named failures on both versions. `--quick`
restricts execution to the ring tests and is only a smoke test, not the full
baseline. Runtime is bounded by the requested timeout (30 minutes by default).

**Limits:** unit-suite results do not establish complete system correctness or
measure the patch's performance cost. This existing runner is unchanged. Its
result handling can misclassify an entirely failing suite as aborted collection;
inspect the pytest output as well as the final label. The existing mocked
`test_save` also needs adaptation to the new implementation, so do not assume
that the patched suite is already green.

## Experiment 1: partial-serialization regression

**Claim tested:** if serialization writes only part of a builder and then raises
an error, the previous builder file should remain byte-identical and loadable.

```bash
python3 experiments/exp1_run_partial_dump_test.py
```

Runs exactly
`TestRingBuilder.test_save_partial_dump_does_nothing` from
`test/unit/common/ring/test_builder.py`. The test first saves a valid builder,
then patches `pickle.dump` to write half its payload and raise `OSError`. It
checks the saved bytes and loads the builder again. This normally takes seconds.

**Expected comparison:** direct overwriting should fail preservation; an atomic
save should preserve the file. However, the existing test's final dictionary
comparison can fail because loading adds device replication fields absent from
the original fixture. The runner's diagnosis distinguishes that mismatch from
changed file bytes. Experiments 0 and 1 and that upstream test are retained
unchanged; a failing final comparison must not be reported as proof that the
atomic-save patch corrupted the file.

**Limits:** the failure is injected, not an actual killed process. It does not
verify syncing, concurrent writers, composite builders, or power-loss survival.

## Experiment 2: process interruption before and after replacement

**Claim tested:** until replacement, an interrupted save preserves the previous
valid builder. After replacement, a process crash leaves the complete new
builder available to the next reader.

```bash
python3 experiments/exp2_interrupted_save.py
```

Three tests run saves of a changed builder in child processes. Each child pauses
at a controlled point and is killed by the parent with `SIGKILL`:

1. Halfway through serialization: the original bytes and loaded state survive.
2. Immediately before rename: the original bytes and loaded state survive.
3. Immediately after rename: the complete updated state loads successfully.

The checks also compare individual partition-to-device lookups. For kills
before replacement, a later save must work despite any temporary file left
behind. A passing run reports **3 tests**, `OK`, and `RESULT: PASS`.

**Limits:** a hard kill cannot run exception cleanup, so leftover temporary
files are permitted. The OS continues running; the post-rename test does not
establish durability after power loss before the directory sync. These are
individual-builder lookups, not composite-ring CLI lookups.

## Experiment 3: handled failure preservation and cleanup

**Claim tested:** errors handled before replacement leave the previous builder
unchanged and loadable, propagate to the caller, and remove the temporary file
created by that attempt. A failed first save resets its unpersisted builder ID.

```bash
python3 experiments/exp3_save_failure_cleanup.py
```

Five tests cover:

1. Serialization writing half the payload and raising an error.
2. The explicit file flush raising an error.
3. File `fsync` raising an error.
4. Replacement raising an error, including Swift's rename retry.
5. A first save failing before it can persist its newly assigned ID.

Each injected failure must actually be reached and raise the expected error.
Existing-builder checks compare the original bytes, loaded state, and
partition-device lookups, and require no extra files after cleanup. The
first-save check requires no destination or temporary file and a restored
unpersisted ID. A passing run reports **5 tests**, `OK`, and `RESULT: PASS`.

**Limits:** this is caught-exception cleanup on a writable filesystem. It does
not require cleanup after `SIGKILL`, guarantee that unlink can never fail, or
require rollback after replacement has already occurred.

## Experiment 4: successful-save durability ordering

**Claim tested:** a changed builder is prepared completely before replacement,
and a successful save follows the required file and directory sync sequence.

```bash
python3 experiments/exp4_save_durability_order.py
```

The single test observes real operations while saving a changed builder:

```text
serialize -> flush -> file_fsync -> close -> rename -> directory_fsync
```

It checks that the candidate is a separate file in the destination directory;
the original stays unchanged until replacement; the candidate is complete and
closed before rename; and the synced directory descriptor identifies the actual
parent directory. The resulting builder must match the intended new state,
load successfully, retain its partition-device mappings, and leave no file at
the temporary name. A passing run reports **1 test**, `OK`, and `RESULT: PASS`.

**Limits:** observing successful sync calls is not a machine power-loss test or
a guarantee about storage hardware. Swift's directory-sync helper can log some
errors instead of propagating them; this experiment requires the successful
sync to be observed on the test filesystem.

## Source selection, output, and interpretation

Experiments 2–4 import the selected **real** Swift checkout and print its source
path and revision. They accept `--swift-src PATH`, `SWIFT_SRC`, `--timeout`
(default 90 seconds), and `--results-json PATH`. The default source is the fork
containing the scripts. `atomic_save_support.py` provides their shared runner
and fixtures; keep it beside all three scripts.

```bash
python3 experiments/exp2_interrupted_save.py \
    --swift-src /path/to/prepared/checkout \
    --results-json exp2-results.json --timeout 90
```

For before/after evidence, run the same scripts against separate prepared
checkouts using `--swift-src`, record both revisions and source modifications,
and inspect the named failures. Do not switch a source checkout during a run.

| Exit code | Meaning |
| --- | --- |
| `0` | The selected checks ran and passed. |
| `1` | A check failed or errored; inspect the named test and traceback. |
| `77` | No valid test result was obtained, such as an unsupported host, missing source/dependencies, or timeout. |

The new experiments follow the existing runners' environment, checkout,
dependency, run, and result sections. Their elapsed times describe experiment
runtime, **not a benchmark of atomic-save overhead**. Experiments 2–4 have passed
syntax, command-line, Windows-refusal, and controlled runner checks; actual
Linux Swift results have not yet been collected here. Expected outcomes must
not be presented as measured passes.

## Scope of the claims

The new experiments target only the patched individual `RingBuilder.save()`.
They do not establish composite-builder atomicity, same-process concurrent-save
isolation, actual power-loss recovery, or running-cluster client behavior. The
current patch does not change the composite save method or make PID-only
temporary names unique across threads. Those broader proposal claims need
separate implementation and evidence.
