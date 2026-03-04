#!/usr/bin/env python3
"""
Run signal detection on the defense intelligence database.

Usage:
    python scripts/detect_signals.py                                    # Run all detection algorithms
    python scripts/detect_signals.py --types kop_alignment              # Run specific detector(s)
    python scripts/detect_signals.py --types kop_alignment sbir_lapse_risk  # Multiple specific detectors
    python scripts/detect_signals.py --all                              # Explicitly run all detectors
    python scripts/detect_signals.py --summary                          # Show signal summary only
    python scripts/detect_signals.py --top 20                           # Show top 20 signals
    python scripts/detect_signals.py --lookback 180                     # Look back 180 days
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.signal_detector import SignalDetector, get_signal_summary, get_top_signals

# Mapping from signal type names to detector method names
DETECTOR_MAP = {
    "sbir_transitions": "detect_sbir_transitions",
    "first_dod_contract": "detect_first_dod_contracts",
    "rapid_growth": "detect_rapid_growth",
    "high_priority_tech": "detect_high_priority_tech",
    "multi_agency": "detect_multi_agency_interest",
    "outsized_award": "detect_outsized_awards",
    "sbir_to_contract": "detect_sbir_to_contract",
    "sbir_to_vc": "detect_sbir_to_vc_raise",
    "sbir_validated_raise": "detect_sbir_validated_raise",
    "sbir_stalled": "detect_sbir_stalled",
    "customer_concentration": "detect_customer_concentration",
    "sbir_graduation_speed": "detect_sbir_graduation_speed",
    "time_to_contract": "detect_time_to_contract",
    "funding_velocity": "detect_funding_velocity",
    "gone_stale": "detect_gone_stale",
    # MEIA/KOP/JAR detectors
    "kop_alignment": "detect_kop_alignment",
    "commercial_pathway_fit": "detect_commercial_pathway",
    "sbir_lapse_risk": "detect_sbir_lapse_risk",
    "meia_experimentation": "detect_meia_experimentation",
    "jar_funding": "detect_jar_funding",
    "pae_portfolio": "detect_pae_portfolio",
}

# Detectors that require a cutoff_date argument
CUTOFF_DETECTORS = {
    "detect_sbir_transitions",
    "detect_first_dod_contracts",
    "detect_rapid_growth",
    "detect_multi_agency_interest",
    "detect_outsized_awards",
}


def main():
    parser = argparse.ArgumentParser(description="Detect intelligence signals")
    parser.add_argument("--summary", action="store_true", help="Show signal summary only")
    parser.add_argument("--top", type=int, default=0, help="Show top N signals")
    parser.add_argument("--lookback", type=int, default=365, help="Days to look back")
    parser.add_argument("--types", nargs="+", help="Run specific detector type(s)")
    parser.add_argument("--all", action="store_true", help="Run all detectors (default)")
    args = parser.parse_args()

    db = SessionLocal()

    if args.summary:
        print("\n" + "=" * 60)
        print("SIGNAL SUMMARY")
        print("=" * 60)
        summary = get_signal_summary(db)
        print(f"Total active signals: {summary['total_active_signals']}")
        print("\nBy type:")
        for signal_type, count in sorted(summary['by_type'].items(), key=lambda x: -x[1]):
            print(f"  {signal_type}: {count}")
        db.close()
        return

    if args.top:
        print("\n" + "=" * 60)
        print(f"TOP {args.top} SIGNALS")
        print("=" * 60)
        signals = get_top_signals(db, args.top)
        for i, s in enumerate(signals, 1):
            print(f"\n{i}. {s['entity_name']}")
            print(f"   Type: {s['signal_type']}")
            print(f"   Confidence: {s['confidence']:.0%}")
            print(f"   Detected: {s['detected_date']}")
            if s['evidence']:
                for key, val in s['evidence'].items():
                    if key != 'entity_name':
                        print(f"   {key}: {val}")
        db.close()
        return

    detector = SignalDetector(db)

    if args.types:
        # Run specific detectors
        print("\n" + "=" * 60)
        print("SIGNAL DETECTION ENGINE (selective)")
        print("=" * 60)
        print(f"Running detectors: {', '.join(args.types)}")
        print()

        cutoff_date = date.today() - timedelta(days=args.lookback)
        results = {}
        for type_name in args.types:
            if type_name not in DETECTOR_MAP:
                print(f"WARNING: Unknown detector type '{type_name}'. Available: {', '.join(sorted(DETECTOR_MAP.keys()))}")
                continue
            method_name = DETECTOR_MAP[type_name]
            method = getattr(detector, method_name)
            if method_name in CUTOFF_DETECTORS:
                results[type_name] = method(cutoff_date)
            else:
                results[type_name] = method()

        db.commit()

        print("Detection Results:")
        print("-" * 40)
        for category, stats in results.items():
            print(f"\n{category}:")
            for key, val in stats.items():
                print(f"  {key}: {val}")

        print("\n" + "=" * 60)
        print(f"Signals created: {detector.signals_created}")
        print(f"Signals updated: {detector.signals_updated}")
        print("=" * 60)
    else:
        # Run all detectors (default or --all)
        print("\n" + "=" * 60)
        print("SIGNAL DETECTION ENGINE")
        print("=" * 60)
        print(f"Lookback period: {args.lookback} days")
        print()

        results = detector.detect_all_signals(lookback_days=args.lookback)

        print("Detection Results:")
        print("-" * 40)

        for category, stats in results['details'].items():
            print(f"\n{category}:")
            for key, val in stats.items():
                print(f"  {key}: {val}")

        print("\n" + "=" * 60)
        print(f"Signals created: {results['signals_created']}")
        print(f"Signals updated: {results['signals_updated']}")
        print("=" * 60)

    # Show summary
    print("\n" + "=" * 60)
    print("FINAL SIGNAL SUMMARY")
    print("=" * 60)
    summary = get_signal_summary(db)
    print(f"Total active signals: {summary['total_active_signals']}")
    print("\nBy type:")
    for signal_type, count in sorted(summary['by_type'].items(), key=lambda x: -x[1]):
        print(f"  {signal_type}: {count}")

    db.close()


if __name__ == "__main__":
    main()
