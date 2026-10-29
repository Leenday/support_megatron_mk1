"""Command-line entry point.

megatron "request text"
megatron --file requests.txt     # one request per line
megatron --file requests.jsonl   # {"text": ..., "expected": <department>} per line
megatron ... -o out/result.json  # save instead of printing (JSON Lines with --file)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from megatron import __version__
from megatron.departments import load_departments
from megatron.inputs import Request, RequestFileError, load_requests
from megatron.llm import BackendError, ExtractionError, build_extractor
from megatron.routing import route
from megatron.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron",
        description="Turn a free-text support request into a JSON ticket.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("text", nargs="?", help="request text")
    source.add_argument(
        "--file",
        type=Path,
        help="requests: .txt with one per line, or .jsonl with a `text` (and `expected`) key",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="save the ticket as JSON (with --file: one result per line, JSON Lines)",
    )
    return parser


def write_output(path: Path, results: list[dict[str, Any]], *, lines: bool) -> None:
    """JSON Lines keep the request, ticket or error and time per line, ready for evaluation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
    else:
        text = json.dumps(results[0]["ticket"], ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.file:
        try:
            requests = load_requests(args.file)
        except RequestFileError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    elif args.text:
        requests = [Request(text=args.text)]
    else:
        parser.print_help()
        return 0

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    config = load_departments(settings.departments_path)
    unknown = sorted({r.expected for r in requests if r.expected} - set(config.ids))
    if unknown:
        path = settings.departments_path
        print(f"error: expected departments {unknown} are not in {path}", file=sys.stderr)
        return 2
    extractor = build_extractor(config, settings)
    print(f"model: {extractor.model} at {extractor.endpoint}", file=sys.stderr)

    results: list[dict[str, Any]] = []
    failed = correct = 0
    for i, request in enumerate(requests, 1):
        if len(requests) > 1:
            print(f"\n=== {i}/{len(requests)} ===")
        print(f"> {request.text}")
        fields = {"id": request.id, "request": request.text, "expected": request.expected}
        record: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        start = time.perf_counter()
        try:
            ticket = extractor.extract(request.text)
        except ExtractionError as e:
            failed += 1
            print(f"error: {e}")
            results.append(record | {"error": str(e)})
            continue
        except BackendError as e:
            # Unreachable server or a rejected key: the remaining requests would fail the same way.
            failed += 1
            print(f"error: {e}")
            break
        seconds = round(time.perf_counter() - start, 1)
        ticket = route(ticket, config)
        if args.output is None:
            print(ticket.model_dump_json(indent=2))
        best_fit = ticket.candidates[0]
        moved = f" (best fit {best_fit} is busy)" if ticket.department != best_fit else ""
        verdict = ""
        if request.expected:
            # The expected department is the one that fits the request, so it is compared
            # with the model's best fit: a ticket moved for load is not a model error.
            hit = best_fit == request.expected
            correct += hit
            verdict = f" · expected {request.expected} {'✓' if hit else '✗'}"
        print(f"→ {ticket.department}{moved} · {seconds:.1f} s{verdict}")
        results.append(record | {"ticket": ticket.model_dump(), "seconds": seconds})

    labelled = sum(1 for r in requests if r.expected)
    if labelled:
        print(f"\ndepartment correct: {correct}/{labelled}")

    # A single request that failed leaves no file: there is no ticket to save.
    if args.output and (args.file or not failed):
        write_output(args.output, results, lines=args.file is not None)
        print(f"saved to {args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
