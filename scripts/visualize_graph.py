#!/usr/bin/env python3
"""
Network Visualization for the Knowledge Graph

Generates interactive HTML visualizations of the defense technology ecosystem
using NetworkX for analysis and Pyvis for rendering. Output is a standalone
HTML file that can be embedded in reports or opened in a browser.

Usage:
    # Visualize a policy ecosystem (e.g., space resilience)
    python scripts/visualize_graph.py --ecosystem space_resilience

    # Visualize with more entities
    python scripts/visualize_graph.py --ecosystem autonomous_systems --max-entities 60

    # Visualize a single company's connections
    python scripts/visualize_graph.py --entity "Anduril"

    # Export to specific file
    python scripts/visualize_graph.py --ecosystem space_resilience -o reports/space_graph.html

    # Static PNG export (requires matplotlib)
    python scripts/visualize_graph.py --ecosystem space_resilience --format png
"""

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.knowledge_graph import KnowledgeGraph
from processing.models import Entity

PROJECT_ROOT = Path(__file__).parent.parent

# Color scheme
COLORS = {
    "company": "#4A90D9",       # Blue
    "policy": "#E74C3C",        # Red
    "agency": "#2ECC71",        # Green
    "investor": "#9B59B6",      # Purple
    "technology": "#F39C12",    # Orange
}

# Relationship colors
EDGE_COLORS = {
    "aligned_to_policy": "#E74C3C",
    "funded_by_agency": "#2ECC71",
    "contracted_by_agency": "#27AE60",
    "invested_in_by": "#9B59B6",
    "similar_technology": "#F39C12",
    "competes_with": "#95A5A6",
}


def build_networkx_graph(graph_data: dict) -> nx.Graph:
    """Convert knowledge graph data to NetworkX graph."""
    G = nx.Graph()

    for node in graph_data["nodes"]:
        G.add_node(
            node["id"],
            label=node["label"],
            node_type=node["type"],
            size=node.get("size", 10),
        )

    for edge in graph_data["edges"]:
        G.add_edge(
            edge["source"],
            edge["target"],
            edge_type=edge["type"],
            weight=edge.get("weight", 1.0),
        )

    return G


def compute_graph_metrics(G: nx.Graph) -> dict:
    """Compute graph analysis metrics."""
    metrics = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
    }

    if G.number_of_nodes() > 0:
        # Degree centrality
        degree_cent = nx.degree_centrality(G)
        top_central = sorted(degree_cent.items(), key=lambda x: -x[1])[:10]
        metrics["top_central_nodes"] = [
            {"id": nid, "centrality": round(cent, 4),
             "label": G.nodes[nid].get("label", nid)}
            for nid, cent in top_central
        ]

        # Connected components
        components = list(nx.connected_components(G))
        metrics["connected_components"] = len(components)
        metrics["largest_component_size"] = max(len(c) for c in components) if components else 0

        # Community detection (if graph is large enough)
        if G.number_of_nodes() >= 5:
            try:
                communities = nx.community.greedy_modularity_communities(G)
                metrics["communities"] = len(communities)
                metrics["community_sizes"] = sorted(
                    [len(c) for c in communities], reverse=True
                )[:10]
            except Exception:
                pass

    return metrics


def render_pyvis(
    graph_data: dict, output_path: Path,
    title: str = "Defense Technology Ecosystem",
    height: str = "800px",
    width: str = "100%",
):
    """Render interactive HTML visualization using Pyvis."""
    from pyvis.network import Network

    net = Network(
        height=height,
        width=width,
        bgcolor="#1a1a2e",
        font_color="white",
        directed=False,
        notebook=False,
    )

    # Physics settings for good layout
    net.set_options(json.dumps({
        "physics": {
            "enabled": True,
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "centralGravity": 0.005,
                "springLength": 150,
                "springConstant": 0.08,
                "damping": 0.4,
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 200},
        },
        "nodes": {
            "font": {"size": 12, "face": "Inter, sans-serif"},
            "borderWidth": 2,
        },
        "edges": {
            "smooth": {"type": "continuous"},
            "color": {"inherit": False},
        },
        "interaction": {
            "hover": True,
            "tooltipDelay": 200,
        },
    }))

    # Add nodes
    for node in graph_data["nodes"]:
        node_type = node["type"]
        color = COLORS.get(node_type, "#888888")
        size = node.get("size", 10)

        # Shape by type
        shape = "dot"
        if node_type == "policy":
            shape = "diamond"
            size = max(size, 25)
        elif node_type == "agency":
            shape = "square"
            size = max(size, 15)

        label = node["label"]
        if len(label) > 25:
            label = label[:22] + "..."

        net.add_node(
            node["id"],
            label=label,
            title=f"{node['label']}\nType: {node_type}",
            color=color,
            size=size,
            shape=shape,
        )

    # Add edges
    for edge in graph_data["edges"]:
        edge_type = edge["type"]
        color = EDGE_COLORS.get(edge_type, "#555555")
        weight = min(edge.get("weight", 1.0), 10.0)

        net.add_edge(
            edge["source"],
            edge["target"],
            color=color,
            width=max(0.5, weight / 2),
            title=edge_type.replace("_", " ").title(),
        )

    # Add title as HTML
    net.heading = title

    net.save_graph(str(output_path))
    return output_path


