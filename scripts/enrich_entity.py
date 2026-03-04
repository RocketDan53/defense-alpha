#!/usr/bin/env python3
"""
Entity Enrichment — Close data gaps via web search.

Two-phase approach:
  Phase 1: Claude + web_search gathers raw findings
  Phase 2: Claude structures findings into JSON for staging

Usage:
    python scripts/enrich_entity.py --entity "X-BOW LAUNCH SYSTEMS INC"
    python scripts/enrich_entity.py --entity "X-BOW LAUNCH SYSTEMS INC" --auto-approve
    python scripts/enrich_entity.py --batch --file priority_entities.txt
    python scripts/enrich_entity.py --review
"""

import argparse
import json
import logging
import sqlite3
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings

PROJECT_ROOT = Path(__file__).parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Database helpers ─────────────────────────────────────────────────────

def _db_path() -> str:
    return settings.DATABASE_URL.replace("sqlite:///", "")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def lookup_entity(conn, name: str) -> dict | None:
    """Find entity by name (case-insensitive, partial match)."""
    row = conn.execute(
        "SELECT * FROM entities WHERE canonical_name LIKE ? AND merged_into_id IS NULL LIMIT 1",
        (f"%{name}%",),
    ).fetchone()
    return dict(row) if row else None


def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except (ValueError, IndexError):
        return None


# ── Phase 1: Gather existing data ───────────────────────────────────────

def gather_existing_data(conn, entity_id: str) -> dict:
    """Return current counts/dates so Claude knows what's already in the DB."""
    sbir_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM funding_events WHERE entity_id = ? "
        "AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')",
        (entity_id,),
    ).fetchone()["cnt"]

    sbir_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM funding_events WHERE entity_id = ? "
        "AND event_type IN ('SBIR_PHASE_1','SBIR_PHASE_2','SBIR_PHASE_3')",
        (entity_id,),
    ).fetchone()["total"]

    contract_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM contracts WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()["cnt"]

    contract_total = conn.execute(
        "SELECT COALESCE(SUM(contract_value), 0) as total FROM contracts WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()["total"]

    regd_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM funding_events WHERE entity_id = ? AND event_type = 'REG_D_FILING'",
        (entity_id,),
    ).fetchone()["cnt"]

    regd_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM funding_events WHERE entity_id = ? AND event_type = 'REG_D_FILING'",
        (entity_id,),
    ).fetchone()["total"]

    # Existing round details
    rounds = conn.execute(
        "SELECT round_stage, amount, event_date, source FROM funding_events "
        "WHERE entity_id = ? AND event_type = 'REG_D_FILING' ORDER BY event_date",
        (entity_id,),
    ).fetchall()
    round_summary = "; ".join(
        f"{r['round_stage'] or '?'} ${float(r['amount'] or 0)/1e6:.1f}M ({r['event_date'] or '?'})"
        for r in rounds
    ) or "None"

    return {
        "sbir_count": sbir_count,
        "sbir_total": f"${float(sbir_total)/1e6:.1f}M",
        "contract_count": contract_count,
        "contract_total": f"${float(contract_total)/1e6:.1f}M",
        "regd_count": regd_count,
        "regd_total": f"${float(regd_total)/1e6:.1f}M",
        "existing_rounds": round_summary,
    }


# ── Phase 2: Search and extract ─────────────────────────────────────────

SEARCH_PROMPT = """
Search for all contracts, funding rounds, acquisitions, partnerships, and
OTA (Other Transaction Authority) agreements for {entity_name}.

Focus on:
1. Government contracts — especially OTAs, production contracts, IDIQ awards.
   Include dollar amounts, awarding agency, contract type, and dates.
2. Private funding rounds — total round size (not just Form D amount),
   lead investors, round stage (seed/A/B/C), and close dates.
3. Acquisitions — companies acquired, acquisition price if disclosed, date.
4. Strategic partnerships — partner name, nature of partnership, date.
5. Government co-investments — e.g., DoD Office of Strategic Capital,
   DIU, AFWERX Catalyst awards.

For context, our database currently has:
- {sbir_count} SBIR awards (total: {sbir_total})
- {contract_count} production contracts (total: {contract_total})
- {regd_count} Reg D filings (total: {regd_total})
- Funding rounds on file: {existing_rounds}

Also determine: Is this company publicly traded? If so, note the ticker symbol
and exchange. Public companies should not be flagged as lacking private capital —
they have access to public market funding.

Search thoroughly. Report everything you find with specific dollar amounts,
dates, and sources. Do not speculate.
"""

