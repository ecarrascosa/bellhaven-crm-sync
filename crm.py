"""CRM API client."""

import os
import requests

API_BASE = "https://analyst-assessment-production.up.railway.app/api/v1"
TOKEN = os.environ.get("BELLHAVEN_API_TOKEN", "bh_HFbtuCJhqC-fYR5SU95NjA")

def _headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

def get_all_accounts() -> list[dict]:
    """Fetch every account from the CRM, handling pagination."""
    all_accounts = []
    page = 1
    while True:
        r = requests.get(f"{API_BASE}/accounts", headers=_headers(),
                         params={"page": page, "page_size": 50})
        r.raise_for_status()
        data = r.json()
        all_accounts.extend(data["data"])
        if len(all_accounts) >= data["total"]:
            break
        page += 1
    return all_accounts

def update_account(account_id: str, fields: dict) -> dict:
    r = requests.patch(f"{API_BASE}/accounts/{account_id}",
                       headers=_headers(), json=fields)
    r.raise_for_status()
    return r.json()

def create_account(fields: dict) -> dict:
    r = requests.post(f"{API_BASE}/accounts", headers=_headers(), json=fields)
    r.raise_for_status()
    return r.json()
