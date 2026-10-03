"""Offline, deterministic replica placement and migration planning."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Node:
    id: str
    weight: float = 1.0


def validate_nodes(nodes: list[Node], replicas: int) -> None:
    if type(replicas) is not int or replicas < 1 or replicas > len(nodes):
        raise ValueError("replicas must be between 1 and the number of nodes")
    ids = set()
    for node in nodes:
        if not isinstance(node.id, str) or not node.id.strip() or node.id in ids:
            raise ValueError("node IDs must be unique nonblank strings")
        if isinstance(node.weight, bool) or not isinstance(node.weight, (float, int)):
            raise ValueError("weights must be finite positive numbers")
        if not math.isfinite(node.weight) or not 1e-12 <= node.weight <= 1e12:
            raise ValueError("weights must be finite and within [1e-12, 1e12]")
        ids.add(node.id)


class Placement:
    def __init__(self, nodes: list[Node], replicas: int = 1):
        validate_nodes(nodes, replicas)
        self.nodes = tuple(nodes)
        self.replicas = replicas

    def owners(self, key: str) -> list[str]:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("keys must be nonblank strings")
        def score(node):
            # JSON framing prevents ambiguous concatenation; no randomized hash().
            message = json.dumps([key, node.id], ensure_ascii=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(message).digest()
            # Use 52 bits to ensure 0 < u < 1 in binary64, including extremes.
            integer = int.from_bytes(digest[:8], "big") >> 12
            u = (integer + 1) / ((1 << 52) + 1)
            return (-math.log(u) / node.weight, node.id)
        return [n.id for n in heapq.nsmallest(self.replicas, self.nodes, key=score)]


def plan(before: list[Node], after: list[Node], objects: list[dict], replicas: int = 1) -> dict:
    old = Placement(before, replicas)
    new = Placement(after, replicas)
    seen = set()
    changes = []
    load = {n.id: {"replicas": 0, "bytes": 0} for n in sorted(after, key=lambda n: n.id)}
    primary_changes = 0
    transferred = 0
    copies = 0
    for item in objects:
        if not isinstance(item, dict) or set(item) != {"key", "bytes"}:
            raise ValueError("each object must contain exactly key and bytes")
        key, size = item["key"], item["bytes"]
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError("object keys must be unique nonblank strings")
        if type(size) is not int or size < 0:
            raise ValueError("object bytes must be a nonnegative integer")
        seen.add(key)
        a, b = old.owners(key), new.owners(key)
        added = [node for node in b if node not in a]
        removed = [node for node in a if node not in b]
        primary_changes += a[0] != b[0]
        transferred += size * len(added)
        copies += len(added)
        for node in b:
            load[node]["replicas"] += 1
            load[node]["bytes"] += size
        if a != b:
            changes.append({"key": key, "bytes": size, "before": a, "after": b,
                            "copy_to": added, "remove_from": removed})
    return {"algorithm": "sha256-weighted-rendezvous-v1", "objects": len(objects),
            "replicas": replicas, "primary_changes": primary_changes,
            "replica_copies": copies, "estimated_copy_bytes": transferred,
            "after_load": load, "changes": sorted(changes, key=lambda c: c["key"])}


def decode_nodes(value):
    if not isinstance(value, list):
        raise ValueError("before and after must be node arrays")
    result = []
    for item in value:
        if not isinstance(item, dict) or not {"id"} <= set(item) <= {"id", "weight"}:
            raise ValueError("each node requires id and optional weight")
        result.append(Node(item["id"], item.get("weight", 1)))
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with before, after, objects, and optional replicas")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        if not isinstance(data, dict) or not {"before", "after", "objects"} <= set(data) <= {"before", "after", "objects", "replicas"}:
            raise ValueError("input requires before, after, objects and optional replicas")
        if not isinstance(data["objects"], list):
            raise ValueError("objects must be an array")
        result = plan(decode_nodes(data["before"]), decode_nodes(data["after"]), data["objects"], data.get("replicas", 1))
    except (OSError, ValueError, OverflowError) as error:
        parser.exit(2, f"shardlens: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
