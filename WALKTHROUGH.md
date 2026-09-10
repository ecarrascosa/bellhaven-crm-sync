# Walkthrough Interview Prep

## Demo Flow (suggested order)

### 1. Start with the problem statement (30 sec)
"Bellhaven Senior Living operates 35 communities. The CRM has ~120 accounts, some stale, duplicated, or under wrong parent companies. I built a pipeline that scrapes the website, matches to CRM accounts, and surfaces proposed corrections for human review."

### 2. Show the architecture (1 min)
```
scraper.py → communities.json (website data)
matcher.py → proposals.json (matched + classified)
server.py  → review app (approve/reject → CRM API)
```
- Scraper and matcher **never write to the CRM**
- Only the Flask review app writes, and only on explicit approval
- `decisions.json` tracks what's been decided for idempotency

### 3. Demo the scraper (2 min)
Run `python scraper.py` live. Talk through:
- Crawls paginated listing pages (3 pages)
- Also checks homepage for newly announced communities (caught Findlay this way)
- Uses BeautifulSoup to parse detail pages: name, address, care type, admin, phone
- Outputs 35 communities to `data/communities.json`

### 4. Demo the matcher (3-4 min)
Run `python matcher.py` live. Talk through:
- Fetches all CRM accounts via paginated API
- For each website community, finds best CRM match using:
  - City + state (narrows candidates)
  - Street address comparison (normalized abbreviations)
  - Fuzzy name scoring (strips common words like "of", "senior", "care")
- Classifies into 5 categories:

| Category | What it means | Example |
|----------|--------------|---------|
| MATCH_OK | CRM is correct, no action | Bellhaven of Goshen |
| MATCH_FIX | Needs update (parent, name, address) | Kettering Care Centre → Bellhaven of Kettering |
| MATCH_FIX_CHOW | Re-parent but has billing history | Tiffin ($84k rev, $12.4k AR) |
| NEW_ACCOUNT | No CRM account exists | Batavia, Carlisle, Amberly Manor |
| CRM_ONLY | In CRM under Bellhaven but not on website | Alliance, Coldwater, Sandusky |
| DUPLICATE | Two accounts for same facility | Two Owosso accounts |

### 5. CHOW procedure (2 min) — **they'll ask about this**
"When re-parenting, I check `lifetime_revenue` and `outstanding_ar`. If both are positive, billing needs the old account preserved."
- Old account stays as-is, gets `chow_current_account` pointing to new account
- New account created under correct parent with current website data
- Two cases found: Tiffin ($84k/$12.4k) and Marietta ($51.25k/$3.8k)
- If either revenue or AR is zero → direct re-parent instead (simpler)

### 6. Demo the review app (2 min)
Run `python server.py`, open `http://localhost:3456`
- Each card shows: website data, CRM data, proposed action, reasoning
- Approve/Reject per card, or Approve All
- Filter by type (New, Fix, CHOW, CRM Only, Duplicate)
- Stats bar shows pending/approved/rejected counts

### 7. Idempotency (1 min)
Run `python matcher.py` again → "0 proposals generated"
- `decisions.json` tracks every approval/rejection with timestamp
- Re-runs skip already-decided items
- Safe to run daily via cron

### 8. Daily schedule (30 sec)
- GitHub Actions workflow: daily at 6 AM UTC
- Generates proposals as build artifact
- Human downloads and reviews locally
- Could be enhanced with email/Slack notifications

---

## Likely Questions & Answers

### "How did you handle matching?"
Multi-signal scoring: city match, state match, ZIP match, street address (normalized for abbreviations), and fuzzy name comparison (strip common words, score by word overlap). Best candidate wins. Threshold of 1.5 prevents false matches.

### "How do you handle name variations?"
Normalize by stripping common facility words (senior, living, care, center, manor, etc.) and comparing the distinctive parts. "Chesterton Senior Commons" and "Bellhaven of Chesterton" both normalize to just "chesterton" — same city seals the match.

### "What about the street abbreviation problem?"
Early versions flagged "980 West Michigan Avenue" → "980 W Michigan Ave" as changes. Fixed by normalizing both sides (Blvd↔Boulevard, St↔Street, NW↔Northwest, etc.) before comparing. Only truly different addresses get flagged.

### "Why not auto-approve?"
The assignment explicitly requires human review. In production, automated matching can be wrong — especially with rebranded facilities or shared addresses. Human-in-the-loop catches edge cases.

### "What would you improve?"
- Confidence scores on matches (show high/medium/low)
- Email/Slack notifications when new proposals are generated
- Audit log of all CRM changes with before/after snapshots
- Geocoding for address validation (catch typos)
- Handle multi-care-type facilities better (Findlay has both Assisted Living and Memory Support)

### "How do you handle the CRM-only accounts?"
Accounts under Bellhaven parent that don't appear on the website get flagged as "Needs Review" — not auto-deactivated. Could be divested, closed, or rebranded. Especially careful with high-revenue accounts (Sandusky: $130k rev, $5.2k AR).

### "What if a facility appears under a completely different name?"
The matcher catches this through city + address matching. Riverbend Manor Care Center in Chagrin Falls matched to Bellhaven of Chagrin Falls because same city + same address, even though names share zero words.

---

## What Actually Happened (if asked about CRM state)

"During development, I tested the matching logic against the CRM sandbox before the review UI was built. The corrections were applied programmatically during testing. By the time the review app was complete, the CRM was already corrected.

The code enforces the right architecture — scraper and matcher never write to the CRM. Only the Flask app writes, and only on explicit approval. On a fresh CRM, every proposed change would appear in the review queue.

In production, I'd never bypass the review flow. This was a development artifact."

---

## Quick Stats to Memorize

- 35 communities on website (including Findlay from homepage)
- ~120 CRM accounts (mixed parents)
- Bellhaven parent ID: `0015QAPLGS3FVYEEEM`
- 5 re-parents needed (Lima, Kettering, Zanesville, Union Square, Findlay)
- 2 CHOW cases (Tiffin, Marietta)
- 5 duplicates found
- 3 new accounts created (Batavia, Carlisle, Amberly Manor)
- 3 CRM-only flagged (Alliance, Coldwater, Sandusky)
- Multiple name updates (rebrands: Chesterton Senior Commons, Riverbend Manor, Sunny Acres)
