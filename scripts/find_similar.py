#!/usr/bin/env python3
"""
Find companies working on similar technology using semantic search over SBIR award titles.

Uses sentence-transformers (all-MiniLM-L6-v2) to embed SBIR award titles and find
nearest neighbors by cosine similarity.

Usage:
    python scripts/find_similar.py --company "Stellar Science"
    python scripts/find_similar.py --company "HawkEye 360" --top 20
    python scripts/find_similar.py --query "autonomous underwater vehicle"
    python scripts/find_similar.py --embed   # (Re)generate all embeddings
"""

import argparse
import sys
import struct
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from processing.database import SessionLocal
from processing.models import (
    Entity, FundingEvent, FundingEventType, SbirEmbedding,
)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dim


def serialize_embedding(arr: np.ndarray) -> bytes:
    """Pack float32 array to bytes."""
    return struct.pack(f"{len(arr)}f", *arr.tolist())


def deserialize_embedding(data: bytes) -> np.ndarray:
    """Unpack bytes to float32 array."""
    n = len(data) // 4
    return np.array(struct.unpack(f"{n}f", data), dtype=np.float32)


def load_model():
    """Load the sentence-transformer model."""
    from sentence_transformers import SentenceTransformer
    print(f"Loading model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    return model


def generate_embeddings(db, model, batch_size=128):
    """Generate embeddings for all SBIR awards that don't have one yet."""
    # Get SBIR awards with titles that haven't been embedded
    existing_ids = set(
        row[0] for row in db.query(SbirEmbedding.funding_event_id).all()
    )

    awards = db.query(FundingEvent).filter(
        FundingEvent.event_type.in_([
            FundingEventType.SBIR_PHASE_1,
            FundingEventType.SBIR_PHASE_2,
            FundingEventType.SBIR_PHASE_3,
        ]),
        FundingEvent.raw_data.isnot(None),
    ).all()

    to_embed = []
    for a in awards:
        if a.id in existing_ids:
            continue
        title = a.raw_data.get("Award Title", "")
        if title:
            to_embed.append((a.id, a.entity_id, title))

    if not to_embed:
        print("All SBIR awards already embedded.")
        return 0

    print(f"Embedding {len(to_embed)} SBIR award titles...")
    start = time.time()

    # Batch encode
    titles = [t[2] for t in to_embed]
    embeddings = model.encode(titles, batch_size=batch_size, show_progress_bar=True)

    # Store in DB
    for i, (fe_id, entity_id, title) in enumerate(to_embed):
        emb = SbirEmbedding(
            funding_event_id=fe_id,
            entity_id=entity_id,
            award_title=title,
            embedding=serialize_embedding(embeddings[i]),
        )
        db.add(emb)

        if (i + 1) % 500 == 0:
            db.commit()

    db.commit()
    elapsed = time.time() - start
    print(f"Embedded {len(to_embed)} titles in {elapsed:.1f}s")
    return len(to_embed)


def load_all_embeddings(db):
    """Load all embeddings from DB into numpy arrays."""
    rows = db.query(SbirEmbedding).all()
    if not rows:
        return None, None, None

    embeddings = np.zeros((len(rows), EMBEDDING_DIM), dtype=np.float32)
    meta = []
    id_to_idx = {}

    for i, row in enumerate(rows):
        embeddings[i] = deserialize_embedding(row.embedding)
        meta.append({
            "entity_id": row.entity_id,
            "funding_event_id": row.funding_event_id,
            "award_title": row.award_title,
        })
        id_to_idx[row.funding_event_id] = i

    # L2 normalize for cosine similarity via dot product
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    return embeddings, meta, id_to_idx


def find_similar_to_company(db, model, company_name, top_n=10):
    """Find companies with similar SBIR technology focus."""
    # Find the entity
    entity = db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{company_name}%"),
        Entity.merged_into_id.is_(None),
    ).first()

    if not entity:
        print(f"Entity not found matching: {company_name}")
        return

    print(f"\nTarget: {entity.canonical_name}")

    # Get this company's SBIR embeddings
    company_embs = db.query(SbirEmbedding).filter(
        SbirEmbedding.entity_id == entity.id
    ).all()

    if not company_embs:
        print(f"  No SBIR awards found for this company.")
        return

    print(f"  SBIR Awards ({len(company_embs)}):")
    for e in company_embs:
        print(f"    - {e.award_title}")

    # Build query vector: average of all company's award embeddings
    vecs = np.array([deserialize_embedding(e.embedding) for e in company_embs])
    query_vec = vecs.mean(axis=0)
    query_vec = query_vec / np.linalg.norm(query_vec)

    # Load all embeddings
    all_embs, all_meta, _ = load_all_embeddings(db)
    if all_embs is None:
        print("No embeddings in database. Run with --embed first.")
        return

    # Compute similarities
    similarities = all_embs @ query_vec

    # Group by entity - take max similarity per entity
    entity_scores = {}
    entity_titles = {}
    for i, meta in enumerate(all_meta):
        eid = meta["entity_id"]
        if eid == entity.id:
            continue  # Skip self
        sim = float(similarities[i])
        if eid not in entity_scores or sim > entity_scores[eid]:
            entity_scores[eid] = sim
            entity_titles[eid] = meta["award_title"]

    # Rank
    ranked = sorted(entity_scores.items(), key=lambda x: -x[1])

    print(f"\n{'='*80}")
    print(f"  TOP {top_n} COMPANIES SIMILAR TO {entity.canonical_name}")
    print(f"{'='*80}")
    print(f"\n{'Rank':<5} {'Company':<42} {'Sim':>5} {'Best Matching Award'}")
    print("-" * 100)

    for i, (eid, score) in enumerate(ranked[:top_n], 1):
        e = db.query(Entity).filter(Entity.id == eid).first()
        name = e.canonical_name[:40] if e else "Unknown"
        title = entity_titles[eid][:50]
        print(f"{i:<5} {name:<42} {score:>5.3f} {title}")

        # Show all matching titles for top 3
        if i <= 3:
            all_titles = db.query(SbirEmbedding.award_title).filter(
                SbirEmbedding.entity_id == eid
            ).all()
            for (t,) in all_titles:
                print(f"      {'':42}       - {t[:70]}")


