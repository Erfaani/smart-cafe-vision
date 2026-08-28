# Privacy

The product measures *how busy a room is* and *how long people stay*. It does
not identify anyone, and it is built so that identifying someone would require
adding code that does not exist rather than flipping a setting.

---

## What is stored

| Data | Stored | Notes |
|---|---|---|
| Anonymous track number | yes, temporarily | e.g. `#27`. Meaningless outside one camera session; reused freely |
| Entry and exit timestamps | yes | The basis of every stay-time figure |
| Bounding box geometry | yes, in the event log | Pixel coordinates, no image content |
| Camera id, zone id, table id | yes | Which camera and area produced an observation |
| Aggregated counts | yes | Occupancy, averages, peak hours |
| **Faces** | **no** | Never detected as identity, never encoded |
| **Face embeddings / biometric templates** | **no** | Never computed |
| **Names, phone numbers, emails of customers** | **no** | Customers are never records |
| **Video footage** | **no** | Frames are processed in memory and discarded |
| **Still images or crops of people** | **no** | Not written to disk or to the event bus |

Staff accounts are the only people the system knows by name — they log in.

## How that is enforced

Three mechanisms, not one:

1. **The event contract rejects it.** `scv_contracts` refuses to construct an
   event whose payload contains keys like `face`, `embedding`, `identity`,
   `name`, `image` or `crop`. This raises at construction time, in the worker,
   before anything is published.

2. **Tests assert it.** `apps/events/tests/test_contract.py` fails the build if
   the guard is weakened. The privacy promise is checked by CI, not by memory.

3. **The public display has its own serializer.** `PublicCafeSerializer` lists
   the exact fields the café TV may receive. It is a separate class, not a field
   subset of the admin serializer, so a future field added to the café model
   cannot silently widen what the public page exposes. A test asserts the exact
   field set.

## Video handling

Frames are read from RTSP, processed in memory, and discarded. Nothing is
written to disk.

`ALLOW_VIDEO_RECORDING` exists as an explicit administrator opt-in for
situations where a venue has a legitimate, documented operational reason. It
defaults to off, and turning it on changes the legal picture for the venue
substantially — that is the venue's decision to make and to document.

## Retention

- Raw events: bounded by `EVENT_STREAM_MAXLEN` in Redis (default 100 000)
  while in transit, and by `EVENT_RETENTION_DAYS` once stored in
  `TrackingEvent` (default 90 days; 0 disables pruning) — a Celery beat task,
  `apps.events.prune_old_events`, deletes anything older on a schedule
  (`EVENT_PRUNE_INTERVAL_SECONDS`, default daily). Safe to prune: every
  durable figure the product reports — customer sessions, table sessions,
  daily analytics rollups — is computed and stored at ingest time, not read
  from raw events later. Pruning only gives up the ability to *recompute* a
  projection for a given day if a bug is ever found in one, not any figure a
  café can currently see.
- Customer sessions, table sessions, and daily analytics rollups: retained
  indefinitely by default — these are small, aggregated records (durations
  and counts), not raw tracking data

## Customer-facing notice

Every café record carries a privacy notice in English and Persian, editable by
the owner and surfaced on the public display and on the sign-in page. The
default text:

> This café uses anonymous camera analytics to measure how busy it is. No faces
> are recognised, no identities are stored, and no footage is kept.

Local law usually also requires physical signage at the entrance. That is the
venue's responsibility; the software cannot discharge it.

## GDPR notes (European deployments)

This is engineering guidance, not legal advice. A venue should confirm with its
own counsel.

- **Personal data.** Anonymous counting with no identifiers and no retained
  imagery is a strong position, but "anonymous" is a legal conclusion, not a
  technical one. A venue with very few customers should consider whether an
  individual could be singled out from the data in context.
- **Lawful basis.** Legitimate interest is the usual basis for occupancy
  analytics. A legitimate interests assessment should be documented.
- **Transparency.** Signage at the entrance plus the in-app notice.
- **Data minimisation.** The system stores durations and counts, not people.
  This is the strongest argument in a venue's favour.
- **Data subject rights.** With no identifiers, there is generally nothing to
  access, rectify or erase for an individual — but the venue must be able to
  explain that clearly rather than merely assert it.
- **DPIA.** Camera-based analytics in a public-facing space usually warrants a
  Data Protection Impact Assessment. The architecture document and this page are
  intended to be usable as inputs to one.
- **Processor relationship.** All processing happens on the venue's own
  hardware. There is no cloud processor to name in a record of processing
  activities.

## What would change this

Adding face recognition, re-identification across cameras, or footage retention
would move this system from *anonymous analytics* to *surveillance*, with an
entirely different legal and ethical footing. None of it is on the roadmap. If a
deployment ever needs it, it should be treated as a different product with its
own assessment — not as a configuration option.
