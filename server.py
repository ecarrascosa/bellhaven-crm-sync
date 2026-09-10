"""
Review app: Flask web UI for approving/rejecting CRM sync proposals.
Approved changes write to the CRM via API. Nothing writes without approval.
"""

import json
from pathlib import Path
from flask import Flask, jsonify, request

from crm import update_account, create_account

DATA_DIR = Path(__file__).parent / "data"
PROPOSALS_FILE = DATA_DIR / "proposals.json"
DECISIONS_FILE = DATA_DIR / "decisions.json"

app = Flask(__name__)


def load_proposals() -> list[dict]:
    return json.loads(PROPOSALS_FILE.read_text())


def load_decisions() -> dict:
    if DECISIONS_FILE.exists():
        return json.loads(DECISIONS_FILE.read_text())
    return {}


def save_decisions(decisions: dict):
    DECISIONS_FILE.write_text(json.dumps(decisions, indent=2))


def execute_proposal(proposal: dict) -> dict:
    """Execute a single proposal against the CRM API. Returns result dict."""
    result = {}
    action = proposal["action"]

    if proposal["type"] == "MATCH_FIX_CHOW":
        created = create_account(action["create"])
        result["created"] = created
        old_fields = dict(action["update_old"]["fields"])
        old_fields["chow_current_account"] = created["account_id"]
        updated = update_account(action["update_old"]["account_id"], old_fields)
        result["updated_old"] = updated
    elif "create" in action:
        result["created"] = create_account(action["create"])
    if "update" in action:
        result["updated"] = update_account(
            action["update"]["account_id"], action["update"]["fields"]
        )
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return HTML


@app.route("/api/proposals")
def api_proposals():
    proposals = load_proposals()
    decisions = load_decisions()
    return jsonify([{**p, "decision": decisions.get(p["key"])} for p in proposals])


