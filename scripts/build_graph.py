#!/usr/bin/env python3
"""
Build and query the knowledge graph.

Materializes relationships from funding_events, contracts, and policy_alignment
into the explicit relationships table, then supports graph queries.

Usage:
    # Materialize all relationships
    python scripts/build_graph.py --materialize

    # Show graph statistics
    python scripts/build_graph.py --stats

    # Find how a company connects to a policy area
    python scripts/build_graph.py --path "Anduril" --policy space_resilience

    # Show all connections for a company
    python scripts/build_graph.py --connections "SpaceX"

    # Export ecosystem graph for visualization
    python scripts/build_graph.py --ecosystem space_resilience --output results/space_graph.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal, init_db
from processing.knowledge_graph import KnowledgeGraph
from processing.models import Entity, Relationship

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def find_entity_by_name(db, name: str) -> Entity | None:
    """Find an entity by name substring."""
    entity = db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{name}%"),
        Entity.merged_into_id.is_(None),
    ).first()
    return entity


def main():
    parser = argparse.ArgumentParser(description="Build and query the knowledge graph")
    parser.add_argument("--materialize", action="store_true", help="Materialize all relationships")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    parser.add_argument("--path", type=str, help="Find paths from entity (name substring)")
    parser.add_argument("--policy", type=str, help="Policy area for --path (e.g., space_resilience)")
    parser.add_argument("--connections", type=str, help="Show all connections for entity")
    parser.add_argument("--ecosystem", type=str, help="Export ecosystem graph for policy area")
    parser.add_argument("--output", "-o", type=str, help="Output file for graph export")
    parser.add_argument("--max-entities", type=int, default=50, help="Max entities in ecosystem graph")

    args = parser.parse_args()

    db = SessionLocal()

    # Ensure the relationships table exists
    init_db()

    kg = KnowledgeGraph(db)

    if args.materialize:
        print("Materializing knowledge graph...")
        kg.materialize_all()
        stats = kg.stats()
        print(f"\nGraph built: {stats['total_relationships']:,} relationships")
        for rtype, count in sorted(stats["by_type"].items()):
            print(f"  {rtype:<30} {count:>8,}")

    elif args.stats:
        stats = kg.stats()
        if stats["total_relationships"] == 0:
            print("No relationships found. Run: python scripts/build_graph.py --materialize")
            db.close()
            return

        print(f"\nKnowledge Graph Statistics")
        print(f"{'='*50}")
        print(f"Total relationships: {stats['total_relationships']:,}")
        print()
        for rtype, count in sorted(stats["by_type"].items()):
            print(f"  {rtype:<30} {count:>8,}")

    elif args.path:
        entity = find_entity_by_name(db, args.path)
        if not entity:
            print(f"No entity found matching '{args.path}'")
            db.close()
            return

        if args.policy:
            paths = kg.find_path_to_policy(entity.id, args.policy)
            print(f"\nConnections: {entity.canonical_name} → {args.policy}")
            print("=" * 70)
            for p in paths:
                print(f"  {p['description']}")
        else:
            paths = kg.find_connections(entity.id, max_hops=2)
            print(f"\nAll connections from {entity.canonical_name} ({len(paths)} paths)")
            print("=" * 70)
            for path in paths[:30]:
                parts = []
                for edge in path:
                    target = edge["to_name"] or edge["to_entity_id"][:8]
                    parts.append(f"--{edge['relationship']}-->{target}")
                print(f"  {entity.canonical_name} {'  '.join(parts)}")

    elif args.connections:
        entity = find_entity_by_name(db, args.connections)
        if not entity:
            print(f"No entity found matching '{args.connections}'")
            db.close()
            return

        graph_data = kg.get_entity_graph(entity.id)
        print(f"\nGraph for {entity.canonical_name}")
        print(f"{'='*70}")
        print(f"  Nodes: {len(graph_data['nodes'])}")
        print(f"  Edges: {len(graph_data['edges'])}")
        print()

        for edge in graph_data["edges"]:
            # Find target label
            target_label = edge["target"]
            for node in graph_data["nodes"]:
                if node["id"] == edge["target"]:
                    target_label = node["label"]
                    break
            weight_str = f" (${edge['weight']/1e6:.1f}M)" if edge.get("weight", 0) > 1000 else ""
            print(f"  → [{edge['type']}] {target_label}{weight_str}")

    elif args.ecosystem:
        graph_data = kg.get_ecosystem_graph(
            args.ecosystem, max_entities=args.max_entities)

        print(f"\nEcosystem: {args.ecosystem}")
        print(f"{'='*70}")
        print(f"  Entities: {graph_data['metadata']['entity_count']}")
        print(f"  Nodes: {len(graph_data['nodes'])}")
        print(f"  Edges: {len(graph_data['edges'])}")

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(graph_data, f, indent=2)
            print(f"\n  Graph exported to {output_path}")
        else:
            # Print summary
            companies = [n for n in graph_data["nodes"] if n["type"] == "company"]
            agencies = [n for n in graph_data["nodes"] if n["type"] == "agency"]
            print(f"\n  Companies ({len(companies)}):")
            for c in companies[:15]:
                print(f"    {c['label']}")
            if len(companies) > 15:
                print(f"    ... and {len(companies) - 15} more")
            print(f"\n  Agencies ({len(agencies)}):")
            for a in agencies:
                print(f"    {a['label']}")

    else:
        parser.print_help()

    db.close()


if __name__ == "__main__":
    main()
