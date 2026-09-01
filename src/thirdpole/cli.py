"""tpw — Third Pole Watch CLI."""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tpw", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("replay", help="replay a reference event from archives")
    rp.add_argument("event", help="trishuli2026 | chamoli2021")
    rp.add_argument("--out", default="out")

    sub.add_parser("watch", help="run the live SeedLink watch")

    sc = sub.add_parser("scan", help="backstop archive scan of the trailing window")
    sc.add_argument("--hours", type=float, default=2.0)

    lg = sub.add_parser("ledger", help="candidate ledger")
    lgs = lg.add_subparsers(dest="lcmd", required=True)
    lgs.add_parser("stats")
    lgs.add_parser("list")
    lb = lgs.add_parser("label")
    lb.add_argument("index", type=int)
    lb.add_argument("verdict", choices=["real", "false", "ambiguous"])
    lb.add_argument("--note", default="")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    try:  # use the OS trust store so corporate/proxy CAs work like they do for curl
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

    if args.cmd == "replay":
        from . import replay
        return replay.run(args.event, args.out)
    if args.cmd == "watch":
        from . import daemon
        return daemon.run()
    if args.cmd == "scan":
        from . import scan
        return scan.run(args.hours)
    if args.cmd == "ledger":
        from . import ledger
        if args.lcmd == "stats":
            print(json.dumps(ledger.stats(), indent=2))
        elif args.lcmd == "list":
            for i, row in enumerate(ledger.load()):
                print(i, json.dumps(row))
        else:
            ledger.label(args.index, args.verdict, args.note)
            print("labeled.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
