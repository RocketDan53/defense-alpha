"""
Knowledge Graph — Relationship Materialization and Path Queries

Materializes implicit relationships from funding_events, contracts, and
policy_alignment into the explicit `relationships` table, enabling graph
traversal and path queries.

Usage:
    from processing.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(db_session)
    kg.materialize_all()
    path = kg.find_path(company_id, "Space Force", max_hops=3)
"""

import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session

from processing.models import (
    Contract,
    Entity,
    FundingEvent,
    FundingEventType,
    Relationship,
    RelationshipType,
)

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """Materializes and queries the knowledge graph."""

    def __init__(self, db: Session):
        self.db = db

    def materialize_all(self, clear_existing: bool = True):
        """Materialize all relationship types."""
        if clear_existing:
            count = self.db.query(Relationship).delete()
            self.db.commit()
            logger.info(f"Cleared {count} existing relationships")

        self.materialize_agency_funded()
        self.materialize_agency_contracted()
        self.materialize_policy_alignment()
        self.db.commit()

        total = self.db.query(Relationship).count()
        logger.info(f"Total relationships materialized: {total:,}")

    def materialize_agency_funded(self):
        """Create FUNDED_BY_AGENCY edges from SBIR awards."""
        logger.info("Materializing FUNDED_BY_AGENCY relationships...")

        rows = self.db.execute(text("""
            SELECT
                fe.entity_id,
                fe.investors_awarders,
                COUNT(*) as award_count,
                COALESCE(SUM(fe.amount), 0) as total_value,
                MIN(fe.event_date) as first_date,
                MAX(fe.event_date) as last_date
            FROM funding_events fe
            JOIN entities e ON fe.entity_id = e.id
            WHERE e.merged_into_id IS NULL
              AND fe.event_type IN ('SBIR_PHASE_1', 'SBIR_PHASE_2', 'SBIR_PHASE_3')
              AND fe.investors_awarders IS NOT NULL
            GROUP BY fe.entity_id, fe.investors_awarders
        """)).fetchall()

        count = 0
        for entity_id, awarders_json, award_count, total_value, first_dt, last_dt in rows:
            try:
                awarders = json.loads(awarders_json) if isinstance(awarders_json, str) else awarders_json or []
            except (json.JSONDecodeError, TypeError):
                continue

            for awarder in awarders:
                if not isinstance(awarder, str) or not awarder.strip():
                    continue
                rel = Relationship(
                    source_entity_id=entity_id,
                    relationship_type=RelationshipType.FUNDED_BY_AGENCY,
                    target_name=awarder.strip(),
                    weight=Decimal(str(total_value)),
                    properties={"award_count": award_count},
                    first_observed=_parse_date(first_dt),
                    last_observed=_parse_date(last_dt),
                )
                self.db.add(rel)
                count += 1

        self.db.flush()
        logger.info(f"  Created {count:,} FUNDED_BY_AGENCY relationships")

    def materialize_agency_contracted(self):
        """Create CONTRACTED_BY_AGENCY edges from contracts table."""
        logger.info("Materializing CONTRACTED_BY_AGENCY relationships...")

        rows = self.db.execute(text("""
            SELECT
                c.entity_id,
                c.contracting_agency,
                COUNT(*) as contract_count,
                COALESCE(SUM(c.contract_value), 0) as total_value,
                MIN(c.award_date) as first_date,
                MAX(c.award_date) as last_date
            FROM contracts c
            JOIN entities e ON c.entity_id = e.id
            WHERE e.merged_into_id IS NULL
              AND c.contracting_agency IS NOT NULL
            GROUP BY c.entity_id, c.contracting_agency
        """)).fetchall()

        count = 0
        for entity_id, agency, contract_count, total_value, first_dt, last_dt in rows:
            rel = Relationship(
                source_entity_id=entity_id,
                relationship_type=RelationshipType.CONTRACTED_BY_AGENCY,
                target_name=agency,
                weight=Decimal(str(total_value)),
                properties={"contract_count": contract_count},
                first_observed=_parse_date(first_dt),
                last_observed=_parse_date(last_dt),
            )
            self.db.add(rel)
            count += 1

        self.db.flush()
        logger.info(f"  Created {count:,} CONTRACTED_BY_AGENCY relationships")

    def materialize_policy_alignment(self):
        """Create ALIGNED_TO_POLICY edges from policy_alignment scores."""
        logger.info("Materializing ALIGNED_TO_POLICY relationships...")

        entities = self.db.query(Entity).filter(
            Entity.merged_into_id.is_(None),
            Entity.policy_alignment.isnot(None),
        ).all()

        count = 0
        for entity in entities:
            pa = entity.policy_alignment or {}
            scores = pa.get("scores", {})
            scored_date = pa.get("scored_date")

            for priority, score in scores.items():
                if score and float(score) >= 0.3:  # Only meaningful alignments
                    rel = Relationship(
                        source_entity_id=entity.id,
                        relationship_type=RelationshipType.ALIGNED_TO_POLICY,
                        target_name=priority,
                        weight=Decimal(str(score)),
                        properties={
                            "top_priorities": pa.get("top_priorities", []),
                            "policy_tailwind": pa.get("policy_tailwind_score"),
                        },
                        first_observed=_parse_date(scored_date),
                    )
                    self.db.add(rel)
                    count += 1

        self.db.flush()
        logger.info(f"  Created {count:,} ALIGNED_TO_POLICY relationships")

    # ====================================================================
    # Path Queries
    # ====================================================================

    def find_connections(
        self, entity_id: str, max_hops: int = 2,
    ) -> list[dict]:
        """
        Find all connections from an entity within N hops.

        Returns list of paths, each path being a list of edges.
        """
        visited = {entity_id}
        paths = []
        current_frontier = [{"entity_id": entity_id, "path": []}]

        for hop in range(max_hops):
            next_frontier = []
            for node in current_frontier:
                eid = node["entity_id"]
                current_path = node["path"]

                # Get outgoing edges
                edges = self.db.query(Relationship).filter(
                    Relationship.source_entity_id == eid
                ).all()

                for edge in edges:
                    edge_info = {
                        "from_entity_id": eid,
                        "relationship": edge.relationship_type.value,
                        "to_entity_id": edge.target_entity_id,
                        "to_name": edge.target_name,
                        "weight": float(edge.weight) if edge.weight else None,
                    }

                    new_path = current_path + [edge_info]
                    paths.append(new_path)

                    # Follow entity-to-entity edges for next hop
                    if edge.target_entity_id and edge.target_entity_id not in visited:
                        visited.add(edge.target_entity_id)
                        next_frontier.append({
                            "entity_id": edge.target_entity_id,
                            "path": new_path,
                        })

                # Get incoming edges (reverse traversal)
                incoming = self.db.query(Relationship).filter(
                    Relationship.target_entity_id == eid
                ).all()

                for edge in incoming:
                    if edge.source_entity_id not in visited:
                        edge_info = {
                            "from_entity_id": edge.source_entity_id,
                            "relationship": edge.relationship_type.value,
                            "to_entity_id": eid,
                            "to_name": None,
                            "weight": float(edge.weight) if edge.weight else None,
                        }
                        new_path = current_path + [edge_info]
                        paths.append(new_path)
                        visited.add(edge.source_entity_id)
                        next_frontier.append({
                            "entity_id": edge.source_entity_id,
                            "path": new_path,
                        })

            current_frontier = next_frontier

        return paths

    def find_path_to_policy(
        self, entity_id: str, policy_signal: str,
    ) -> list[dict]:
        """
        Find how a company connects to a policy signal.

        Example: "How does Company X connect to Space Force policy?"
        → Company X → SBIR Phase II (Air Force) → space_resilience 0.9
          → Space Force signal → Q+1 Reg D response
        """
        paths = []

        # Get entity info
        entity = self.db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity:
            return paths

        # 1. Policy alignment connection
        policy_edges = self.db.query(Relationship).filter(
            Relationship.source_entity_id == entity_id,
            Relationship.relationship_type == RelationshipType.ALIGNED_TO_POLICY,
            Relationship.target_name == policy_signal,
        ).all()

        for edge in policy_edges:
            paths.append({
                "description": f"{entity.canonical_name} is aligned to {policy_signal} "
                              f"(score: {edge.weight})",
                "edge_type": "policy_alignment",
                "score": float(edge.weight) if edge.weight else 0,
            })

        # 2. Agency funding connection
        agency_edges = self.db.query(Relationship).filter(
            Relationship.source_entity_id == entity_id,
            Relationship.relationship_type.in_([
                RelationshipType.FUNDED_BY_AGENCY,
                RelationshipType.CONTRACTED_BY_AGENCY,
            ]),
        ).all()

        for edge in agency_edges:
            paths.append({
                "description": f"{entity.canonical_name} → {edge.relationship_type.value} → "
                              f"{edge.target_name} (${float(edge.weight or 0)/1e6:.1f}M)",
                "edge_type": edge.relationship_type.value,
                "agency": edge.target_name,
                "value": float(edge.weight) if edge.weight else 0,
            })

        return paths

    def get_entity_graph(
        self, entity_id: str,
    ) -> dict:
        """
        Get all relationships for an entity (for visualization).

        Returns nodes and edges in a format suitable for NetworkX.
        """
        entity = self.db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity:
            return {"nodes": [], "edges": []}

        nodes = [{
            "id": entity_id,
            "label": entity.canonical_name,
            "type": "company",
        }]
        edges = []

        # Outgoing relationships
        rels = self.db.query(Relationship).filter(
            Relationship.source_entity_id == entity_id
        ).all()

        for rel in rels:
            target_id = rel.target_entity_id or rel.target_name
            target_label = rel.target_name
            if rel.target_entity_id:
                target = self.db.query(Entity).filter(
                    Entity.id == rel.target_entity_id).first()
                target_label = target.canonical_name if target else target_id

            nodes.append({
                "id": target_id,
                "label": target_label,
                "type": rel.relationship_type.value,
            })
            edges.append({
                "source": entity_id,
                "target": target_id,
                "type": rel.relationship_type.value,
                "weight": float(rel.weight) if rel.weight else 1.0,
            })

        return {"nodes": nodes, "edges": edges}

    def get_ecosystem_graph(
        self, policy_area: str, min_score: float = 0.5,
        max_entities: int = 50,
    ) -> dict:
        """
        Get the graph for an entire policy ecosystem (e.g., "space_resilience").

        Returns nodes and edges for visualization.
        """
        # Get entities aligned to this policy area
        aligned = self.db.query(Relationship).filter(
            Relationship.relationship_type == RelationshipType.ALIGNED_TO_POLICY,
            Relationship.target_name == policy_area,
            Relationship.weight >= Decimal(str(min_score)),
        ).order_by(Relationship.weight.desc()).limit(max_entities).all()

        entity_ids = [r.source_entity_id for r in aligned]
        nodes = []
        edges = []
        seen_nodes = set()

        # Add the policy area as a central node
        policy_node_id = f"policy:{policy_area}"
        nodes.append({
            "id": policy_node_id,
            "label": policy_area.replace("_", " ").title(),
            "type": "policy",
            "size": 30,
        })
        seen_nodes.add(policy_node_id)

        for rel in aligned:
            entity = self.db.query(Entity).filter(
                Entity.id == rel.source_entity_id).first()
            if not entity:
                continue

            entity_node_id = entity.id
            if entity_node_id not in seen_nodes:
                nodes.append({
                    "id": entity_node_id,
                    "label": entity.canonical_name,
                    "type": "company",
                    "size": float(rel.weight) * 10 if rel.weight else 5,
                })
                seen_nodes.add(entity_node_id)

            edges.append({
                "source": entity_node_id,
                "target": policy_node_id,
                "type": "aligned_to_policy",
                "weight": float(rel.weight) if rel.weight else 0.5,
            })

            # Get agency connections for this entity
            agency_rels = self.db.query(Relationship).filter(
                Relationship.source_entity_id == entity.id,
                Relationship.relationship_type.in_([
                    RelationshipType.FUNDED_BY_AGENCY,
                    RelationshipType.CONTRACTED_BY_AGENCY,
                ]),
            ).all()

            for ar in agency_rels:
                agency_id = f"agency:{ar.target_name}"
                if agency_id not in seen_nodes:
                    nodes.append({
                        "id": agency_id,
                        "label": ar.target_name,
                        "type": "agency",
                        "size": 15,
                    })
                    seen_nodes.add(agency_id)

                edges.append({
                    "source": entity_node_id,
                    "target": agency_id,
                    "type": ar.relationship_type.value,
                    "weight": float(ar.weight) if ar.weight else 1.0,
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "policy_area": policy_area,
                "min_score": min_score,
                "entity_count": len(entity_ids),
            },
        }

    def stats(self) -> dict:
        """Get graph statistics."""
        total = self.db.query(Relationship).count()
        by_type = self.db.query(
            Relationship.relationship_type,
            func.count(Relationship.id),
        ).group_by(Relationship.relationship_type).all()

        return {
            "total_relationships": total,
            "by_type": {rt.value: count for rt, count in by_type},
        }


def _parse_date(val) -> Optional[date]:
    """Parse a date value that may be string or date."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except (ValueError, IndexError):
            return None
    return None
