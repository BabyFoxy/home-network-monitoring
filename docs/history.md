# Project History

This is a short orientation layer, not a full git log. The repository history
is still the source of truth, but these milestones show how the stack evolved.

## Milestones

| Commit | Change | Why it matters |
|---|---|---|
| `25d102a` | Added the daily gaming email report | Introduced the report pipeline that now drives the cron job |
| `b3ef0d1` | Fixed timezone handling for the report | Locked the report output to `Australia/Sydney` |
| `6d2520f` | Added the recovery runbook | Gave the project a recovery path instead of just startup notes |
| `68b69f2` | Updated deployment and recovery docs | Brought the operator docs back in sync with the live stack |
| `b677c4b` | Changed the report window to rolling 24h | Matched the report to the actual send time instead of the calendar day |
| `1fe356a` | Switched the device filter to exclusion mode | Kept the report centred on the non-Fox devices without constant manual edits |
| `f82d2b3` | Defaulted the dashboard device filter to All | Made the dashboard easier to use for ad hoc inspection |
| `4cc3850` | Showed all gaming DNS queries, allowed and blocked | Made the evidence panel match the real question being asked |
| `92d29eb` | Fixed STATUS values in the email report | Removed misleading `ALLOWED` labels in the report output |
| `ff97b90` | Refreshed the daily report runbook | Brought the runbook into line with the current architecture |

## Read this as

- The stack started as a DNS log visualisation project and grew into a
  monitoring plus reporting setup.
- The big stability wins were timezone handling, device filtering, and recovery
  documentation.
- When in doubt, trust the current docs and the live compose files over older
  handoff material.
