"""Command-line entry point for evaluation (#12).

megatron-eval data/local/ru --run     # run the backend (LLM_BACKEND, DEPARTMENTS_PATH) on
                                      # test.jsonl, then report every results file of the set
megatron-eval data/local/ru           # report only: baselines + out/eval/ru/*.jsonl
megatron-eval data/local/ru --results out/a.jsonl out/b.jsonl
megatron-eval data/local/ru --part dev --run --name gpt-prompt-v2   # prompt tuning on dev

The set directory is what `megatron-testset` writes: dev.jsonl (trains the baselines),
test.jsonl (scored) and gold.yaml (fields). A run appends to out/eval/<set>/<model>.jsonl
and skips requests already there, so an interrupted run of a slow model resumes.
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

from megatron.departments import DepartmentsConfig, load_departments
from megatron.evaluation import (
    Result,
    department_report,
    load_results,
    majority_baseline,
    model_report,
    render,
    tfidf_baseline,
)
from megatron.inputs import Request, load_requests
from megatron.llm import (
    BackendError,
    ExtractionError,
    Extractor,
    add_llm_arguments,
    build_extractor,
)
from megatron.prompt import PROMPT_VERSION
from megatron.routing import route
from megatron.settings import Settings
from megatron.testset import load_gold


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron-eval",
        description="Score backends and baselines on a test set built by megatron-testset.",
    )
    parser.add_argument("set", type=Path, help="directory with dev.jsonl, test.jsonl, gold.yaml")
    parser.add_argument(
        "--part",
        choices=["test", "dev"],
        default="test",
        help="test: reported numbers (gold.yaml); dev: prompt tuning (gold-dev.yaml, no baselines)",
    )
    parser.add_argument(
        "--run", action="store_true", help="run the configured backend on the part first"
    )
    parser.add_argument(
        "--name", help="with --run: results file name, e.g. a prompt variant (default: the model)"
    )
    add_llm_arguments(parser)
    parser.add_argument("--limit", type=int, help="with --run: only the first N test requests")
    parser.add_argument(
        "--results",
        type=Path,
        nargs="+",
        help="results files to score (default: every .jsonl in the output directory)",
    )
    parser.add_argument(
        "--train", type=Path, help="requests that train the baselines (default: dev.jsonl)"
    )
    parser.add_argument(
        "--out", type=Path, help="output directory (default: out/eval/<set>, <set>-dev for dev)"
    )
    parser.add_argument("--rounds", type=int, default=1000, help="bootstrap resamples (1000)")
    parser.add_argument("--seed", type=int, default=0)
    return parser


def run_backend(
    extractor: Extractor, config: DepartmentsConfig, requests: list[Request], path: Path
) -> bool:
    """Append a result per request not yet in `path`; False if the backend became unusable."""
    done = {str(r.id) for r in load_results(path)} if path.exists() else set()
    todo = [r for r in requests if str(r.id) not in done]
    print(f"{extractor.model}: {len(done)} done, {len(todo)} to go -> {path}", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    for i, request in enumerate(todo, 1):
        result = Result(
            id=request.id,
            request=request.text,
            expected=request.expected,
            model=extractor.model,
            prompt=PROMPT_VERSION,
        )
        start = time.perf_counter()
        try:
            extraction = extractor.extract_detailed(request.text)
        except ExtractionError as e:
            result.error = str(e)
        except BackendError as e:
            print(f"error: {e}", file=sys.stderr)
            return False
        else:
            result.ticket = route(extraction.ticket, config)
            result.attempts = extraction.attempts
            result.dropped_identifiers = extraction.dropped_identifiers
        result.seconds = round(time.perf_counter() - start, 1)
        verdict = "failed" if result.ticket is None else result.best_fit
        mark = "✓" if result.best_fit == request.expected else "✗"
        # Flushed: without a terminal (docker compose run -T, a log file) output is buffered.
        line = f"[{i}/{len(todo)}] {result.seconds:.1f} s · {verdict} {mark} {request.expected}"
        print(line, flush=True)
        # One line at a time, so an interrupted run keeps what it has done.
        # Only top-level None values are left out: the ticket's null fields must stay.
        record = {k: v for k, v in result.model_dump(mode="json").items() if v is not None}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def model_slug(model: str) -> str:
    return re.sub(r"[^\w.-]+", "-", model).strip("-")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    dev = args.part == "dev"
    name = f"{args.set.name}-dev" if dev else args.set.name
    out = args.out or Path("out/eval") / name
    test = load_requests(args.set / f"{args.part}.jsonl")
    train = load_requests(args.train or args.set / "dev.jsonl")
    gold_path = args.set / ("gold-dev.yaml" if dev else "gold.yaml")
    gold = load_gold(gold_path) if gold_path.exists() else []

    if args.run:
        settings = Settings().with_llm(args.backend, args.model)
        config = load_departments(settings.departments_path)
        unknown = sorted({r.expected for r in test if r.expected} - set(config.ids))
        if unknown:
            print(f"error: {unknown} are not in {settings.departments_path}", file=sys.stderr)
            return 2
        extractor = build_extractor(config, settings)
        path = out / f"{args.name or model_slug(extractor.model)}.jsonl"
        if not run_backend(extractor, config, test[: args.limit], path):
            return 1

    paths = args.results or sorted(out.glob("*.jsonl"))
    truth = [r.expected or "" for r in test]
    # On dev the baselines would be scored on their own training data.
    baselines = (
        {}
        if dev
        else {
            f"majority class ({len(train)} train)": majority_baseline(train, test),
            f"TF-IDF + logreg ({len(train)} train)": tfidf_baseline(train, test),
        }
    )
    reports = [
        department_report(name, list(zip(truth, predicted, strict=True)), args.rounds, args.seed)
        for name, predicted in baselines.items()
    ]
    for path in paths:
        results = load_results(path)
        if len(results) < len(test):
            print(f"note: {path} has {len(results)} of {len(test)} requests", file=sys.stderr)
        reports.append(model_report(path.stem, results, gold, args.rounds, args.seed))

    report = render(name, reports)
    print("\n" + report)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"saved to {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