@app.route("/api/proposals/<path:key>/approve", methods=["POST"])
def approve(key: str):
    proposals = load_proposals()
    proposal = next((p for p in proposals if p["key"] == key), None)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    decisions = load_decisions()
    if key in decisions:
        return jsonify({"error": "Already decided"}), 400

    try:
        result = execute_proposal(proposal)
        decisions[key] = {
            "decision": "approved",
            "at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "account_id": (result.get("created", {}).get("account_id")
                           or proposal.get("action", {}).get("update", {}).get("account_id")),
            "result": result,
        }
        save_decisions(decisions)
        return jsonify({"status": "approved", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/proposals/<path:key>/reject", methods=["POST"])
def reject(key: str):
    decisions = load_decisions()
    if key in decisions:
        return jsonify({"error": "Already decided"}), 400

    body = request.get_json(silent=True) or {}
    decisions[key] = {
        "decision": "rejected",
        "at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "reason": body.get("reason", ""),
    }
    save_decisions(decisions)
    return jsonify({"status": "rejected"})


@app.route("/api/proposals/approve-all", methods=["POST"])
def approve_all():
    proposals = load_proposals()
    decisions = load_decisions()
    results = []

    for p in proposals:
        if p["key"] in decisions:
            continue
        try:
            result = execute_proposal(p)
            decisions[p["key"]] = {
                "decision": "approved",
                "at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "account_id": (result.get("created", {}).get("account_id")
                               or p.get("action", {}).get("update", {}).get("account_id")),
                "result": result,
            }
            results.append({"key": p["key"], "status": "approved"})
        except Exception as e:
            results.append({"key": p["key"], "status": "error", "error": str(e)})

    save_decisions(decisions)
    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# HTML (single-page review UI)
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bellhaven CRM Sync — Review</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #1a365d; color: white; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .stats { display: flex; gap: 16px; font-size: 13px; }
  .stat { background: rgba(255,255,255,0.15); padding: 4px 12px; border-radius: 12px; }
  .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
  .filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .filters button { padding: 6px 14px; border: 1px solid #ccc; background: white; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .filters button.active { background: #1a365d; color: white; border-color: #1a365d; }
  .card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 12px; overflow: hidden; }
  .card-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #eee; }
  .card-header h3 { font-size: 15px; }
  .badge { font-size: 11px; padding: 3px 10px; border-radius: 10px; font-weight: 600; text-transform: uppercase; }
  .badge-new { background: #d4edda; color: #155724; }
  .badge-fix { background: #fff3cd; color: #856404; }
  .badge-chow { background: #f8d7da; color: #721c24; }
  .badge-crm { background: #cce5ff; color: #004085; }
  .badge-dup { background: #e2e3e5; color: #383d41; }
  .badge-approved { background: #d4edda; color: #155724; }
  .badge-rejected { background: #f8d7da; color: #721c24; }
  .card-body { padding: 14px 20px; font-size: 13px; }
  .card-body .reason { margin-bottom: 10px; color: #555; }
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .detail-box { background: #f8f9fa; padding: 10px; border-radius: 6px; }
  .detail-box h4 { font-size: 12px; color: #666; margin-bottom: 6px; text-transform: uppercase; }
  .detail-box p { font-size: 13px; line-height: 1.5; }
  .change { color: #c0392b; font-weight: 500; }
  .actions { display: flex; gap: 8px; padding: 10px 20px; border-top: 1px solid #eee; }
  .btn { padding: 7px 18px; border: none; border-radius: 5px; cursor: pointer; font-size: 13px; font-weight: 500; }
  .btn-approve { background: #28a745; color: white; }
  .btn-reject { background: #dc3545; color: white; }
  .btn-all { background: #1a365d; color: white; padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .decided { opacity: 0.6; }
</style>
</head>
<body>
<div class="header">
  <h1>🏥 Bellhaven CRM Sync — Review Queue</h1>
  <div class="stats" id="stats"></div>
</div>
<div class="container">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 16px;">
    <div class="filters" id="filters"></div>
    <button class="btn-all" onclick="approveAll()">✅ Approve All Pending</button>
  </div>
  <div id="proposals"></div>
</div>
<script>
let allProposals = [];
let filter = 'all';

async function load() {
  const res = await fetch('/api/proposals');
  allProposals = await res.json();
  render();
}

function render() {
  const filtered = filter === 'all' ? allProposals :
    filter === 'pending' ? allProposals.filter(p => !p.decision) :
    allProposals.filter(p => p.type === filter);

  const pending = allProposals.filter(p => !p.decision).length;
  const approved = allProposals.filter(p => p.decision?.decision === 'approved').length;
  const rejected = allProposals.filter(p => p.decision?.decision === 'rejected').length;

  document.getElementById('stats').innerHTML =
    `<span class="stat">📋 ${allProposals.length} total</span>` +
    `<span class="stat">⏳ ${pending} pending</span>` +
    `<span class="stat">✅ ${approved} approved</span>` +
    `<span class="stat">❌ ${rejected} rejected</span>`;

  const types = ['all','pending','NEW_ACCOUNT','MATCH_FIX','MATCH_FIX_CHOW','CRM_ONLY','DUPLICATE'];
  const labels = {all:'All',pending:'Pending',NEW_ACCOUNT:'New',MATCH_FIX:'Fix',MATCH_FIX_CHOW:'CHOW',CRM_ONLY:'CRM Only',DUPLICATE:'Duplicate'};
  document.getElementById('filters').innerHTML = types.map(t =>
    `<button class="${filter===t?'active':''}" onclick="setFilter('${t}')">${labels[t]}</button>`
  ).join('');

  document.getElementById('proposals').innerHTML = filtered.map(renderCard).join('');
}

function badgeClass(type) {
  return {NEW_ACCOUNT:'badge-new',MATCH_FIX:'badge-fix',MATCH_FIX_CHOW:'badge-chow',CRM_ONLY:'badge-crm',DUPLICATE:'badge-dup'}[type]||'';
}

function renderCard(p) {
  const decided = p.decision ? ' decided' : '';
  const decBadge = p.decision ?
    `<span class="badge ${p.decision.decision==='approved'?'badge-approved':'badge-rejected'}">${p.decision.decision}</span>` : '';

  let details = '';
  if (p.community) {
    details += `<div class="detail-box"><h4>Website</h4><p>
      ${p.community.name}<br>${p.community.street}<br>
      ${p.community.city}, ${p.community.state} ${p.community.zip}<br>
      Care: ${p.community.care}</p></div>`;
  }
  if (p.account) {
    details += `<div class="detail-box"><h4>CRM Account</h4><p>
      ${p.account.name} <small>(${p.account.account_id})</small><br>
      ${p.account.billing_street}<br>
      ${p.account.billing_city}, ${p.account.billing_state} ${p.account.billing_zip}<br>
      Care: ${p.account.care_type}<br>
      Parent: ${p.account.parent_name||'none'}<br>
      Revenue: $${(p.account.lifetime_revenue||0).toLocaleString()}
      | AR: $${(p.account.outstanding_ar||0).toLocaleString()}</p></div>`;
  }
  if (p.duplicate) {
    details += `<div class="detail-box"><h4>Duplicate Account</h4><p>
      ${p.duplicate.name} <small>(${p.duplicate.account_id})</small><br>
      ${p.duplicate.billing_city}, ${p.duplicate.billing_state}</p></div>`;
  }

  let actionDetail = '';
  const act = p.action || {};
  if (act.create) {
    actionDetail += `<div class="detail-box"><h4>Action: Create Account</h4>
      <p><pre style="white-space:pre-wrap;font-size:12px">${JSON.stringify(act.create,null,2)}</pre></p></div>`;
  }
  if (act.update) {
    actionDetail += `<div class="detail-box"><h4>Action: Update ${act.update.account_id}</h4><p>` +
      Object.entries(act.update.fields).map(([k,v])=>`<span class="change">${k}</span>: ${v}`).join('<br>') +
      `</p></div>`;
  }
  if (act.update_old) {
    actionDetail += `<div class="detail-box"><h4>Action: CHOW — Update Old Account</h4><p>
      Set chow_current_account → new account ID<br>` +
      Object.entries(act.update_old.fields).map(([k,v])=>`${k}: ${v}`).join('<br>') +
      `</p></div>`;
  }

  const buttons = p.decision ? '' :
    `<div class="actions">
      <button class="btn btn-approve" onclick="decide('${p.key}','approve')">✅ Approve</button>
      <button class="btn btn-reject" onclick="decide('${p.key}','reject')">❌ Reject</button>
    </div>`;

  return `<div class="card${decided}">
    <div class="card-header"><h3>${p.community?.name||p.account?.name||p.key}</h3>
    <div><span class="badge ${badgeClass(p.type)}">${p.type}</span> ${decBadge}</div></div>
    <div class="card-body"><p class="reason">${p.reason}</p>
    <div class="detail-grid">${details}</div>
    <div class="detail-grid">${actionDetail}</div></div>
    ${buttons}</div>`;
}

async function decide(key, action) {
  const url = `/api/proposals/${encodeURIComponent(key)}/${action}`;
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  if (res.ok) await load(); else alert('Error: '+(await res.json()).error);
}

async function approveAll() {
  if (!confirm('Approve ALL pending proposals?')) return;
  const res = await fetch('/api/proposals/approve-all', {method:'POST'});
  if (res.ok) await load(); else alert('Error');
}

function setFilter(f) { filter=f; render(); }

load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 3456))
    print(f"\n🏥 Review app running at http://localhost:{port}")
    print("Open in your browser to review and approve/reject proposals.\n")
    app.run(host="0.0.0.0", port=port, debug=False)