def find_similar_to_query(db, model, query_text, top_n=10):
    """Find companies matching a free-text technology query."""
    print(f'\nQuery: "{query_text}"')

    # Encode the query
    query_vec = model.encode([query_text])[0]
    query_vec = query_vec / np.linalg.norm(query_vec)

    # Load all embeddings
    all_embs, all_meta, _ = load_all_embeddings(db)
    if all_embs is None:
        print("No embeddings in database. Run with --embed first.")
        return

    similarities = all_embs @ query_vec

    # Group by entity
    entity_scores = {}
    entity_titles = {}
    for i, meta in enumerate(all_meta):
        eid = meta["entity_id"]
        sim = float(similarities[i])
        if eid not in entity_scores or sim > entity_scores[eid]:
            entity_scores[eid] = sim
            entity_titles[eid] = meta["award_title"]

    ranked = sorted(entity_scores.items(), key=lambda x: -x[1])

    print(f"\n{'='*80}")
    print(f"  TOP {top_n} COMPANIES FOR: {query_text}")
    print(f"{'='*80}")
    print(f"\n{'Rank':<5} {'Company':<42} {'Sim':>5} {'Best Matching Award'}")
    print("-" * 100)

    for i, (eid, score) in enumerate(ranked[:top_n], 1):
        e = db.query(Entity).filter(Entity.id == eid).first()
        name = e.canonical_name[:40] if e else "Unknown"
        title = entity_titles[eid][:50]
        print(f"{i:<5} {name:<42} {score:>5.3f} {title}")


def main():
    parser = argparse.ArgumentParser(description="Semantic search over SBIR awards")
    parser.add_argument("--company", type=str, help="Find companies similar to this one")
    parser.add_argument("--query", type=str, help="Free-text technology query")
    parser.add_argument("--top", type=int, default=10, help="Number of results (default 10)")
    parser.add_argument("--embed", action="store_true", help="(Re)generate embeddings")
    args = parser.parse_args()

    db = SessionLocal()
    model = load_model()

    # Always ensure embeddings are up to date
    count = db.query(func.count(SbirEmbedding.id)).scalar() or 0
    if count == 0 or args.embed:
        generate_embeddings(db, model)

    if args.company:
        find_similar_to_company(db, model, args.company, args.top)
    elif args.query:
        find_similar_to_query(db, model, args.query, args.top)
    elif not args.embed:
        parser.print_help()

    db.close()


if __name__ == "__main__":
    main()
