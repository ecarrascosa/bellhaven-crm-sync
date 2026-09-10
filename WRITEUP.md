# Writeup

## Matching Approach

The matcher uses a multi-signal scoring system to link each website community to its CRM account:

1. **City + state filtering** narrows candidates to accounts in the same location.
2. **Street address comparison** uses normalized abbreviations (Blvd↔Boulevard, St↔Street, NW↔Northwest, etc.) to avoid false positives from formatting differences.
3. **Fuzzy name scoring** strips common facility words (senior, living, care, center, manor, etc.) and compares the distinctive remaining words. This catches rebrands like "Chesterton Senior Commons" → "Bellhaven of Chesterton" — both reduce to "chesterton" and share a city match.
4. **ZIP code** provides a tiebreaker and a fallback for edge cases where city names might not match exactly.

Candidates are scored and ranked. The top match is classified into one of six categories (MATCH_OK, MATCH_FIX, MATCH_FIX_CHOW, NEW_ACCOUNT, CRM_ONLY, DUPLICATE) based on what corrections are needed. The CHOW logic checks `lifetime_revenue` and `outstanding_ar` before deciding whether to re-parent directly or preserve the old account for billing.

I also added guards against false duplicate detection: accounts involved in CHOW relationships (old account → new account) and accounts already marked inactive are excluded from duplicate matching, since those pairs are intentional.

## How I Used AI Tools

I used an AI coding assistant (OpenClaw) throughout the project. It helped with:

- **Exploring the API and website structure** — fetching pages, parsing the OpenAPI spec, and understanding the data shape before writing any code.
- **Scaffolding** — generating the initial scraper, matcher, and Flask review app, which I then iterated on.
- **Debugging matching edge cases** — when the matcher was flagging street abbreviation differences as real changes, or when CHOW-created accounts were incorrectly detected as duplicates, the AI helped identify and fix those issues.
- **The review app UI** — the single-page HTML/JS frontend was largely AI-generated, with tweaks for layout and filtering.

The core matching logic, classification decisions, and CHOW implementation were designed collaboratively — I described what each case should do and validated the results against the actual CRM data.

## What I'd Build Next

- **Confidence scores** — surface a high/medium/low confidence level on each match so reviewers can prioritize uncertain ones and fast-track obvious corrections.
- **Notifications** — Slack or email alerts when the daily pipeline generates new proposals, so the review queue doesn't sit unattended.
- **Audit log** — record before/after snapshots of every CRM change with timestamps and who approved it, for accountability and rollback.
- **Address validation** — use a geocoding API to verify addresses and catch typos or outdated entries that string comparison would miss.
- **Multi-care-type support** — some facilities (like Findlay) offer multiple care types. The CRM only stores one `care_type` value. I'd propose a schema change or a convention to handle this properly.
- **Automated monitoring** — track match rates over time. If the percentage of NEW_ACCOUNT or CRM_ONLY proposals spikes, that's a signal of a major ownership change worth flagging proactively.
