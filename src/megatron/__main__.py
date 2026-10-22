"""Command-line entry point: `megatron "request text"`."""

import argparse

from megatron import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron",
        description="Turn a free-text support request into a JSON ticket.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("text", nargs="?", help="request text")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.text is None:
        parser.print_help()
        return 0
    # The pipeline (LLM adapter, validation, routing) arrives in #8-#13.
    print("Pipeline is not implemented yet.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