STRUCTURE_PROMPT = """
You are a data extraction tool. Convert the following research findings about
{entity_name} into structured JSON. Return ONLY valid JSON, no markdown fences,
no explanation.

Research findings:
{search_results}

Existing database records (do NOT duplicate these):
{existing_summary}

Return this exact schema:
{{
  "contracts": [
    {{
      "description": "string - what the contract is for",
      "contracting_agency": "string - awarding agency",
      "contract_value": number or null,
      "award_date": "YYYY-MM-DD" or null,
      "contract_type": "production|development|services|other",
      "procurement_type": "ota|standard|idiq|p3|other",
      "source_url": "string - where you found this",
      "confidence": "high|medium|low"
    }}
  ],
  "funding_rounds": [
    {{
      "amount": number or null,
      "event_date": "YYYY-MM-DD" or null,
      "round_stage": "seed|series_a|series_b|series_c|growth|other",
      "lead_investors": ["string"],
      "source_url": "string",
      "confidence": "high|medium|low",
      "is_update_to_existing": true or false,
      "updates_filing_source": "sec_edgar:xxx" or null
    }}
  ],
  "partnerships": [
    {{
      "partner_name": "string",
      "partnership_type": "strategic|joint_venture|acquisition|co_investment|p3|other",
      "description": "string",
      "value": number or null,
      "announcement_date": "YYYY-MM-DD" or null,
      "source_url": "string",
      "confidence": "high|medium|low"
    }}
  ],
  "ota_awards": [
    {{
      "program_name": "string - e.g., NEST, DIU, AFWERX Catalyst",
      "description": "string",
      "contracting_agency": "string",
      "value": number or null,
      "award_date": "YYYY-MM-DD" or null,
      "source_url": "string",
      "confidence": "high|medium|low"
    }}
  ],
  "public_company": {{
    "is_public": true or false,
    "ticker": "string or null - e.g., LUNA",
    "exchange": "string or null - e.g., NASDAQ",
    "note": "string or null - e.g., Publicly traded since 2006",
    "source_url": "string or null"
  }}
}}

Rules:
- Only include findings NOT already in the database
- If a funding round updates an existing Reg D filing (same round, higher
  amount from press release), set is_update_to_existing=true and reference
  the existing filing source
- Dates should be as precise as possible. If only month/year, use the 1st
  of the month
- confidence=high means dollar amount and date are both confirmed by a
  named source. medium means one is estimated. low means the finding is
  from a single unverified source.
- OTA awards go in ota_awards, NOT contracts
- If the company is publicly traded, set public_company.is_public=true with
  ticker and exchange. If not public or unknown, set is_public=false.
"""


def search_and_extract(entity_name: str, existing_data: dict) -> dict:
    """
    Two-phase Claude API call:
      Phase 1: Web search to gather raw findings
      Phase 2: Structure into JSON
    """
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return {}

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.error("anthropic package not installed (pip install anthropic)")
        return {}

    client = Anthropic(api_key=api_key)

    # Phase 1: Search
    search_prompt = SEARCH_PROMPT.format(entity_name=entity_name, **existing_data)
    logger.info("Phase 1: Searching web for %s...", entity_name)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 10,
        }],
        messages=[{"role": "user", "content": search_prompt}],
    )

    # Extract text from response
    text_parts = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text.strip())
    search_results = "\n".join(text_parts)

    if not search_results.strip():
        logger.warning("No search results returned")
        return {}

    logger.info("Phase 1 complete. Structuring results...")

    # Phase 2: Structure
    existing_summary = json.dumps(existing_data, indent=2)
    structure_prompt = STRUCTURE_PROMPT.format(
        entity_name=entity_name,
        search_results=search_results,
        existing_summary=existing_summary,
    )

    response2 = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": structure_prompt}],
    )

    raw_json = response2.content[0].text.strip()

    # Strip markdown fences if present
    if raw_json.startswith("```"):
        lines = raw_json.split("\n")
        raw_json = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        findings = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse structured JSON: %s", e)
        logger.debug("Raw response: %s", raw_json[:500])
        return {}

    total = sum(len(findings.get(k, [])) for k in ["contracts", "funding_rounds", "partnerships", "ota_awards"])
    logger.info("Phase 2 complete. %d findings extracted.", total)

    return findings


