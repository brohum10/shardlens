# ShardLens

[![Checks](https://github.com/brohum10/shardlens/actions/workflows/ci.yml/badge.svg)](https://github.com/brohum10/shardlens/actions/workflows/ci.yml)

**Preview the data movement before changing a cluster.**

ShardLens is a dependency-free Python tool that compares replica placement before and after a topology change. Add a node, retire a node, or change relative capacity weights; get a deterministic JSON report of primary changes, new replica copies, estimated bytes transferred, and final per-node load.

It is an **offline planner**, not a distributed database or a migration executor. It never contacts servers or moves data.

## Run it

Requires Python 3.11+; no account or API key.

```sh
python3 shardlens.py examples/scale-out.json
python3 -m unittest discover -s tests -v
```

Optional installation:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/shardlens examples/scale-out.json
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\shardlens.exe`.

## Model

Input contains `before` and `after` node arrays, an `objects` array with unique keys and nonnegative integer byte sizes, and optional `replicas` (default 1). Node weights default to 1 and must lie within [1e-12, 1e12]. Replication count must fit both topologies. Unknown fields and duplicate JSON fields are rejected; invalid input exits 2 without a partial report.

Weights represent **relative selection probability**, not hard storage limits. With one replica, weights 1:3 aim for roughly 25%:75% of keys over a large well-distributed sample. Unequal object sizes may still create byte imbalance. With multiple replicas, weighted selection is without replacement, so replica shares are not simply proportional to weights.

## Algorithm and architecture

1. Frame each `(object key, node ID)` pair as compact ASCII JSON and hash it with SHA-256.
2. Convert 52 digest bits to an open-interval uniform value `u`.
3. Rank nodes by `-log(u) / weight`, smallest first; node ID breaks equal-score ties.
4. Select the first R unique owners. The first owner is the primary.
5. Compare old and new owner sets: only newly added replicas contribute to copy bytes.

This weighted rendezvous scheme uses an exponential race: increasing a node's weight makes it more likely to win. Existing pair scores do not change when an unrelated node joins or leaves, limiting placement disruption. Unlike modulo hashing, adding a node does not renumber every bucket.

The first owner can change while all replicas remain present; that is a **primary change without a copy**. Reports preserve this distinction. Owners are ordered, changes are sorted by key, and load entries are sorted by node ID so input reordering does not change output.

For K objects, N nodes, and R replicas, scoring requires O(KN) hashes; top-R selection adds O(KN log R) work for R > 1. Inputs and detailed changes remain in memory. No placement table or virtual-node ring is stored. Floating-point logarithms can differ at extreme near-ties across math libraries; this is a Python planner, not a cross-language consensus primitive. Treat algorithm version and framing as part of the placement contract.

## Report semantics and safety

- `estimated_copy_bytes` sums object size once for each new destination replica.
- `copy_to` and `remove_from` describe a desired final-state difference, **not an execution sequence**.
- Copies assume a readable old replica exists. A removed node may need to remain online as a source; a complete topology replacement is not proof of recoverability after a failure.
- No rack/zone anti-affinity, quorum protocol, checksum validation, synchronization, bandwidth scheduling, free-space checks, TTLs, or concurrent-write coordination is implemented.
- Never delete old replicas based on this report alone. A real migration needs verified copies, cutover coordination, and recovery procedures.
- Object keys may contain sensitive names. The tool runs locally, but its report repeats keys; sanitize before sharing.

## Verification

The test suite covers order independence, distinct replicas, join/leave minimal movement, retained replica order, weighted selection, monotonic weight increases, invalid topologies, Unicode keys, byte accounting, primary-only changes, deterministic output, and CLI failure behavior. A seeded topology check varies weights and node order; a 10,000-key distribution check exercises the 1:3 weighting case. These tests validate this model, not production availability.

GitHub Actions runs Python 3.11 and 3.13 and tests the installed command. No throughput or production savings claim is made.

## Future extensions

- Failure-domain constraints and explicit infeasible-placement reports.
- Streaming summary mode for large object inventories.
- Capacity limits and a bandwidth-aware copy scheduler, separate from placement.
- Versioned golden vectors for cross-language compatibility.

Built as a learning and portfolio project with AI assistance. MIT licensed.
