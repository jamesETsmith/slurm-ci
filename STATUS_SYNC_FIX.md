# Status Sync Issue - Fixed

## Problem

Jobs that had completed (with `[runtime.end]` section in their TOML files) were still showing as "running" on the dashboard.

## Root Cause

There was a bug in `src/slurm_ci/status_watcher.py` (lines 157-168) where the sync logic compared file modification times incorrectly:

```python
# BUGGY CODE (before fix):
existing_mtime = os.path.getmtime(existing_job.status_file_path)
current_mtime = os.path.getmtime(file_path)

if current_mtime <= existing_mtime:
    should_update = False
```

The issue: `existing_job.status_file_path` and `file_path` were the **same file**, so their modification times were always equal. This meant the sync would always skip updates for existing jobs, even when the job status changed from "running" to "completed".

## Solution

### Immediate Fix (for you)
Ran `slurm-ci db-soft-reset` to delete and recreate the database with fresh data from all status files.

### Permanent Fix (code change)
Modified `status_watcher.py` to compare actual status values instead of file modification times:

```python
# FIXED CODE:
should_update = (
    existing_job.status != job_info["status"]
    or existing_job.exit_code != job_info["exit_code"]
    or existing_job.end_time != job_info["end_time"]
)
```

Now the sync detects when a job's status changes (e.g., from "running" to "completed") by comparing the actual data values.

## Prevention

### Option 1: Run Status Watcher Daemon (Recommended)
Start the status watcher daemon to automatically sync changes:
```bash
slurm-ci db-watch
```

This will continuously monitor the status directory and sync changes to the database every 30 seconds.

### Option 2: Manual Sync
If you don't want to run the daemon, manually sync when you notice stale data:
```bash
slurm-ci db-sync
```

### Option 3: Soft Reset (if sync doesn't work)
If jobs are still showing incorrect status:
```bash
slurm-ci db-soft-reset
```

This deletes the database and rebuilds it from all status files (safe operation).

## Verification

A test was added in `tests/test_status_sync_fix.py` to ensure this bug doesn't reoccur. Run it with:
```bash
pytest tests/test_status_sync_fix.py -v
```

## Files Modified
- `src/slurm_ci/status_watcher.py` - Fixed sync logic
- `tests/test_status_sync_fix.py` - Added regression test

## Date
October 25, 2025

