from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from jsonschema import ValidationError

from .demo import seed_demo
from .engine import challenge, discover
from .ingest import import_csv, ingest
from .report import export, markdown
from .store import Store


def parser():
    p = argparse.ArgumentParser(prog="pharma", description="PHARMA-SCOPE | Evidence-first terminal research")
    p.add_argument("--data-dir", default=".pharma", help="SQLite and archive folder (default: .pharma)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check setup without printing API keys")
    research = sub.add_parser("investigate", help="Autonomously research a company using public sources")
    research.add_argument("company", nargs="?")
    research.add_argument("--resume", help="Resume a saved investigation ID")
    research.add_argument("--provider", choices=["gemini", "openai"])
    research.add_argument("--model")
    research.add_argument("--years", type=int, default=5)
    research.add_argument("--seconds", type=int, default=600)
    research.add_argument("--max-searches", type=int, default=16)
    research.add_argument("--max-sources", type=int, default=18)
    research.add_argument("--max-model-calls", type=int, default=30)
    research.add_argument("--rounds", type=int, default=2)
    research.add_argument("--json", action="store_true")
    research.add_argument("--tui", action="store_true")
    research.add_argument("--output", type=Path)
    demo = sub.add_parser("demo", help="Seed fictional disclosures and investigate DEMO")
    demo.add_argument("--tui", action="store_true", help="Open the terminal workbench after seeding")
    demo.add_argument("--json", action="store_true")
    ing = sub.add_parser("ingest", help="Archive a local PDF or text source")
    ing.add_argument("path", type=Path)
    for name in ["company", "title", "publisher", "published"]:
        ing.add_argument("--" + name, required=True)
    ing.add_argument("--url", default="")
    sub.add_parser("sources", help="List source IDs and provenance").add_argument("--company")
    sub.add_parser("import", help="Import source-anchored geographic revenue CSV").add_argument("path", type=Path)
    ext = sub.add_parser("extract", help="Optional OpenAI extraction; previews JSON unless --commit is set")
    ext.add_argument("source_id")
    ext.add_argument("--pages", required=True, help="Physical pages, e.g. 15,16,20-22")
    ext.add_argument("--model")
    ext.add_argument("--commit", action="store_true", help="Import validated output; manual table review is still required")
    disc = sub.add_parser("discover", help="Investigate geographic revenue drift")
    disc.add_argument("--company", required=True)
    disc.add_argument("--threshold", type=float, default=5)
    disc.add_argument("--years", type=int, default=5)
    disc.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="Read a saved investigation")
    show.add_argument("run", nargs="?", default="latest")
    show.add_argument("--json", action="store_true")
    ch = sub.add_parser("challenge", help="Retrieve archived evidence for an alternative explanation")
    ch.add_argument("finding")
    ch.add_argument("question")
    ch.add_argument("--run", default="latest")
    ev = sub.add_parser("evidence", help="Inspect an observation and its source passage")
    ev.add_argument("observation")
    out = sub.add_parser("export", help="Export a portable evidence dossier")
    out.add_argument("run", nargs="?", default="latest")
    out.add_argument("--format", choices=["html", "json", "md"], default="html")
    out.add_argument("--output", type=Path)
    tui = sub.add_parser("tui", help="Open the interactive terminal workbench")
    tui.add_argument("run", nargs="?", default="latest")
    return p


def parse_pages(value):
    selected = set()
    for token in value.split(","):
        parts = token.strip().split("-")
        if len(parts) == 1:
            selected.add(int(parts[0]))
        elif len(parts) == 2:
            start, end = map(int, parts)
            if start > end or end - start > 1000:
                raise ValueError("Invalid page range.")
            selected.update(range(start, end + 1))
        else:
            raise ValueError("Use page ranges such as 15,16,20-22.")
    return sorted(selected)


def main(argv=None):
    from .config import load_env
    load_env()
    args = parser().parse_args(argv)
    store = None
    try:
        store = Store(args.data_dir)
        if args.command == "doctor":
            from .config import doctor
            print(json.dumps(doctor(), indent=2))
        elif args.command == "investigate":
            from .agent import Limits, ResearchAgent
            from .providers import Model
            limits = Limits(seconds=args.seconds, searches=args.max_searches, sources=args.max_sources,
                            model_calls=args.max_model_calls, rounds=args.rounds)
            def progress(entry):
                print(f"[{entry['stage']}] {entry['message']}", file=sys.stderr)
            agent = ResearchAgent(store, model=Model(args.provider, args.model), limits=limits, emit=progress)
            try:
                run = agent.run(args.company, years=args.years, resume=args.resume)
            except Exception:
                latest = store.db.execute("SELECT id FROM agent_states ORDER BY updated DESC LIMIT 1").fetchone()
                if latest:
                    print(f"Checkpoint retained. Resume with: python -m pharma_scope investigate --resume {latest['id']}", file=sys.stderr)
                raise
            destination = args.output or store.root / "exports" / (run["id"] + ".html")
            export(store, run, destination, "html")
            print(json.dumps(run, indent=2) if args.json else markdown(run))
            print(f"Report: {destination.resolve()}", file=sys.stderr)
            if args.tui:
                from .tui import launch
                launch(store.root, run["id"])
        elif args.command == "demo":
            run = seed_demo(store)
            if args.tui:
                from .tui import launch
                launch(store.root, run["id"])
            else:
                print(json.dumps(run, indent=2) if args.json else markdown(run))
        elif args.command == "ingest":
            sid = ingest(store, args.path, args.company, args.title, args.publisher, args.published, args.url)
            print(json.dumps({"source_id": sid, "status": "archived"}))
        elif args.command == "sources":
            print(json.dumps([{k: v for k, v in s.items() if k != "pages"} for s in store.sources(args.company)], indent=2))
        elif args.command == "import":
            print(json.dumps({"imported": import_csv(store, args.path)}))
        elif args.command == "extract":
            from .ai import extract
            print(json.dumps(extract(store, args.source_id, parse_pages(args.pages), args.model, args.commit), indent=2))
        elif args.command == "discover":
            def progress(e):
                if not args.json:
                    print(f"[{e['stage']}] {e['message']}", file=sys.stderr)
            run = discover(store, args.company, args.threshold, args.years, progress)
            print(json.dumps(run, indent=2) if args.json else markdown(run))
        elif args.command == "show":
            run = store.run(args.run)
            print(json.dumps(run, indent=2) if args.json else markdown(run, store.challenges(run["id"])))
        elif args.command == "challenge":
            print(json.dumps(challenge(store, args.run, args.finding, args.question), indent=2))
        elif args.command == "evidence":
            row = store.db.execute("SELECT * FROM observations WHERE id=?", (args.observation,)).fetchone()
            if row is None:
                raise ValueError("Unknown observation ID.")
            src = next(s for s in store.sources() if s["id"] == row["source_id"])
            print(json.dumps({"observation": dict(row), "source": {k: v for k, v in src.items() if k != "pages"}}, indent=2))
        elif args.command == "export":
            run = store.run(args.run)
            path = args.output or store.root / "exports" / f"{run['id']}.{args.format}"
            print(export(store, run, path, args.format))
        elif args.command == "tui":
            store.run(args.run)  # Friendly error before entering an alternate terminal screen.
            from .tui import launch
            launch(store.root, args.run)
        return 0
    except (ValueError, OSError, ImportError, ValidationError) as exc:
        print(f"pharma: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
