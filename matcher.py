"""
Matcher: links scraped communities to CRM accounts and produces proposals.

Classification categories:
  MATCH_OK       — website community matches CRM account, no changes needed
  MATCH_FIX      — matches but needs updates (wrong parent, outdated name, etc.)
  MATCH_FIX_CHOW — needs re-parenting but has billing history → CHOW procedure
  NEW_ACCOUNT    — website community has no CRM account
  CRM_ONLY       — CRM account under Bellhaven parent but not on website
  DUPLICATE      — two CRM accounts for the same facility
"""

import json, re
from datetime import date
from pathlib import Path
from crm import get_all_accounts

DATA_DIR = Path(__file__).parent / "data"
BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Strip common words to compare distinctive parts of facility names."""
    n = name.lower()
    for word in ["&amp;", "&", "the", "of", "at", "rehabilitation", "rehab",
                 "nursing", "centre", "center", "healthcare", "health care",
                 "senior", "living", "commons", "manor", "care", "home",
                 "acres", "retirement", "campus"]:
        n = n.replace(word, " ")
    return re.sub(r"[-–—,.\s]+", " ", n).strip()


def normalize_street(s: str) -> str:
    """Normalize street abbreviations for comparison."""
    n = s.lower()
    replacements = [
        (r"\bblvd\.?\b", "boulevard"), (r"\bst\.?\b", "street"),
        (r"\bave\.?\b", "avenue"), (r"\bdr\.?\b", "drive"),
        (r"\brd\.?\b", "road"), (r"\bln\.?\b", "lane"),
        (r"\bct\.?\b", "court"), (r"\bnorthwest\b", "nw"),
        (r"\bnortheast\b", "ne"), (r"\bsouthwest\b", "sw"),
        (r"\bsoutheast\b", "se"), (r"\bnorth\b", "n"),
        (r"\bsouth\b", "s"), (r"\beast\b", "e"), (r"\bwest\b", "w"),
    ]
    for pat, repl in replacements:
        n = re.sub(pat, repl, n)
    return re.sub(r"[.,]", "", n).strip()


def map_care_type(web_care: str) -> str:
    """Map website care labels to CRM care_type values."""
    c = web_care.lower()
    if "memory" in c:
        return "Memory Care"
    if "assisted" in c:
        return "Assisted Living"
    if "rehab" in c or "nursing" in c or "skilled" in c:
        return "Skilled Nursing"
    return web_care


def score_match(comm: dict, acct: dict) -> dict:
    """Score how well a website community matches a CRM account."""
    city_ok = comm["city"].lower() == acct["billing_city"].lower()
    state_ok = comm["state"].lower() == acct["billing_state"].lower()
    zip_ok = comm["zip"] == acct["billing_zip"]
    street_ok = normalize_street(comm["street"]) == normalize_street(acct["billing_street"])

    norm_c = set(normalize_name(comm["name"]).split())
    norm_a = set(normalize_name(acct["name"]).split())
    big = norm_c | norm_a
    overlap = norm_c & norm_a
    name_score = len(overlap) / max(len(big), 1)
    city_in_name = comm["city"].lower() in acct["name"].lower()

    addr_score = sum([city_ok, state_ok, zip_ok, street_ok])
    total = addr_score + name_score * 3 + (0.5 if city_in_name else 0)

    return {"city": city_ok, "state": state_ok, "zip": zip_ok,
            "street": street_ok, "name_score": name_score, "total": total}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    DATA_DIR.mkdir(exist_ok=True)

    communities = json.loads((DATA_DIR / "communities.json").read_text())

    # Load previous decisions for idempotency
    decisions_path = DATA_DIR / "decisions.json"
    decisions: dict = {}
    if decisions_path.exists():
        decisions = json.loads(decisions_path.read_text())

    print("Fetching CRM accounts...")
    accounts = get_all_accounts()
    print(f"Loaded {len(accounts)} CRM accounts")

    # Index by city
    by_city: dict[str, list] = {}
    for a in accounts:
        by_city.setdefault(a["billing_city"].lower(), []).append(a)

    # Build set of account IDs involved in CHOW relationships (skip as duplicates)
    chow_ids: set[str] = set()
    for a in accounts:
        if a.get("chow_current_account"):
            chow_ids.add(a["account_id"])
            chow_ids.add(a["chow_current_account"])
    # Build set of account IDs already marked as duplicates
    dup_ids: set[str] = set()
    for a in accounts:
        if a.get("duplicate_of_account"):
            dup_ids.add(a["account_id"])

    proposals = []
    matched_ids: set[str] = set()

    for comm in communities:
        key = f"web:{comm['slug']}"
        if key in decisions:
            print(f"  ⏭ Skipping {comm['name']} (already decided)")
            aid = decisions[key].get("account_id")
            if aid:
                matched_ids.add(aid)
            continue

        crm_care = map_care_type(comm["care"])

        # Find candidates in same city (skip already-inactive duplicates)
        candidates = []
        for a in by_city.get(comm["city"].lower(), []):
            if a.get("duplicate_of_account") or a.get("status") == "Inactive":
                continue
            sc = score_match(comm, a)
            if sc["total"] >= 1.5 or sc["street"]:
                candidates.append((sc, a))

        # Also check by zip (for city mismatches)
        if comm["zip"]:
            for a in accounts:
                if a.get("duplicate_of_account") or a.get("status") == "Inactive":
                    continue
                if a["billing_zip"] == comm["zip"] and a["billing_city"].lower() != comm["city"].lower():
                    sc = score_match(comm, a)
                    if sc["total"] >= 2:
                        candidates.append((sc, a))

        candidates.sort(key=lambda x: x[0]["total"], reverse=True)

        # ----- NO MATCH → NEW_ACCOUNT -----
        if not candidates:
            proposals.append({
                "key": key, "type": "NEW_ACCOUNT", "community": comm,
                "reason": f"No matching CRM account for {comm['name']} in {comm['city']}, {comm['state']}",
                "action": {"create": {
                    "name": comm["name"], "parent_id": BELLHAVEN_PARENT_ID,
                    "billing_street": comm["street"], "billing_city": comm["city"],
                    "billing_state": comm["state"], "billing_zip": comm["zip"],
                    "care_type": crm_care, "phone": comm["phone"], "status": "Active",
                }},
            })
            print(f"  🆕 {comm['name']} — no CRM match")
            continue

        best_sc, best_acct = candidates[0]
        matched_ids.add(best_acct["account_id"])

        # ----- DUPLICATE detection -----
        if len(candidates) > 1 and candidates[1][0]["total"] > 2:
            dup_acct = candidates[1][1]
            # Skip if either account is part of a CHOW pair or already marked duplicate
            is_chow = dup_acct["account_id"] in chow_ids or best_acct["account_id"] in chow_ids
            already_dup = dup_acct["account_id"] in dup_ids
            if (not is_chow and not already_dup
                    and dup_acct["account_id"] != best_acct["account_id"]
                    and dup_acct["account_id"] not in matched_ids):
                dup_key = f"dup:{dup_acct['account_id']}"
                if dup_key not in decisions:
                    proposals.append({
                        "key": dup_key, "type": "DUPLICATE",
                        "community": comm, "account": best_acct, "duplicate": dup_acct,
                        "reason": f"{dup_acct['name']} appears to be a duplicate of {best_acct['name']} (both in {comm['city']})",
                        "action": {"update": {
                            "account_id": dup_acct["account_id"],
                            "fields": {
                                "status": "Inactive",
                                "duplicate_of_account": best_acct["account_id"],
                                "note": f"Duplicate of {best_acct['name']} ({best_acct['account_id']}). Identified by CRM sync pipeline.",
                            },
                        }},
                    })
                    print(f"  🔁 {dup_acct['name']} — duplicate of {best_acct['name']}")
                matched_ids.add(dup_acct["account_id"])

        # ----- Determine needed changes -----
        changes: dict = {}
        reasons: list[str] = []

        # Parent check
        if best_acct["parent_id"] != BELLHAVEN_PARENT_ID:
            needs_chow = best_acct["lifetime_revenue"] > 0 and best_acct["outstanding_ar"] > 0
            if needs_chow:
                proposals.append({
                    "key": key, "type": "MATCH_FIX_CHOW",
                    "community": comm, "account": best_acct,
                    "reason": (
                        f"{best_acct['name']} is under {best_acct['parent_name']} but should be under Bellhaven. "
                        f"Has revenue (${best_acct['lifetime_revenue']:,}) and outstanding AR "
                        f"(${best_acct['outstanding_ar']:,}), so CHOW procedure applies."
                    ),
                    "action": {
                        "create": {
                            "name": comm["name"], "parent_id": BELLHAVEN_PARENT_ID,
                            "billing_street": comm["street"], "billing_city": comm["city"],
                            "billing_state": comm["state"], "billing_zip": comm["zip"],
                            "care_type": crm_care, "phone": comm["phone"], "status": "Active",
                        },
                        "update_old": {
                            "account_id": best_acct["account_id"],
                            "fields": {
                                "note": "CHOW: Facility now operated by Bellhaven Senior Living. "
                                        "New account created under Bellhaven parent. Old account preserved for billing.",
                            },
                            "set_chow": True,
                        },
                    },
                })
                print(f"  🔄 {best_acct['name']} — CHOW (rev=${best_acct['lifetime_revenue']:,}, AR=${best_acct['outstanding_ar']:,})")
                continue
            else:
                changes["parent_id"] = BELLHAVEN_PARENT_ID
                reasons.append(f"Wrong parent: {best_acct['parent_name']} → Bellhaven Senior Living")

        # Name check
        if best_acct["name"] != comm["name"]:
            if normalize_name(best_acct["name"]) != normalize_name(comm["name"]):
                changes["name"] = comm["name"]
                reasons.append(f'Name: "{best_acct["name"]}" → "{comm["name"]}"')

        # Care type check
        if best_acct["care_type"] != crm_care and "," not in comm["care"]:
            changes["care_type"] = crm_care
            reasons.append(f'Care type: "{best_acct["care_type"]}" → "{crm_care}"')

        # Street check (only if meaningfully different)
        if comm["street"] and normalize_street(comm["street"]) != normalize_street(best_acct["billing_street"]):
            changes["billing_street"] = comm["street"]
            reasons.append(f'Street: "{best_acct["billing_street"]}" → "{comm["street"]}"')

        # ZIP check
        if comm["zip"] and best_acct["billing_zip"] and best_acct["billing_zip"] != comm["zip"]:
            changes["billing_zip"] = comm["zip"]
            reasons.append(f'ZIP: "{best_acct["billing_zip"]}" → "{comm["zip"]}"')

        if not changes:
            print(f"  ✅ {best_acct['name']} — OK")
            continue

        proposals.append({
            "key": key, "type": "MATCH_FIX",
            "community": comm, "account": best_acct,
            "reason": "; ".join(reasons),
            "action": {"update": {"account_id": best_acct["account_id"], "fields": changes}},
        })
        print(f"  🔧 {best_acct['name']} — {'; '.join(reasons)}")

    # ----- CRM-ONLY: under Bellhaven parent but not on website -----
    for a in accounts:
        if a["parent_id"] != BELLHAVEN_PARENT_ID or "Parent Account" in a["name"]:
            continue
        if a.get("status") == "Inactive" or a.get("duplicate_of_account"):
            continue
        if a["account_id"] in matched_ids:
            continue
        crm_key = f"crm_only:{a['account_id']}"
        if crm_key in decisions:
            print(f"  ⏭ Skipping CRM-only {a['name']} (already decided)")
            continue
        proposals.append({
            "key": crm_key, "type": "CRM_ONLY", "account": a,
            "reason": (
                f"{a['name']} ({a['billing_city']}, {a['billing_state']}) is under Bellhaven parent "
                f"but not on website. May have been divested or closed."
            ),
            "action": {"update": {
                "account_id": a["account_id"],
                "fields": {
                    "status": "Needs Review",
                    "note": f"Not found on Bellhaven website as of {date.today().isoformat()}. "
                            f"May be divested or closed. Flagged by CRM sync pipeline.",
                },
            }},
        })
        print(f"  ❓ {a['name']} — in CRM under Bellhaven but not on website")

    # Save proposals
    (DATA_DIR / "proposals.json").write_text(json.dumps(proposals, indent=2))
    print(f"\n📋 Generated {len(proposals)} proposals")
    print("   Run 'python server.py' to review and approve/reject them.")


if __name__ == "__main__":
    main()
