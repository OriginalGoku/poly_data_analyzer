# Improve Data Download Initial Idea

## Goal

Recover complete trade histories for games currently saved as truncated Data API fallback files by hydrating directly from Polygon on-chain `OrderFilled` events.

## Plan Of Action

1. **Confirm Current Failure Mode**
   - Pick 2-3 truncated games:
     - one NBA high-volume game
     - one MLB game
     - one NHL game
   - Record current file stats: `trade_count`, first/last trade timestamp, pregame trade count, notional, and source fields.
   - Confirm Goldsky returns zero and Data API caps at 4000 for these samples.

2. **Identify Required On-Chain Contracts**
   - Start with current V2 contracts:
     - CTF Exchange: `0xE111180000d2663C0091e4f400237545B87B996B`
     - Neg Risk CTF Exchange: `0xe2222d279d744050d28e00520010520000310F59`
   - Verify whether May 2026 sports markets use one or both.
   - Keep legacy contracts out of scope until the modern window works.

3. **Build A One-Game Prototype**
   - Input: `date`, `match_id`, `token_ids`, `gamma_start_time`, `gamma_closed_time`.
   - Convert the relevant time window to Polygon block ranges.
   - Fetch `OrderFilled` logs from both V2 contracts.
   - Decode logs with ABI.
   - Filter decoded events where `makerAssetId` or `takerAssetId` matches one of the game token IDs.
   - Normalize into the existing trade schema:
     - `fill_id`
     - `side`
     - `asset`
     - `price`
     - `size`
     - `timestamp`
     - `transactionHash`
     - `maker`
     - `taker`

4. **Validate Prototype Against Known-Good Games**
   - Run direct-onchain fetch for a game already collected from Goldsky.
   - Compare:
     - trade count
     - first/last timestamp
     - total notional
     - token-level price path
     - maker/taker presence
   - Fix decoding and dedup logic until direct-onchain matches Goldsky closely.

5. **Validate Prototype Against Truncated Games**
   - Run it on the sample truncated games.
   - Success criteria:
     - recovered trade count is greater than 4000 for capped files
     - first trade moves earlier than the Data API first trade
     - pregame trades are recovered where expected
     - notional is plausible and higher than capped fallback
     - prices stay in valid `0..1` range

6. **Add Downloader Source Module**
   - Add a module like `src/poly_data_downloader/onchain.py`.
   - Responsibilities:
     - block timestamp lookup
     - chunked `eth_getLogs`
     - `OrderFilled` decoding
     - token filtering
     - trade normalization
   - Keep it isolated from `pull.py` initially so it is easy to test.

7. **Integrate Into Rehydration**
   - Update `rehydrate_entry()` flow:
     - try Goldsky
     - if Goldsky returns zero, try direct on-chain
     - if direct on-chain succeeds, write source as `direct_onchain`
   - Preserve existing file schema.
   - Set:
     - `source: "direct_onchain"`
     - `history_source: "direct_onchain"`
     - `history_truncated: false`
     - `history_cap: null`

8. **Optionally Integrate Into Pull**
   - After rehydration works, update `pull.py`:
     - Goldsky first
     - direct-onchain second
     - Data API fallback last
   - This prevents creating new truncated files going forward.

9. **Add Tests**
   - Unit tests for:
     - event decoding
     - trade normalization
     - token filtering
     - dedup by `tx_hash + log_index`
   - Integration-style tests with mocked RPC responses.
   - Regression test that `rehydrate` replaces a truncated Data API file with `direct_onchain`.

10. **Run Corpus Rehydration**
    - Run direct-onchain rehydrate over `2026-04-10` to `2026-05-16`.
    - Generate before/after report:
      - candidates
      - successfully rehydrated
      - still truncated
      - source breakdown
      - recovered trade-count delta
      - recovered pregame trade-count delta

11. **Update Analyzer Quality Handling**
    - Keep `history_truncated` visible in the dashboard.
    - Add or plan a filter for:
      - exclude truncated histories
      - source = `goldsky`, `direct_onchain`, `data_api`
    - Make backtests exclude `history_truncated == true` by default.

## Recommended Milestone

Start with a narrow proof:

```text
Direct-onchain hydrate one truncated NBA game and one known-good Goldsky game.
```

If those match or recover correctly, the rest is straightforward engineering.
