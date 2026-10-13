# ADR-2: Brute-force vector scan until one million segments

Status: accepted, 2026-10-13.

## Context

Each volume stores segment vectors as float16 SQLite blobs.
An approximate nearest-neighbor index would add persistence, rebuild and tuning work before the expected index size needs it.
The timing comment in `helper/omafindd/search.py` records a 500,000 by 768 scan on the host:
750 ms when converting float16 blocks, and 45 ms with resident float32 vectors.

## Decision

Keep a brute-force numpy scan until the index exceeds one million segments.
Store vectors as float16 blobs and cache decoded float32 vectors for repeated queries.
Load offline volumes on demand and include them in the scan.

## Consequences

The scan is exact and needs no separate vector index to recover or rebuild.
Resident float32 vectors use more memory than their stored float16 blobs.
Revisit the scan strategy above one million segments using measured latency and memory use.
The host timing describes the vector scan, not end-to-end query latency.
