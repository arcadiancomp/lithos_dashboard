# Lithos Dashboard v0.2.2

Bug-fix release: restores Ergo network adoption metrics when the local Ergo
node returns large header or block-transaction responses.

## Fixed

- Page the rolling 1,000-block header scan using 128-header `chainSlice`
  requests instead of a single oversized `lastHeaders/1000` response.
- Match the actual Ergo node 6.0.6 `chainSlice` height boundaries, using
  `fromHeight=first-1` and `toHeight=last` and checking for missing or
  duplicate canonical heights.
- Permit up to 16 MiB for **complete block transaction responses only**;
  retain the original 2 MiB cap for other Lithos and Ergo API requests.
- Include the request path in oversized-response errors to speed diagnosis.
- Run eight network adoption regression tests in GitHub Actions, including
  paging, height-boundary validation, large blocks, and API size limits.

## Validated

- Eight regression tests passed on the development system.
- Live Ergo 6.0.6 network adoption scan restored the Ergo network hashrate
  and the last-100, last-500, and last-1,000-block adoption statistics.
- No changes to mining, NISP commitments, wallet data, or adoption history.