# ── Deduplication ────────────────────────────────────────────────────────

def is_duplicate_contract(conn, entity_id: str, data: dict) -> bool:
    """Check if a contract finding is already in the database."""
    existing = conn.execute(
        "SELECT * FROM contracts WHERE entity_id = ? AND contracting_agency = ?",
        (entity_id, data.get("contracting_agency")),
    ).fetchall()

    for c in existing:
        existing_val = float(c["contract_value"] or 0)
        new_val = float(data.get("contract_value") or 0)
        if existing_val > 0 and new_val > 0:
            if abs(existing_val - new_val) / existing_val < 0.10:
                return True

        existing_date = _parse_date(c["award_date"])
        new_date = _parse_date(data.get("award_date"))
        if existing_date and new_date:
            if abs((existing_date - new_date).days) < 90:
                if existing_val == 0 or new_val == 0:
                    return True

    return False


def is_duplicate_funding(conn, entity_id: str, data: dict) -> tuple[bool | str, str | None]:
    """Check if a funding round is already captured. Returns (status, source)."""
    existing = conn.execute(
        "SELECT * FROM funding_events WHERE entity_id = ? "
        "AND event_type IN ('REG_D_FILING', 'VC_ROUND')",
        (entity_id,),
    ).fetchall()

    for f in existing:
        existing_val = float(f["amount"] or 0)
        new_val = float(data.get("amount") or 0)
        existing_date = _parse_date(f["event_date"])
        new_date = _parse_date(data.get("event_date"))

        if f["round_stage"] == data.get("round_stage"):
            if existing_date and new_date:
                if abs((existing_date - new_date).days) < 180:
                    if new_val > existing_val:
                        return "update", f["source"]
                    return True, None

    return False, None


# ── Stage findings ───────────────────────────────────────────────────────

def stage_findings(conn, entity_id: str, findings: dict) -> list[str]:
    """Write findings to enrichment_findings with status='pending'. Returns IDs."""
    staged_ids = []
    now = datetime.now(tz=timezone.utc).isoformat()

    for contract in findings.get("contracts", []):
        if is_duplicate_contract(conn, entity_id, contract):
            logger.info("  SKIP (duplicate contract): %s", contract.get("description", "")[:60])
            continue
        fid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO enrichment_findings (id, entity_id, finding_type, finding_data, source_url, confidence, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (fid, entity_id, "contract", json.dumps(contract),
             contract.get("source_url"), contract.get("confidence"), now),
        )
        staged_ids.append(fid)

    for fr in findings.get("funding_rounds", []):
        dup_status, dup_source = is_duplicate_funding(conn, entity_id, fr)
        if dup_status is True:
            logger.info("  SKIP (duplicate funding): %s %s", fr.get("round_stage"), fr.get("amount"))
            continue
        if dup_status == "update":
            fr["is_update_to_existing"] = True
            fr["updates_filing_source"] = dup_source
        fid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO enrichment_findings (id, entity_id, finding_type, finding_data, source_url, confidence, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (fid, entity_id, "funding_round", json.dumps(fr),
             fr.get("source_url"), fr.get("confidence"), now),
        )
        staged_ids.append(fid)

    for ota in findings.get("ota_awards", []):
        if is_duplicate_contract(conn, entity_id, {"contracting_agency": ota.get("contracting_agency"), "contract_value": ota.get("value"), "award_date": ota.get("award_date")}):
            logger.info("  SKIP (duplicate OTA): %s", ota.get("description", "")[:60])
            continue
        fid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO enrichment_findings (id, entity_id, finding_type, finding_data, source_url, confidence, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (fid, entity_id, "ota_award", json.dumps(ota),
             ota.get("source_url"), ota.get("confidence"), now),
        )
        staged_ids.append(fid)

    for p in findings.get("partnerships", []):
        fid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO enrichment_findings (id, entity_id, finding_type, finding_data, source_url, confidence, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (fid, entity_id, "partnership", json.dumps(p),
             p.get("source_url"), p.get("confidence"), now),
        )
        staged_ids.append(fid)

    # Public company detection
    pub = findings.get("public_company")
    if pub and pub.get("is_public"):
        # Check if already flagged
        already = conn.execute(
            "SELECT 1 FROM enrichment_findings WHERE entity_id = ? AND finding_type = 'public_company'",
            (entity_id,),
        ).fetchone()
        if not already:
            fid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO enrichment_findings (id, entity_id, finding_type, finding_data, source_url, confidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (fid, entity_id, "public_company", json.dumps(pub),
                 pub.get("source_url"), "high", now),
            )
            staged_ids.append(fid)
            logger.info("  PUBLIC COMPANY: %s (%s)", pub.get("ticker"), pub.get("exchange"))

    conn.commit()
    return staged_ids


