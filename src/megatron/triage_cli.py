"""Command-line entry point for the triage-time measurement (#43).

megatron-triage plan data/local/ru --results out/eval/ru/gpt-5.4-mini-v4.jsonl
    # 30 test requests outside the gold subset, with the service's tickets → out/triage/ru/
megatron-triage serve data/local/ru --participant p1          # the page at 127.0.0.1:8743
megatron-triage serve data/local/ru --participant p2 --swap   # the second participant
megatron-triage report data/local/ru                          # → out/triage/ru/report.md

The plan and the answers stay in out/ (git-ignored): they hold the requests' texts. Only the
report, which has aggregate numbers, is meant to be shared.
"""

import argparse
import contextlib
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import ValidationError

from megatron.departments import load_departments
from megatron.evaluation import load_results
from megatron.inputs import load_requests
from megatron.settings import Settings
from megatron.testset import load_gold
from megatron.triage import (
    Answer,
    build_plan,
    load_answers,
    load_plan,
    render,
    report,
    sequence,
    write_plan,
)


def out_dir(set_dir: Path) -> Path:
    return Path("out/triage") / set_dir.name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megatron-triage",
        description="Measure triage time: by hand against checking the service's tickets.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="pick the requests and split them into halves A and B")
    plan.add_argument("set", type=Path, help="directory with test.jsonl and gold.yaml")
    plan.add_argument("--results", type=Path, required=True, help="the service's answers")
    plan.add_argument("--size", type=int, default=30)
    plan.add_argument("--seed", type=int, default=43)
    plan.add_argument(
        "--with-gold", action="store_true", help="also use the gold requests (seen when labelling)"
    )
    serve = sub.add_parser("serve", help="the measurement page for one participant")
    serve.add_argument("set", type=Path)
    serve.add_argument("--participant", required=True, help="a name for the answers file")
    serve.add_argument("--swap", action="store_true", help="triage half B by hand instead of A")
    serve.add_argument("--port", type=int, default=8743)
    rep = sub.add_parser("report", help="the times and the reduction from all answers")
    rep.add_argument("set", type=Path)
    return parser


def make_plan(args: argparse.Namespace) -> int:
    requests = load_requests(args.set / "test.jsonl")
    gold = args.set / "gold.yaml"
    exclude = set() if args.with_gold or not gold.exists() else {str(g.id) for g in load_gold(gold)}
    plan = build_plan(
        requests, load_results(args.results), size=args.size, seed=args.seed, exclude=exclude
    )
    path = out_dir(args.set) / "plan.jsonl"
    write_plan(path, plan)
    halves = {h: sum(p.half == h for p in plan) for h in "AB"}
    print(f"{len(plan)} requests → {path} (A: {halves['A']}, B: {halves['B']})")
    return 0


# The measurement page; the request texts reach it only from this local server.
PAGE = Path(__file__).with_name("triage.html")


def serve(args: argparse.Namespace) -> int:
    directory = out_dir(args.set)
    plan = load_plan(directory / "plan.jsonl")
    order = sequence(plan, swap=args.swap)
    answers_path = directory / f"answers-{args.participant}.jsonl"
    config = load_departments(Settings().departments_path)
    departments = [
        {"id": d.id, "name": d.name_ru, "description": d.description} for d in config.departments
    ]
    unknown = {p.expected for p in plan if p.expected} - {d["id"] for d in departments}
    if unknown:
        print(f"DEPARTMENTS_PATH has no {sorted(unknown)}: set it to the set's config")
        return 2
    by_id = {p.id: p for p in plan}

    class Handler(BaseHTTPRequestHandler):
        def send(self, status: HTTPStatus, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data: object) -> None:
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send(HTTPStatus.OK, body, "application/json")

        def do_GET(self) -> None:
            if self.path == "/":
                self.send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/next":
                done = {a.id for a in load_answers(answers_path)}
                pending = [(p, m) for p, m in order if p.id not in done]
                item = None
                if pending:
                    p, mode = pending[0]
                    fields = p.service.model_dump() if mode == "service" else None
                    item = {"id": p.id, "mode": mode, "text": p.text, "fields": fields}
                self.send_json(
                    {
                        "item": item,
                        "done": len(order) - len(pending),
                        "total": len(order),
                        "departments": departments,
                    }
                )
            else:
                self.send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/api/answer":
                self.send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                data = json.loads(raw)
                answer = Answer(
                    participant=args.participant,
                    model_seconds=by_id[data["id"]].model_seconds,
                    **data,
                )
            except (ValueError, KeyError, ValidationError) as e:
                self.send(HTTPStatus.BAD_REQUEST, str(e).encode(), "text/plain; charset=utf-8")
                return
            if answer.id in {a.id for a in load_answers(answers_path)}:
                self.send(HTTPStatus.CONFLICT, b"already answered", "text/plain")
                return
            with answers_path.open("a", encoding="utf-8") as f:
                f.write(answer.model_dump_json() + "\n")
            self.send_json({"ok": True})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # the request texts must not end up in a terminal log

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"{args.participant}: {url}  (answers → {answers_path}; Ctrl+C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


def make_report(args: argparse.Namespace) -> int:
    directory = out_dir(args.set)
    plan = load_plan(directory / "plan.jsonl")
    answers = [a for path in sorted(directory.glob("answers-*.jsonl")) for a in load_answers(path)]
    result = report(answers, plan)
    text = render(args.set.name, result)
    (directory / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"plan": make_plan, "serve": serve, "report": make_report}[args.command](args)
    except (OSError, ValueError) as e:
        print(f"megatron-triage: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
