"""Command-line entry point.

megatron "request text"
megatron --file requests.txt     # one request per line
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from megatron import __version__
from megatron.departments import load_departments
from megatron.llm import ExtractionError, build_extractor
from megatron.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron",
        description="Turn a free-text support request into a JSON ticket.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("text", nargs="?", help="request text")
    source.add_argument("--file", type=Path, help="file with one request per line")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.file:
        lines = args.file.read_text(encoding="utf-8").splitlines()
        requests = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    elif args.text:
        requests = [args.text]
    else:
        parser.print_help()
        return 0

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    config = load_departments(settings.departments_path)
    extractor = build_extractor(config, settings)
    print(f"model: {settings.ollama_model} at {settings.ollama_base_url}", file=sys.stderr)

    failed = 0
    for i, text in enumerate(requests, 1):
        if len(requests) > 1:
            print(f"\n=== {i}/{len(requests)} ===")
        print(f"> {text}")
        start = time.perf_counter()
        try:
            ticket = extractor.extract(text)
        except ExtractionError as e:
            failed += 1
            print(f"error: {e}")
            continue
        print(ticket.model_dump_json(indent=2))
        print(f"→ {ticket.department} · {time.perf_counter() - start:.1f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
