#!/usr/bin/env python3
"""
RAG query CLI — ask natural language questions about the defense industrial base.

Connects semantic search over 27,529 SBIR award embeddings to entity intelligence
data (signals, contracts, funding, policy alignment) and optionally to Claude for
structured analysis.

Usage:
    # Show enriched context without calling Claude (verify retrieval quality):
    python scripts/rag_query.py "companies building counter-drone RF systems" --raw

    # Full RAG pipeline with Claude reasoning:
    python scripts/rag_query.py "who is working on jam-resistant tactical radios"

    # Filter and constrain:
    python scripts/rag_query.py "mesh networking for JADC2" \\
        --filter-business software --min-score 2.0 --top-k 30

    # Output entity rankings for report generation:
    python scripts/rag_query.py "autonomous underwater vehicles" --report
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.rag_engine import RAGEngine


def main():
    parser = argparse.ArgumentParser(
        description="RAG query — ask questions about the defense industrial base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  %(prog)s "counter-drone RF systems" --raw\n'
            '  %(prog)s "hypersonic thermal protection" --filter-business aerospace_platforms\n'
            '  %(prog)s "autonomous underwater vehicles" --report --max-results 10\n'
        ),
    )
    parser.add_argument(
        "question", type=str,
        help="Natural language question about defense companies/technologies",
    )
    parser.add_argument(
        "--filter-business", type=str, default=None,
        help="Filter by core_business (rf_hardware, software, aerospace_platforms, "
             "components, systems_integrator, services, other)",
    )
    parser.add_argument(
        "--min-score", type=float, default=0.0,
        help="Minimum composite score to include (default: 0.0)",
    )
    parser.add_argument(
        "--top-k", type=int, default=50,
        help="How many entities to retrieve from semantic search (default: 50)",
    )
    parser.add_argument(
        "--max-results", type=int, default=15,
        help="Max entities in final output (default: 15)",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Show enriched context without calling Claude (for debugging/verification)",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Output entity IDs + rankings as JSON (for generate_prospect_report.py)",
    )
    args = parser.parse_args()

    db = SessionLocal()

    # Only create Anthropic client when needed
    client = None
    if not args.raw and not args.report:
        from anthropic import Anthropic
        from config.settings import settings

        if not settings.ANTHROPIC_API_KEY:
            print(
                "ERROR: ANTHROPIC_API_KEY not set in environment. "
                "Use --raw to skip the Claude API call, or set the key in .env",
                file=sys.stderr,
            )
            sys.exit(1)
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Initialize engine (loads model + embeddings into memory)
    print("Initializing RAG engine...", file=sys.stderr)
    t0 = time.time()
    try:
        engine = RAGEngine(db, client=client)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Engine ready in {time.time() - t0:.1f}s", file=sys.stderr)

    # Build filters
    filters = {}
    if args.filter_business:
        filters["core_business"] = args.filter_business
    if args.min_score > 0:
        filters["min_composite"] = args.min_score

    if args.raw:
        _run_raw_mode(engine, args, filters)
    elif args.report:
        _run_report_mode(engine, args, filters)
    else:
        _run_full_mode(engine, args, filters)

    db.close()


def _run_raw_mode(engine, args, filters):
    """Retrieve + enrich + build context, print to stdout. No Claude call."""
    print(f'\nQuery: "{args.question}"', file=sys.stderr)
    print("Retrieving...", file=sys.stderr)

    results = engine.retrieve(args.question, top_k=args.top_k)

    if not results:
        print("\nNo entities found above similarity threshold.", file=sys.stderr)
        return

    print(f"Retrieved {len(results)} entities. Enriching...", file=sys.stderr)
    enriched = engine.enrich(results)

    if filters:
        enriched = engine._apply_filters(enriched, filters)

    enriched = enriched[:args.max_results]

    if not enriched:
        print("\nNo entities remaining after filters.", file=sys.stderr)
        return

    context = engine.build_context(enriched)

    # Status summary to stderr
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"  RAG CONTEXT — {len(enriched)} entities", file=sys.stderr)
    print(f'  Query: "{args.question}"', file=sys.stderr)
    print(f"  Estimated tokens: {len(context) // 4}", file=sys.stderr)
    if filters:
        print(f"  Filters: {filters}", file=sys.stderr)
    print(f"{'=' * 70}\n", file=sys.stderr)

    # Full context to stdout
    print(context)


def _run_report_mode(engine, args, filters):
    """Output entity IDs + rankings as JSON for report generation."""
    print(f'\nQuery: "{args.question}"', file=sys.stderr)

    results = engine.retrieve(args.question, top_k=args.top_k)
    if not results:
        print("[]")
        return

    enriched = engine.enrich(results)

    if filters:
        enriched = engine._apply_filters(enriched, filters)

    enriched = enriched[:args.max_results]

    report_data = []
    for i, e in enumerate(enriched, 1):
        report_data.append({
            "rank": i,
            "entity_id": e.entity_id,
            "name": e.name,
            "similarity": round(e.similarity, 4),
            "composite_score": e.composite_score,
            "stage": e.activity["stage"],
        })

    # JSON to stdout
    print(json.dumps(report_data, indent=2))

    # Summary to stderr
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"  REPORT OUTPUT — {len(report_data)} entities", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    for r in report_data:
        print(
            f"  {r['rank']:>2}. {r['name']:<40} "
            f"sim={r['similarity']:.3f}  "
            f"composite={r['composite_score']:.2f}  "
            f"stage={r['stage']}",
            file=sys.stderr,
        )


def _run_full_mode(engine, args, filters):
    """Full RAG pipeline: retrieve → enrich → reason via Claude."""
    print(f'\nQuery: "{args.question}"', file=sys.stderr)
    print("Running full RAG pipeline...", file=sys.stderr)

    response = engine.query(
        args.question,
        top_k=args.top_k,
        filters=filters if filters else None,
        max_results=args.max_results,
    )

    output = {
        "question": response.question,
        "relevant_companies": response.relevant_companies,
        "watchlist": response.watchlist,
        "gaps": response.gaps,
        "summary": response.summary,
        "meta": {
            "entities_retrieved": response.entities_retrieved,
            "entities_enriched": response.entities_enriched,
            "context_tokens": response.context_tokens_estimate,
            "elapsed_seconds": round(response.elapsed_seconds, 2),
        },
    }

    print(json.dumps(output, indent=2))

    # Brief summary to stderr
    n_companies = len(response.relevant_companies)
    n_watchlist = len(response.watchlist)
    print(
        f"\n{n_companies} relevant companies, {n_watchlist} watchlist, "
        f"{response.elapsed_seconds:.1f}s elapsed",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
