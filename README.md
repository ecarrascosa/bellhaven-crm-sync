# Bellhaven CRM Sync Pipeline

A daily pipeline that scrapes Bellhaven Senior Living's website, matches communities to CRM accounts, and produces a review queue for human-approved corrections.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Scraper    │────▸│   Matcher    │────▸│  Review App  │
│ (website →   │     │ (match +     │     │ (approve →   │
│  JSON)       │     │  classify)   │     │  CRM API)    │
└─────────────┘     └──────────────┘     └──────────────┘
```

**Three components:**

1. **Scraper** (`scraper.py`) — Crawls all paginated community listing pages + detail pages using BeautifulSoup. Extracts name, address, city, state, zip, care offerings, administrator, and phone. Also checks the homepage for newly announced communities not yet in the paginated list.

2. **Matcher** (`matcher.py`) — Loads scraped communities and all CRM accounts. For each website community, finds the best CRM match using city, zip, street address, and fuzzy name comparison. Classifies each into:
   - **MATCH_OK** — no changes needed
   - **MATCH_FIX** — needs corrections (wrong parent, outdated name, wrong care type, etc.)
   - **MATCH_FIX_CHOW** — needs re-parenting but has billing history (revenue > 0 AND outstanding AR > 0), so CHOW procedure applies
   - **NEW_ACCOUNT** — no CRM account exists
   - **CRM_ONLY** — account under Bellhaven parent but not on website (possible divestiture)
   - **DUPLICATE** — multiple CRM accounts for the same facility

3. **Review App** (`server.py`) — Flask web UI where a reviewer sees each proposal with evidence, and can approve or reject. Approved changes write to the CRM API. Nothing writes without approval.

## Running

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run the full pipeline (scrape + match)
python scraper.py
python matcher.py

# Start the review app
python server.py
# Open http://localhost:3456
```

## Idempotency

Decisions are persisted to `data/decisions.json`. Re-running the pipeline skips any community/account that already has a decision, so approving the same proposals twice is impossible.

## CHOW (Change of Ownership) SOP

When a facility needs to move to a different parent company:

- **If** the account has `lifetime_revenue > 0` **AND** `outstanding_ar > 0`:
  - Preserve the old account as-is (billing team needs it)
  - Create a new account under the correct parent
  - Set `chow_current_account` on the old account to the new account's ID

- **Otherwise**: re-parent the existing account directly.

This is implemented in the matcher and executed atomically during approval.

## Duplicate Handling

When two CRM accounts appear to represent the same facility (same city, overlapping name), the lower-confidence match is marked `Inactive` with `duplicate_of_account` pointing to the surviving account.

## Schedule (GitHub Actions)

The pipeline runs daily at 6:00 AM UTC via `.github/workflows/daily-sync.yml`. It generates proposals as build artifacts. A human downloads them and runs the review app locally to approve/reject.

## Key Decisions & Findings

### Matching approach
- **Primary signal**: city + state match narrows candidates, then street address and normalized name scoring rank them.
- **Street normalization**: abbreviation variants (Blvd/Boulevard, St/Street, NW/Northwest) are normalized before comparison to avoid false positives.
- **Name normalization**: strips common words (of, the, at, senior, living, manor, center, etc.) to compare the distinctive parts.

### What the pipeline found and corrected

| Category | Count | Examples |
|----------|-------|---------|
| Already correct | ~15 | Bellhaven of Goshen, Bellhaven of Meadville |
| Name updates | 5 | "Bellhaven Rehab and Nursing" → full name; "Chesterton Senior Commons" → "Bellhaven of Chesterton" |
| Wrong parent | 5 | Crossings of Lima (Harborview → Bellhaven), Kettering Care Centre (Harborview → Bellhaven) |
| CHOW re-parents | 2 | Tiffin ($84k rev, $12.4k AR), Marietta ($51.25k rev, $3.8k AR) |
| Duplicates | 5 | Two Owosso accounts, Harborview Shores = Bellhaven Shores of Erie |
| New accounts | 3 | Batavia, Carlisle, Amberly Manor (Hudson) |
| CRM-only (flagged) | 3 | Alliance, Coldwater, Sandusky — not on website, set to "Needs Review" |
| Data fixes | 2 | Portsmouth wrong ZIP, Ashtabula PO Box → street address |

### Notable cases
- **Bellhaven Meadows of Findlay**: Announced on homepage but not in the paginated community list. Scraper catches it via homepage check.
- **Amberly Manor (Hudson, OH)**: Different branding but listed on Bellhaven's website. No existing CRM account → created.
- **Bellhaven of Sandusky**: Has $130k revenue and $5.2k outstanding AR, but not on website. Flagged as "Needs Review" rather than deactivated, since the billing relationship is significant.

## File Structure

```
bellhaven-crm-sync/
├── scraper.py           # Website scraper
├── matcher.py           # Matching + proposal generation
├── crm.py               # CRM API client
├── server.py            # Review web app (Flask)
├── requirements.txt     # Python dependencies
├── data/
│   ├── communities.json # Scraped website data
│   ├── proposals.json   # Current proposals
│   └── decisions.json   # Approved/rejected decisions (idempotency)
├── .github/workflows/
│   └── daily-sync.yml   # Daily cron schedule
└── README.md
```
