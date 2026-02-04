#!/usr/bin/env python3
"""
Tag SBIR entities with technology categories based on their award data.

Usage:
    python scripts/tag_sbir_entities.py --dry-run
    python scripts/tag_sbir_entities.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.models import Entity, FundingEvent, FundingEventType

# Technology keywords (expanded for better title matching)
TECHNOLOGY_KEYWORDS = {
    "ai_ml": [
        "artificial intelligence", "machine learning", "deep learning", "neural network",
        "computer vision", "natural language processing", "nlp", "reinforcement learning",
        "predictive analytics", "cognitive", "autonomous decision", "agentic", " ai ",
        "llm", "large language model", "generative ai",
    ],
    "autonomy": [
        "autonomous", "unmanned", "uav", "ugv", "usv", "uuv", "drone", "robotics",
        "robot", "self-driving", "automated", "swarm", "uas ", "suas", "counter-uas",
    ],
    "cyber": [
        "cyber", "cybersecurity", "encryption", "cryptograph", "malware", "intrusion",
        "network security", "zero trust", "penetration", "vulnerability", "secure ",
    ],
    "space": [
        "satellite", "spacecraft", "orbital", "space-based", "launch vehicle",
        "propulsion", "cislunar", "leo ", " geo ", "small sat", "cubesat",
        "space application", "in-space", "on-orbit",
    ],
    "quantum": [
        "quantum", "qubit", "quantum computing", "quantum sensing", "quantum communication",
        "quantum cryptography", "post-quantum",
    ],
    "hypersonics": [
        "hypersonic", "scramjet", "mach 5", "high-speed", "thermal protection",
        "hypersonic glide", "boost-glide", "reentry",
    ],
    "biotech": [
        "biotech", "biotechnology", "synthetic biology", "gene", "crispr", "biologic",
        "pharmaceutical", "vaccine", "therapeutic", "biomaterial", "biodefense",
        "medical", "health", "tissue",
    ],
    "sensors": [
        "sensor", "radar", "lidar", "sonar", "electro-optical", "infrared", "rf sensing",
        "imaging", "detection", "surveillance", "reconnaissance", "isr", "spectrometer",
        "optical", "camera", "night vision", "thermal", "multispectral", "hyperspectral",
    ],
    "communications": [
        "5g", "6g", "communications", "datalink", "mesh network", "satcom",
        "software defined radio", "sdr", "tactical network", "resilient comms",
        "antenna", "waveform", "radio", "wireless",
    ],
    "directed_energy": [
        "directed energy", "laser", "high-energy laser", "hel", "microwave",
        "high-powered microwave", "hpm", "particle beam", "beam control",
    ],
    "materials": [
        "metamaterial", "composite", "advanced material", "lightweight", "armor",
        "ceramic", "carbon fiber", "additive manufacturing", "3d printing", "additive",
        "coating", "alloy", "thermal", "insulation",
    ],
    "electronics": [
        "semiconductor", "microelectronics", "photonics", "fpga", "asic",
        "power electronics", "gan", "sic", "silicon carbide", "circuit", "chip",
    ],
    "c4isr": [
        "c4isr", "command and control", "battle management", "situational awareness",
        "targeting", "kill chain", "decision support", "mission planning",
    ],
    "ew": [
        "electronic warfare", " ew ", "jamming", "spoofing", "sigint", "elint",
        "spectrum", "counter-uas", "c-uas", "countermeasure",
    ],
    "simulation": [
        "simulation", "modeling", "synthetic", "digital twin", "virtual", "training",
        "lvc ", "live virtual",
    ],
    "manufacturing": [
        "manufacturing", "production", "machining", "casting", "forging", "assembly",
        "supply chain", "logistics",
    ],
}


def extract_tags(text: str) -> list[str]:
    """Extract technology tags from text."""
    tags = set()
    text_lower = text.lower()

    for tag_name, keywords in TECHNOLOGY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                tags.add(tag_name)
                break

    return sorted(list(tags))


def main():
    parser = argparse.ArgumentParser(description="Tag SBIR entities with technology categories")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tagged without making changes")
    args = parser.parse_args()

    db = SessionLocal()

    sbir_types = [FundingEventType.SBIR_PHASE_1, FundingEventType.SBIR_PHASE_2, FundingEventType.SBIR_PHASE_3]

    # Get all SBIR companies without tags
    sbir_entities = db.query(Entity).join(
        FundingEvent, FundingEvent.entity_id == Entity.id
    ).filter(
        FundingEvent.event_type.in_(sbir_types),
        Entity.merged_into_id.is_(None)
    ).distinct().all()

    # Filter to those without tags
    entities_to_tag = [e for e in sbir_entities if not e.technology_tags or len(e.technology_tags) == 0]

    print(f"SBIR entities without tags: {len(entities_to_tag)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    tagged_count = 0
    tag_distribution = {}

    for entity in entities_to_tag:
        # Get all SBIR awards for this entity
        awards = db.query(FundingEvent).filter(
            FundingEvent.entity_id == entity.id,
            FundingEvent.event_type.in_(sbir_types)
        ).all()

        # Combine all text from awards (Award Title is the main source since abstracts aren't stored)
        text_parts = []
        for award in awards:
            if award.raw_data:
                # Get award title (main text source)
                text_parts.append(award.raw_data.get("Award Title", "") or "")
                text_parts.append(award.raw_data.get("award_title", "") or "")
                # Branch can help with categorization
                text_parts.append(award.raw_data.get("Branch", "") or "")
                # Also check for any abstract if available
                text_parts.append(award.raw_data.get("Abstract", "") or "")
                text_parts.append(award.raw_data.get("Research Keywords", "") or "")

        combined_text = " ".join(str(s) for s in text_parts if s)

        if not combined_text.strip():
            continue

        tags = extract_tags(combined_text)

        if tags:
            tagged_count += 1
            for tag in tags:
                tag_distribution[tag] = tag_distribution.get(tag, 0) + 1

            print(f"  {entity.canonical_name[:45]:<45} | {tags}")

            if not args.dry_run:
                entity.technology_tags = tags

    if not args.dry_run:
        db.commit()

    print("=" * 60)
    print(f"Entities tagged: {tagged_count}")
    print("\nTag distribution:")
    for tag, count in sorted(tag_distribution.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {count}")

    db.close()


if __name__ == "__main__":
    main()
