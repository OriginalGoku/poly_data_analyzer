#!/usr/bin/env bash
# Archive the pre-change baseline CSVs before deploying the tip-off stop-loss
# EV changes. Copies dataset.csv + tipoff_band_outcome_summary.csv from a
# baseline analysis run into analysis_outputs/baseline_pre_tipoff_stoploss/.
#
# Usage:
#   scripts/archive_baseline_pre_tipoff_stoploss.sh <baseline_run_dir>
#
# <baseline_run_dir> is a prior `analysis_nba_open_vs_tipoff.py` output dir,
# e.g. analysis_outputs/nba_open_tipoff_20260411_132745
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <baseline_run_dir>" >&2
  exit 2
fi

SRC="$1"
DEST="analysis_outputs/baseline_pre_tipoff_stoploss"

for f in dataset.csv tipoff_band_outcome_summary.csv; do
  if [[ ! -f "$SRC/$f" ]]; then
    echo "error: $SRC/$f not found" >&2
    exit 1
  fi
done

mkdir -p "$DEST"
cp "$SRC/dataset.csv" "$DEST/dataset.csv"
cp "$SRC/tipoff_band_outcome_summary.csv" "$DEST/tipoff_band_outcome_summary.csv"
echo "Archived baseline CSVs from $SRC -> $DEST"
