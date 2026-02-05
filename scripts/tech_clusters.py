#!/usr/bin/env python3
"""
Cluster SBIR awards by technology area using embeddings + k-means.

Groups all SBIR award titles into semantic clusters and labels each
cluster by the most representative terms.

Usage:
    python scripts/tech_clusters.py                    # 20 clusters (default)
    python scripts/tech_clusters.py --n-clusters 30    # 30 clusters
    python scripts/tech_clusters.py --cluster 7        # Show details for cluster 7
"""

import argparse
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from sklearn.cluster import KMeans
from sqlalchemy import func

from processing.database import SessionLocal
from processing.models import Entity, SbirEmbedding

EMBEDDING_DIM = 384

# Stop words to exclude from cluster labels
STOP_WORDS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "to", "with", "on",
    "by", "at", "from", "as", "is", "it", "its", "that", "this", "be",
    "are", "was", "were", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "dare", "must", "ought", "used", "using",
    "use", "based", "new", "novel", "advanced", "phase", "ii", "iii",
    "sbir", "sttr", "via", "approach", "development", "system", "systems",
    "technology", "technologies", "solution", "solutions", "platform",
}


def deserialize_embedding(data: bytes) -> np.ndarray:
    n = len(data) // 4
    return np.array(struct.unpack(f"{n}f", data), dtype=np.float32)


def extract_terms(title: str) -> list[str]:
    """Extract meaningful terms from an award title."""
    # Remove parenthetical acronyms
    clean = re.sub(r"\([^)]*\)", "", title)
    # Tokenize
    words = re.findall(r"[a-zA-Z]{3,}", clean.lower())
    return [w for w in words if w not in STOP_WORDS]


def label_cluster(titles: list[str], n_terms: int = 4) -> str:
    """Generate a label from the most common terms in cluster titles."""
    all_terms = []
    for t in titles:
        all_terms.extend(extract_terms(t))

    counts = Counter(all_terms)
    top = [term for term, _ in counts.most_common(n_terms)]
    return ", ".join(top)


def run_clustering(db, n_clusters: int):
    """Run k-means clustering on SBIR embeddings."""
    rows = db.query(SbirEmbedding).all()
    if not rows:
        print("No embeddings found. Run: python scripts/find_similar.py --embed")
        return None

    print(f"Clustering {len(rows)} SBIR awards into {n_clusters} clusters...")

    embeddings = np.zeros((len(rows), EMBEDDING_DIM), dtype=np.float32)
    meta = []
    for i, row in enumerate(rows):
        embeddings[i] = deserialize_embedding(row.embedding)
        meta.append({
            "entity_id": row.entity_id,
            "award_title": row.award_title,
        })

    # L2 normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    # Build cluster info
    clusters = defaultdict(lambda: {"titles": [], "entity_ids": set()})
    for i, label in enumerate(labels):
        clusters[label]["titles"].append(meta[i]["award_title"])
        clusters[label]["entity_ids"].add(meta[i]["entity_id"])

    # Compute cluster compactness (avg distance to centroid)
    cluster_info = []
    for cid in range(n_clusters):
        mask = labels == cid
        if mask.sum() == 0:
            continue
        centroid = kmeans.cluster_centers_[cid]
        centroid_norm = centroid / np.linalg.norm(centroid)
        cluster_embs = embeddings[mask]
        avg_sim = float(np.mean(cluster_embs @ centroid_norm))

        entity_ids = clusters[cid]["entity_ids"]
        entity_names = []
        for eid in list(entity_ids)[:50]:
            e = db.query(Entity).filter(Entity.id == eid).first()
            if e:
                entity_names.append(e.canonical_name)

        cluster_info.append({
            "id": cid,
            "label": label_cluster(clusters[cid]["titles"]),
            "award_count": len(clusters[cid]["titles"]),
            "company_count": len(entity_ids),
            "avg_similarity": avg_sim,
            "titles": clusters[cid]["titles"],
            "entity_names": sorted(entity_names),
        })

    cluster_info.sort(key=lambda x: -x["company_count"])
    return cluster_info


def print_cluster_overview(clusters):
    """Print overview of all clusters."""
    print(f"\n{'='*90}")
    print(f"  SBIR TECHNOLOGY CLUSTERS ({len(clusters)} clusters)")
    print(f"{'='*90}")
    print(f"\n{'ID':>3} {'Companies':>9} {'Awards':>7} {'Cohesion':>8}  Topic")
    print("-" * 90)

    for c in clusters:
        print(
            f"{c['id']:>3} {c['company_count']:>9} {c['award_count']:>7} "
            f"{c['avg_similarity']:>8.3f}  {c['label']}"
        )

    total_awards = sum(c["award_count"] for c in clusters)
    total_companies = len(set().union(*(set() for c in clusters)))
    print(f"\nTotal: {total_awards} awards across {len(clusters)} clusters")


def print_cluster_detail(clusters, cluster_id):
    """Print detailed view of a single cluster."""
    target = None
    for c in clusters:
        if c["id"] == cluster_id:
            target = c
            break

    if not target:
        print(f"Cluster {cluster_id} not found.")
        return

    print(f"\n{'='*80}")
    print(f"  CLUSTER {target['id']}: {target['label']}")
    print(f"{'='*80}")
    print(f"  Companies: {target['company_count']}")
    print(f"  Awards: {target['award_count']}")
    print(f"  Cohesion: {target['avg_similarity']:.3f}")

    print(f"\n--- Companies ({target['company_count']}) ---")
    for name in target["entity_names"]:
        print(f"  {name}")

    print(f"\n--- Sample Awards (up to 15) ---")
    for title in target["titles"][:15]:
        print(f"  - {title[:90]}")


def main():
    parser = argparse.ArgumentParser(description="SBIR technology clustering")
    parser.add_argument("--n-clusters", type=int, default=20, help="Number of clusters")
    parser.add_argument("--cluster", type=int, default=None, help="Show details for cluster N")
    args = parser.parse_args()

    db = SessionLocal()
    clusters = run_clustering(db, args.n_clusters)

    if clusters is None:
        db.close()
        return

    if args.cluster is not None:
        print_cluster_detail(clusters, args.cluster)
    else:
        print_cluster_overview(clusters)

        # Show top 3 most cohesive clusters in detail
        by_cohesion = sorted(clusters, key=lambda x: -x["avg_similarity"])[:3]
        print(f"\n{'='*90}")
        print("  TOP 3 MOST COHESIVE CLUSTERS")
        print(f"{'='*90}")
        for c in by_cohesion:
            print(f"\nCluster {c['id']}: {c['label']} ({c['company_count']} companies)")
            for title in c["titles"][:5]:
                print(f"  - {title[:85]}")

    db.close()


if __name__ == "__main__":
    main()
