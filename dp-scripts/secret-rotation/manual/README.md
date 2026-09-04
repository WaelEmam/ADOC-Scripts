# Manual Workflow

Manual secret rotation where you provide credentials directly.

## Quick Start

```bash
# Dry-run to preview changes
./rotate-and-restart.sh --dry-run \
  fijiusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA_NEW_KEY' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=new_secret_value'

# Execute the rotation
./rotate-and-restart.sh \
  fijiusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA_NEW_KEY' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=new_secret_value'
```

## What It Does

1. Shows current secret values (pause for review)
2. Updates Kubernetes secret with new credentials
3. Restarts affected deployments
4. Waits for all pods to be ready

## Script

- **rotate-and-restart.sh** - Complete rotation workflow with manual credential entry

## When to Use

- You don't have OpenBao access
- You need to manually enter or paste credentials
- One-time rotations
- Testing or emergency scenarios

## Prerequisites

- kubectl configured for target cluster
- jq installed (`brew install jq` on macOS)
- New AWS credentials ready to paste

See [main README](../README.md) for full documentation.