# ── Ingestion ────────────────────────────────────────────────────────────

def ingest_finding(conn, finding) -> str | None:
    """Write an approved enrichment finding to the appropriate table."""
    data = json.loads(finding["finding_data"]) if isinstance(finding["finding_data"], str) else finding["finding_data"]
    entity_id = finding["entity_id"]
    now = datetime.now(tz=timezone.utc).isoformat()

    if finding["finding_type"] == "contract":
        record_id = str(uuid.uuid4())
        # contracts table requires a contract_number (unique, not null)
        contract_number = f"WEB-{record_id[:8]}"
        conn.execute(
            """INSERT INTO contracts
               (id, entity_id, contract_number, contracting_agency, contract_value, award_date,
                contract_type, procurement_type, raw_data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, entity_id, contract_number,
             data.get("contracting_agency"),
             data.get("contract_value"),
             data.get("award_date"),
             data.get("contract_type"),
             data.get("procurement_type", "standard"),
             json.dumps({"source": "web_enrichment", "source_url": data.get("source_url", ""), "description": data.get("description", "")}),
             now, now),
        )
        return record_id

    elif finding["finding_type"] == "funding_round":
        if data.get("is_update_to_existing"):
            # Find the existing EDGAR filing this enrichment supersedes
            match = conn.execute(
                """SELECT id FROM funding_events
                   WHERE entity_id = ? AND event_type = 'REG_D_FILING'
                   AND round_stage = ?
                   ORDER BY ABS(amount - ?) ASC LIMIT 1""",
                (entity_id, data.get("round_stage"), data.get("amount", 0)),
            ).fetchone()
            parent_id = match["id"] if match else None

            record_id = str(uuid.uuid4())
            investors = data.get("lead_investors", [])
            conn.execute(
                """INSERT INTO funding_events
                   (id, entity_id, event_type, amount, event_date,
                    round_stage, investors_awarders, source, raw_data,
                    parent_event_id, created_at)
                   VALUES (?, ?, 'PRIVATE_ROUND', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, entity_id,
                 data.get("amount"),
                 data.get("event_date"),
                 data.get("round_stage"),
                 json.dumps(investors),
                 f"web_enrichment:{data.get('source_url', '')}",
                 json.dumps({"source": "web_enrichment", "confidence": data.get("confidence")}),
                 parent_id, now),
            )
            return record_id
        else:
            record_id = str(uuid.uuid4())
            investors = data.get("lead_investors", [])
            conn.execute(
                """INSERT INTO funding_events
                   (id, entity_id, event_type, amount, event_date,
                    round_stage, investors_awarders, source, raw_data, created_at)
                   VALUES (?, ?, 'PRIVATE_ROUND', ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, entity_id,
                 data.get("amount"),
                 data.get("event_date"),
                 data.get("round_stage"),
                 json.dumps(investors),
                 f"web_enrichment:{data.get('source_url', '')}",
                 json.dumps({"source": "web_enrichment", "confidence": data.get("confidence")}),
                 now),
            )
            return record_id

    elif finding["finding_type"] == "ota_award":
        record_id = str(uuid.uuid4())
        contract_number = f"OTA-{record_id[:8]}"
        conn.execute(
            """INSERT INTO contracts
               (id, entity_id, contract_number, contracting_agency, contract_value, award_date,
                contract_type, procurement_type, raw_data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'ota', ?, ?, ?)""",
            (record_id, entity_id, contract_number,
             data.get("contracting_agency"),
             data.get("value"),
             data.get("award_date"),
             "development",
             json.dumps({"source": "web_enrichment", "program": data.get("program_name"), "source_url": data.get("source_url", ""), "description": data.get("description", "")}),
             now, now),
        )
        return record_id

    elif finding["finding_type"] == "partnership":
        record_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO relationships
               (id, source_entity_id, relationship_type, target_name, weight, properties, created_at)
               VALUES (?, ?, 'INVESTED_IN_BY', ?, ?, ?, ?)""",
            (record_id, entity_id,
             data.get("partner_name"),
             data.get("value"),
             json.dumps(data),
             now),
        )
        return record_id

    elif finding["finding_type"] == "public_company":
        # No separate table — the enrichment_findings record itself is the flag.
        # Signal detectors check enrichment_findings for public_company type.
        return finding["id"]

    return None


