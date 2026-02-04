#!/usr/bin/env python3
"""
Run signal detection on the defense intelligence database.

Usage:
    python scripts/detect_signals.py                    # Run all detection algorithms
    python scripts/detect_signals.py --summary         # Show signal summary only
    python scripts/detect_signals.py --top 20          # Show top 20 signals
    python scripts/detect_signals.py --lookback 180    # Look back 180 days
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.database import SessionLocal
from processing.signal_detector import SignalDetector, get_signal_summary, get_top_signals


def main():
    parser = argparse.ArgumentParser(description="Detect intelligence signals")
    parser.add_argument("--summary", action="store_true", help="Show signal summary only")
    parser.add_argument("--top", type=int, default=0, help="Show top N signals")
    parser.add_argument("--lookback", type=int, default=365, help="Days to look back")
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

    # Run full detection
    print("\n" + "=" * 60)
    print("SIGNAL DETECTION ENGINE")
    print("=" * 60)
    print(f"Lookback period: {args.lookback} days")
    print()

    detector = SignalDetector(db)
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