def render_static(
    graph_data: dict, output_path: Path,
    title: str = "Defense Technology Ecosystem",
    figsize: tuple = (16, 12),
):
    """Render static PNG/SVG using matplotlib."""
    import matplotlib.pyplot as plt

    G = build_networkx_graph(graph_data)

    fig, ax = plt.subplots(1, 1, figsize=figsize, facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Layout
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    # Draw by node type
    for node_type, color in COLORS.items():
        nodelist = [n for n, d in G.nodes(data=True) if d.get("node_type") == node_type]
        if nodelist:
            sizes = [G.nodes[n].get("size", 10) * 20 for n in nodelist]
            nx.draw_networkx_nodes(
                G, pos, nodelist=nodelist, node_color=color,
                node_size=sizes, alpha=0.9, ax=ax,
            )

    # Draw edges by type
    for edge_type, color in EDGE_COLORS.items():
        edgelist = [(u, v) for u, v, d in G.edges(data=True) if d.get("edge_type") == edge_type]
        if edgelist:
            nx.draw_networkx_edges(
                G, pos, edgelist=edgelist, edge_color=color,
                alpha=0.4, width=0.8, ax=ax,
            )

    # Labels
    labels = {n: d.get("label", n)[:20] for n, d in G.nodes(data=True)}
    nx.draw_networkx_labels(
        G, pos, labels=labels, font_size=6,
        font_color="white", ax=ax,
    )

    ax.set_title(title, color="white", fontsize=16, pad=20)
    ax.margins(0.1)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close()
    return output_path


def find_entity_by_name(db, name: str) -> Entity | None:
    return db.query(Entity).filter(
        Entity.canonical_name.ilike(f"%{name}%"),
        Entity.merged_into_id.is_(None),
    ).first()


def main():
    parser = argparse.ArgumentParser(description="Knowledge graph visualization")
    parser.add_argument("--ecosystem", type=str, help="Policy area to visualize")
    parser.add_argument("--entity", type=str, help="Entity name to visualize")
    parser.add_argument("--max-entities", type=int, default=40, help="Max entities")
    parser.add_argument("--min-score", type=float, default=0.5, help="Min policy alignment score")
    parser.add_argument("-o", "--output", type=str, help="Output file path")
    parser.add_argument("--format", choices=["html", "png", "svg"], default="html",
                        help="Output format (default: html)")

    args = parser.parse_args()

    db = SessionLocal()
    kg = KnowledgeGraph(db)

    # Check relationships exist
    stats = kg.stats()
    if stats["total_relationships"] == 0:
        print("No relationships found. Run: python scripts/build_graph.py --materialize")
        db.close()
        return

    if args.ecosystem:
        graph_data = kg.get_ecosystem_graph(
            args.ecosystem,
            min_score=args.min_score,
            max_entities=args.max_entities,
        )
        title = f"Defense Technology Ecosystem: {args.ecosystem.replace('_', ' ').title()}"

    elif args.entity:
        entity = find_entity_by_name(db, args.entity)
        if not entity:
            print(f"No entity found matching '{args.entity}'")
            db.close()
            return
        graph_data = kg.get_entity_graph(entity.id)
        title = f"Knowledge Graph: {entity.canonical_name}"

    else:
        parser.print_help()
        db.close()
        return

    # Compute metrics
    G = build_networkx_graph(graph_data)
    metrics = compute_graph_metrics(G)

    print(f"\nGraph: {title}")
    print(f"  Nodes: {metrics['nodes']}")
    print(f"  Edges: {metrics['edges']}")
    if "communities" in metrics:
        print(f"  Communities: {metrics['communities']}")
    if "top_central_nodes" in metrics:
        print(f"\n  Most central nodes:")
        for n in metrics["top_central_nodes"][:5]:
            print(f"    {n['label']:<40} centrality: {n['centrality']:.4f}")

    # Render
    if args.output:
        output_path = Path(args.output)
    else:
        safe_name = (args.ecosystem or args.entity or "graph").replace(" ", "_").lower()
        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        ext = args.format
        output_path = reports_dir / f"graph_{safe_name}.{ext}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "html":
        render_pyvis(graph_data, output_path, title=title)
    else:
        render_static(graph_data, output_path, title=title)

    print(f"\n  Visualization saved to {output_path}")
    db.close()


if __name__ == "__main__":
    main()