# ── Review CLI ───────────────────────────────────────────────────────────

def review_pending(conn):
    """Interactive review of pending enrichment findings."""
    pending = conn.execute(
        """SELECT ef.*, e.canonical_name
           FROM enrichment_findings ef
           JOIN entities e ON ef.entity_id = e.id
           WHERE ef.status = 'pending'
           ORDER BY ef.created_at""",
    ).fetchall()

    if not pending:
        print("No pending findings to review.")
        return

    print(f"\n{len(pending)} pending findings:\n")

    for f in pending:
        data = json.loads(f["finding_data"]) if isinstance(f["finding_data"], str) else f["finding_data"]
        print(f"  Entity:     {f['canonical_name']}")
        print(f"  Type:       {f['finding_type']}")
        print(f"  Confidence: {f['confidence']}")
        print(f"  Source:     {f['source_url'] or 'N/A'}")
        print(f"  Data:       {json.dumps(data, indent=2)}")
        print()

        while True:
            choice = input("  [a]pprove / [r]eject / [s]kip / [q]uit? ").lower().strip()
            if choice in ('a', 'r', 's', 'q'):
                break

        if choice == 'q':
            break
        elif choice == 's':
            continue
        elif choice == 'a':
            record_id = ingest_finding(conn, f)
            conn.execute(
                """UPDATE enrichment_findings
                   SET status = 'ingested', reviewed_at = datetime('now'),
                       reviewed_by = 'manual', ingested_at = datetime('now'),
                       ingested_record_id = ?
                   WHERE id = ?""",
                (record_id, f["id"]),
            )
            conn.commit()
            print(f"  Ingested as {record_id}\n")
        elif choice == 'r':
            conn.execute(
                """UPDATE enrichment_findings
                   SET status = 'rejected', reviewed_at = datetime('now'),
                       reviewed_by = 'manual'
                   WHERE id = ?""",
                (f["id"],),
            )
            conn.commit()
            print(f"  Rejected\n")


# ── Batch mode ───────────────────────────────────────────────────────────

def run_batch(conn, entity_file: str, auto_approve_high: bool = False):
    """Enrich multiple entities from a file (one name per line)."""
    names = Path(entity_file).read_text().strip().splitlines()

    for name in names:
        name = name.strip()
        if not name or name.startswith("#"):
            continue

        print(f"\n{'='*60}")
        print(f"Enriching: {name}")
        print(f"{'='*60}")

        entity = lookup_entity(conn, name)
        if not entity:
            print(f"  Entity not found, skipping")
            continue

        existing = gather_existing_data(conn, entity["id"])
        findings = search_and_extract(name, existing)
        if not findings:
            print(f"  No findings returned")
            continue

        staged = stage_findings(conn, entity["id"], findings)
        print(f"  Staged {len(staged)} findings")

        if auto_approve_high and staged:
            auto_count = 0
            for finding_id in staged:
                f = conn.execute(
                    "SELECT * FROM enrichment_findings WHERE id = ?",
                    (finding_id,),
                ).fetchone()
                if f and f["confidence"] == "high":
                    record_id = ingest_finding(conn, f)
                    conn.execute(
                        """UPDATE enrichment_findings
                           SET status='ingested', reviewed_at=datetime('now'),
                               reviewed_by='auto', ingested_record_id=?
                           WHERE id=?""",
                        (record_id, finding_id),
                    )
                    auto_count += 1
            conn.commit()
            print(f"  Auto-approved {auto_count} high-confidence findings")


# ── Single entity mode ───────────────────────────────────────────────────

