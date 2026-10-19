"""The benchmark lab: re-create incidents by running the real pipelines against injected faults.

Each scenario runs the actual pipeline code (hcip, the clinical ETL) on corrupted inputs, then the
platform's collector records the resulting evidence exactly as an on-call engineer would find it.
Scenario names never reach the evidence: incident ids are opaque, release ids are neutral, and
temporary paths are rewritten (see `redact` and tests/test_benchmark_integrity.py). Ground-truth labels
live in benchmark/labels.yml, which no investigator can read.
"""
