"""Command-line entry point for building a test set from a ticket export (#7).

megatron-testset tickets.csv --text subject,body --label queue --filter language=en \\
    --per-label 15 --out data/local/en
megatron-testset export.jsonl --text text --label line --id id --strip-tracker-keys \\
    --out data/local/ru

Writes OUT/dev.jsonl and OUT/test.jsonl (requests for `megatron --file`) and, unless it
already exists, OUT/gold.yaml: a draft of the gold subset to check by hand.
"""

import argparse
import logging
import sys
from pathlib import Path

from megatron.testset import (
    TRACKER_KEY,
    TRACKER_LINK,
    draft_gold,
    label_counts,
    pick_gold,
    read_rows,
    sample,
    split,
    to_requests,
    write_gold,
    write_requests,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron-testset",
        description="Build dev/test request files and a gold draft from a ticket export.",
    )
    parser.add_argument("source", type=Path, help="ticket export: .csv with a header or .jsonl")
    parser.add_argument(
        "--text", required=True, help="comma-separated columns joined into the request text"
    )
    parser.add_argument("--label", required=True, help="column with the department/queue")
    parser.add_argument("--id", help="column with the ticket id (default: row number)")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="COLUMN=VALUE",
        help="keep only rows with this value (repeatable)",
    )
    parser.add_argument(
        "--strip-tracker-keys",
        action="store_true",
        help="remove issue-tracker keys (PROJ-123) and links to them: they give the label away",
    )
    parser.add_argument(
        "--leak",
        action="append",
        default=[],
        metavar="REGEX",
        help="remove matches of this regular expression from the text (repeatable)",
    )
    parser.add_argument("--per-label", type=int, help="take at most N requests of each label")
    parser.add_argument("--dev", type=float, default=0.3, help="share of the dev part (0.3)")
    parser.add_argument("--gold", type=int, default=30, help="size of the gold draft (30)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    filters = dict(f.split("=", 1) for f in args.filter)
    leaks = [*args.leak]
    if args.strip_tracker_keys:
        # Links first: removing the key alone would leave a broken URL behind.
        leaks = [TRACKER_LINK, TRACKER_KEY, *leaks]

    rows = [
        row
        for row in read_rows(args.source)
        if all(str(row.get(k)) == v for k, v in filters.items())
    ]
    try:
        requests = to_requests(rows, args.text.split(","), args.label, args.id, leaks)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    requests = sample(requests, args.per_label, args.seed)
    dev, test = split(requests, args.dev, args.seed)
    write_requests(args.out / "dev.jsonl", dev)
    write_requests(args.out / "test.jsonl", test)
    print(f"{len(rows)} rows -> {len(requests)} requests: dev {len(dev)}, test {len(test)}")
    for label, count in sorted(label_counts(requests).items()):
        print(f"  {label}: {count}")

    gold_path = args.out / "gold.yaml"
    if gold_path.exists():
        # The gold file holds hand-checked labels; a rerun must not overwrite them.
        print(f"{gold_path} exists, left as is")
    else:
        write_gold(gold_path, [draft_gold(r) for r in pick_gold(test, args.gold, args.seed)])
        print(f"gold draft: {gold_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
