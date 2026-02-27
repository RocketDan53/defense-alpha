#!/bin/bash
set -e
cd "$(dirname "$0")/.."
echo "=== Entity Snapshot $(date) ==="
python scripts/snapshot_entities.py
echo "=== Complete ==="
