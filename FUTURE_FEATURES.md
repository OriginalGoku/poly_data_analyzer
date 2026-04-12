# Future Features

## High

### Multi-game comparison view
**Date:** 09/04/2026
Support viewing multiple games side-by-side or overlaid for cross-game pattern analysis.

### NHL and MLB sport support
**Date:** 09/04/2026
Extend the visualizer beyond NBA. NHL lacks wall-clock event timestamps; MLB has only scoring plays. Each sport needs adapted event overlay logic.

## Medium

### Bid/ask spread approximation
**Date:** 09/04/2026
Approximate spread from BUY vs SELL trade prices within time windows. Current data has executed fills only (no order book), so any spread visualization would be an estimate.

### Pre-game odds drift analysis
**Date:** 09/04/2026
Dedicated view or summary statistics for how the market moved between market open and tip-off, using `price_checkpoints` data.

### Sensitivity cache invalidation
**Date:** 11/04/2026
Include a settings hash in the sensitivity cache filename so changes to window size or lead-bin thresholds automatically invalidate stale per-game sensitivity rows.

## Low

### Data quality filtering controls
**Date:** 09/04/2026
UI controls to filter by price quality (exact/inferred), data source (goldsky/data_api), or exclude truncated histories.