def enrich_single(conn, entity_name: str, auto_approve: bool = False) -> dict:
    """
    Enrich a single entity.

    Returns: {"entity": name, "status": "success"|"not_found"|"no_findings",
              "findings": int, "approved": int, "errors": []}
    """
    result = {"entity": entity_name, "status": "not_found", "findings": 0,
              "approved": 0, "rejected": 0, "errors": [],
              "by_type": {}}

    entity = lookup_entity(conn, entity_name)
    if not entity:
        logger.warning("Entity '%s' not found in database.", entity_name)
        return result

    name = entity["canonical_name"]
    entity_id = entity["id"]
    result["entity"] = name

    logger.info("Enriching: %s (%s)", name, entity_id)

    existing = gather_existing_data(conn, entity_id)
    logger.info("  Current data: %d SBIRs, %d contracts, %d Reg D filings",
                existing['sbir_count'], existing['contract_count'], existing['regd_count'])

    try:
        findings = search_and_extract(name, existing)
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        logger.error("  Search failed for %s: %s", name, e)
        return result

    if not findings:
        result["status"] = "no_findings"
        logger.info("  No findings returned from web search.")
        return result

    # Count by type
    for category in ["contracts", "funding_rounds", "ota_awards", "partnerships"]:
        items = findings.get(category, [])
        if items:
            result["by_type"][category] = len(items)
            logger.info("  %s: %d finding(s)", category, len(items))
            for item in items:
                desc = item.get("description") or item.get("partner_name") or item.get("round_stage") or "?"
                val = item.get("contract_value") or item.get("amount") or item.get("value")
                val_str = f" (${float(val)/1e6:.1f}M)" if val else ""
                conf = item.get("confidence", "?")
                logger.info("    [%s] %s%s", conf, str(desc)[:70], val_str)

    staged = stage_findings(conn, entity_id, findings)
    result["findings"] = len(staged)
    logger.info("  Staged %d findings for review", len(staged))

    if auto_approve and staged:
        auto_count = 0
        for finding_id in staged:
            f = conn.execute(
                "SELECT * FROM enrichment_findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
            if f and f["confidence"] == "high":
                record_id = ingest_finding(conn, f)
                conn.execute(
                    """UPDATE enrichment_findings
                       SET status='ingested', reviewed_at=datetime('now'),
                           reviewed_by='auto', ingested_record_id=?
                       WHERE id=?""",
                    (record_id, finding_id),
                )
                auto_count += 1
        conn.commit()
        result["approved"] = auto_count
        result["rejected"] = len(staged) - auto_count
        logger.info("  Auto-approved %d high-confidence findings", auto_count)
        remaining = len(staged) - auto_count
        if remaining > 0:
            logger.info("  %d medium/low-confidence findings need manual review (--review)", remaining)

    result["status"] = "success"
    return result


def enrich_single_entity(entity_name: str, auto_approve: bool = True, conn=None) -> dict:
    """
    Convenience wrapper for batch use.
    Creates its own connection if none provided.
    Returns: {"entity": name, "status": ..., "findings": int, "approved": int, "errors": []}
    """
    close_conn = False
    if conn is None:
        conn = _connect()
        close_conn = True
    try:
        return enrich_single(conn, entity_name, auto_approve=auto_approve)
    finally:
        if close_conn:
            conn.close()


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Entity Enrichment - Close data gaps via web search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/enrich_entity.py --entity "X-BOW LAUNCH SYSTEMS INC"
  python scripts/enrich_entity.py --entity "X-BOW LAUNCH SYSTEMS INC" --auto-approve
  python scripts/enrich_entity.py --batch --file priority_entities.txt
  python scripts/enrich_entity.py --batch --file priority_entities.txt --auto-approve
  python scripts/enrich_entity.py --review
        """,
    )
    parser.add_argument("--entity", type=str, help="Entity name to enrich")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve high-confidence findings")
    parser.add_argument("--batch", action="store_true",
                        help="Batch mode: enrich multiple entities from file")
    parser.add_argument("--file", type=str,
                        help="File with entity names (one per line) for batch mode")
    parser.add_argument("--review", action="store_true",
                        help="Interactive review of pending findings")

    args = parser.parse_args()

    conn = _connect()

    try:
        if args.review:
            review_pending(conn)
        elif args.batch and args.file:
            run_batch(conn, args.file, auto_approve_high=args.auto_approve)
        elif args.entity:
            result = enrich_single(conn, args.entity, auto_approve=args.auto_approve)
            if result["status"] == "not_found":
                sys.exit(1)
        else:
            parser.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
