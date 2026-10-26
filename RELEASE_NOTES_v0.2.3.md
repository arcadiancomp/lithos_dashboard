# Lithos Dashboard v0.2.3

## Fixed

- Monthly income projections now support payout histories exceeding
  the Lithos API's 500-record page limit.
- CLI and browser dashboards retrieve the complete paginated ledger.
- Adaptive page sizing preserves API response-size safeguards.
- Missing, duplicate, or inconsistent payout pages are rejected
  rather than silently producing incorrect earnings estimates.
- Open claims and bounties are not duplicated across payment pages.

## Validation

- 18 regression tests passing, including 10 new pagination tests.
- Live validation against Lithos Client 1.0.6.
- Successfully processed 548 confirmed payouts.
- No Ergo, Lithos, SOAT, or database changes required.

The monthly income estimation algorithm is unchanged.
