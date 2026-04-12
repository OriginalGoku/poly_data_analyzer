# Gzip Data File Migration

**Date:** 2026-04-10
**Affects:** All repositories that read from the `poly_data_downloader/data/` folder

---

## What changed

All trades and events data files are now gzip-compressed:

| Before | After |
|---|---|
| `{match_id}_trades.json` | `{match_id}_trades.json.gz` |
| `{match_id}_events.json` | `{match_id}_events.json.gz` |

**Unchanged:** `manifest.json` and `download_log.json` remain plain JSON.

## Why

The `data/` folder was 3.7 GB of JSON. Trades files contain highly repetitive hex strings (asset IDs, wallet addresses, transaction hashes). Gzip reduces total size by ~88% (3.7 GB to ~450 MB) with no data loss.

## How to read the new files

### Python (recommended)

```python
import gzip
import json

# Read a .json.gz file
with gzip.open("data/2026-03-29/nhl-mon-car-2026-03-29_trades.json.gz", "rt", encoding="utf-8") as f:
    data = json.load(f)
```

Key details:
- Use `gzip.open()` with mode `"rt"` (text mode) — no `.decode()` needed
- `json.load()` works identically to plain file reads
- `gzip` is a Python stdlib module — no extra dependencies

### Suffix-based auto-detection (if you need both formats)

```python
import gzip
import json
from pathlib import Path

def read_json(path: Path) -> dict:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)
```

### Shell / jq

```bash
# Read with zcat (macOS/Linux)
zcat data/2026-03-29/nhl-mon-car-2026-03-29_trades.json.gz | jq '.trade_count'

# Or use gzip -dc
gzip -dc data/2026-03-29/nhl-mon-car-2026-03-29_trades.json.gz | jq '.match_id'
```

### Node.js

```javascript
const fs = require('fs');
const zlib = require('zlib');

const compressed = fs.readFileSync('data/2026-03-29/nhl-mon-car-2026-03-29_trades.json.gz');
const data = JSON.parse(zlib.gunzipSync(compressed).toString('utf-8'));
```

### Pandas

```python
import pandas as pd

# Pandas reads .json.gz natively
df = pd.read_json("data/2026-03-29/nhl-mon-car-2026-03-29_trades.json.gz")
```

## File discovery

Update any glob patterns:

| Before | After |
|---|---|
| `data/*/_trades.json` | `data/*/_trades.json.gz` |
| `data/*/_events.json` | `data/*/_events.json.gz` |
| `data/*/manifest.json` | `data/*/manifest.json` (unchanged) |

## Data format

The JSON structure inside the files is **identical** — only the container changed. All fields, nesting, and types are preserved exactly.

## New: download_log.json

A new `download_log.json` file may appear in date directories alongside the manifest. It records unusual events during downloads (Goldsky failures, fallbacks, zero trades, etc.) as structured JSON. It is plain JSON (not gzipped) and is informational only — you can safely ignore it.

## Migration timeline

- All existing data files were migrated on 2026-04-10
- All new downloads produce `.json.gz` files automatically
- No `.json` trades/events files remain in the data folder
