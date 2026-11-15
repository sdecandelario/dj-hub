"""djhub: the DJ Hub command line (used by the dj-library Claude skill).

Same commands as the old djlib.py. Every change is a dry run unless --apply is
given; applied changes are stored as batches in the app database (visible in
History) and can be reverted with `undo`.

    uv run --project ~/Projects/dj-hub/backend djhub status
"""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from . import db
from .config import get_config
from .core import library as lib
from .db import session_scope
from .jobs import runner
from .models import Batch
from .services import analysis as _a, downloads as _d, legacy, library, playlists as _p  # noqa: F401
from .services import downloads


def _rel(path):
    return library.rel(path)


def print_plan(plan):
    for step in plan.steps:
        if step.action == "skip":
            print(f"skip   {_rel(step.source)}\n       -> {step.note}")
        else:
            verb = step.label if step.label in ("inbox", "reject", "trash") else step.action
            print(f"{verb:6} {_rel(step.source)}\n       -> {_rel(step.dest)}")
    counts = {}
    for step in plan.steps:
        key = step.label if step.label in ("inbox", "reject", "trash") else step.action
        counts[key] = counts.get(key, 0) + 1
    print("\n" + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) + (", " if counts else "")
          + f"{len(plan.problems)} problem(s)")
    for note in plan.notes:
        print(f"  NOTE: {note}")
    for problem in plan.problems:
        print(f"  PROBLEM: {problem}")


def run_change(kind, payload, apply):
    with session_scope() as s:
        plan = library.make_plan(s, kind, payload)
    print_plan(plan)
    if not apply:
        print("\nDry run. Nothing changed. Add --apply to run it.")
        return
    if not plan.runnable():
        print("\nNothing to apply.")
        return
    with session_scope() as s:
        batch_id = library.preview(s, kind, payload, label="").id
    result = library.apply(session_scope, batch_id)
    print(f"\nApplied {result['done']} change(s). Batch {batch_id} ({result['status']}). "
          f"Undo with: djhub undo --batch {batch_id} --apply")
    if result["error"]:
        sys.exit(f"  ERROR: {result['error']}")


def cmd_status(args):
    with session_scope() as s:
        report = lib.status(library.scan(s))
    print(f"Library: {get_config().root}")
    print(f"{report['files']} files, {report['songs']} different songs (not counting Rejected)\n")
    for kind in ("inbox", "genre", "session", "unsorted", "rejected"):
        rows = [r for r in report["folders"] if r["kind"] == kind]
        if rows:
            print(lib.KIND_LABELS[kind])
            for r in rows:
                print(f"  {r['count']:4}  {r['folder']}")
            print()
    print(f"Songs without a genre folder: {len(report['no_genre'])}")
    print(f"Songs in more than one genre: {len(report['multi_genre'])}")
    for song in report["multi_genre"][:20]:
        print(f"  {song['artist']} - {song['title']}: {', '.join(song['genres'])}")


def cmd_scan(args):
    with session_scope() as s:
        out = lib.to_sort(library.scan(s), args.folder)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_find(args):
    with session_scope() as s:
        hits = lib.find(library.scan(s), args.query)
    for copies in hits:
        print(f"{copies[0]['artist']} - {copies[0]['title']}")
        for c in copies:
            print(f"    {c['path']}")
    print(f"\n{len(hits)} song(s) found")


def cmd_dupes(args):
    with session_scope() as s:
        report = lib.dupes(library.scan(s))
    print("Same file saved under different names in one folder:")
    for d in report["same_file"]:
        print(f"  {d['folder']}: " + " | ".join(Path(p).name for p in d["files"]))
    print(f"  {len(report['same_file'])} found\n")
    print("Same artist and title but different files (other encode or version? check by ear):")
    for d in report["same_name"]:
        print(f"  {d['artist']} - {d['title']}")
        for p in d["files"]:
            print(f"      {p}")
    print(f"  {len(report['same_name'])} found")


def cmd_index(args):
    with session_scope() as s:
        out = [{k: t[k] for k in ("path", "kind", "folder", "artist", "title", "fp")} for t in library.scan(s)]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cmd_apply(args):
    run_change("apply", {"items": _load(args.plan)}, args.apply)


def cmd_remove(args):
    run_change("remove", {"paths": args.paths}, args.apply)


def cmd_fix_tags(args):
    run_change("tags", {"genre": args.genre}, args.apply)


def cmd_intake(args):
    run_change("intake", {"picks": _load(args.picks)}, args.apply)


def cmd_intake_decided(args):
    """Move the songs decided in the web app's Downloads page."""
    with session_scope() as s:
        picks, songs = downloads.picks(s)
    if not picks:
        print("No decided songs waiting. Pick versions on the Downloads page first.")
        return
    run_change("intake", {"picks": picks, "songs": songs}, args.apply)


def cmd_undo(args):
    with session_scope() as s:
        if args.batch:
            batch = s.get(Batch, int(args.batch)) if args.batch.isdigit() else None
            batch = batch or s.scalar(select(Batch).where(Batch.legacy_id == args.batch))
        else:
            batch = s.scalar(select(Batch).where(Batch.status.in_(("applied", "partial")), Batch.kind != "undo")
                             .order_by(Batch.id.desc()).limit(1))
        if batch is None:
            if args.batch:
                sys.exit(f"Batch {args.batch} not found.")
            print("Nothing to undo.")
            return
        print(f"Batch {batch.id}: {batch.label}")
        batch_id = batch.id
    run_change("undo", {"batch_id": batch_id}, args.apply)   # a BatchError exits non-zero in main()


def cmd_history(args):
    with session_scope() as s:
        for b in s.scalars(select(Batch).where(Batch.status != "discarded").order_by(Batch.id.desc()).limit(args.limit)):
            print(f"{b.id:5}  {b.created_at:%Y-%m-%d %H:%M}  {b.status:9} {b.label}")


def cmd_review(args):
    runner.run_sync("review_downloads", {}, echo=print)
    with session_scope() as s:
        view = downloads.review_view(s)
    if not view:
        return
    songs = view["songs"]
    print(f"\n{sum(len(x['versions']) for x in songs)} file(s), {len(songs)} song(s) waiting, "
          f"{sum(len(x['versions']) > 1 for x in songs)} with more than one version")
    print(f"{sum(1 for x in songs for v in x['versions'] if v['identical_to'])} file(s) have a byte-identical "
          f"copy; {sum(v['likely_transcode'] for x in songs for v in x['versions'])} likely transcode(s); "
          f"{sum(bool(x['in_library']) for x in songs)} song(s) already in the library; "
          f"{sum(bool(x['wanted_by']) for x in songs)} wanted by a playlist")
    print("Open the Downloads page in DJ Hub to listen and pick.")


def cmd_analyze(args):
    paths = [Path(p).expanduser() for p in args.paths]
    paths = [str(p if p.is_absolute() else get_config().root / p) for p in paths]
    runner.run_sync("analyze", {"paths": paths}, echo=print)


def cmd_refresh(args):
    runner.run_sync("spotify_refresh", {}, echo=print)


def cmd_scan_library(args):
    runner.run_sync("library_scan", {}, echo=print)


def _print_candidate(c):
    notes = ""
    if c.get("check"):
        notes += f"  [check: you may have {c['check']['artist']} - {c['check']['title']}]"
    if c.get("you_own"):
        notes += f"  [you already own {c['you_own']} track(s) by this artist]"
    for hit in c.get("in_playlists", []):
        notes += f"  [in playlist {hit['playlist']}" + (f", {hit['project']}" if hit["project"] else "") + "]"
    status = f" ({c['status']})" if c.get("status") and c["status"] != "new" else ""
    print(f"{c['id']:5}  {c['score']:7.2f}  {c['artist']} - {c['title']}{status}\n"
          f"                because: {', '.join(c['because'])}{notes}")


def cmd_discover(args):
    """Find new-song candidates for a genre folder with Last.fm and store them (no files change)."""
    from .integrations import lastfm
    from .services import discovery
    try:
        with session_scope() as s:
            result = discovery.discover(s, args.genre, artist_limit=args.artists, tracks_per_artist=args.tracks)
            discovery.save(s, result)
            seeds = ", ".join(f"{a} ({n:g})" for a, n in result["seeds"].items())
            rows = [c for c in discovery.list_candidates(s, genre=args.genre)
                    if c["status"] == "new" and (c["artist"], c["title"]) in
                    {(x["artist"], x["title"]) for x in result["candidates"]}]
    except (discovery.UnknownGenre, lastfm.LastfmError) as exc:
        sys.exit(str(exc))
    if args.json:
        json.dump({"genre": args.genre, "seeds": result["seeds"], "candidates": rows}, sys.stdout,
                  ensure_ascii=False, indent=1)
        print()
        return
    print(f"Seeds from Genres/{args.genre}: {seeds}")
    for c in rows:
        _print_candidate(c)
    print(f"\n{len(rows)} new candidate(s), none of them owned. Saved; mark them with: "
          f"djhub mark wanted|dismissed ID...  (nothing in the library changed)")


def cmd_candidates(args):
    from .services import discovery
    with session_scope() as s:
        rows = discovery.list_candidates(s, status=args.status, genre=args.genre)
    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return
    for c in rows:
        _print_candidate(c)
    print(f"\n{len(rows)} candidate(s)")


def cmd_mark(args):
    from .services import discovery
    try:
        with session_scope() as s:
            rows = discovery.set_status(s, args.ids, args.status)
            out = [f"{r.id} {r.artist} - {r.title}" for r in rows]
    except (KeyError, ValueError) as exc:
        sys.exit(str(exc.args[0]))
    print("\n".join(f"{args.status}: {line}" for line in out))


def cmd_import_legacy(args):
    with session_scope() as s:
        result = legacy.import_all(s, args.legacy_dir)
    print("Imported: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in result.items()))
    runner.run_sync("library_scan", {}, echo=print)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="djhub", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="folder counts and songs missing a genre").set_defaults(func=cmd_status)
    p = sub.add_parser("scan", help="JSON of songs to sort (default: songs without a genre)")
    p.add_argument("folder", nargs="?", help="only songs in this folder, relative to the root")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("find", help="every copy of songs matching the words")
    p.add_argument("query", nargs="+")
    p.set_defaults(func=cmd_find)
    p = sub.add_parser("apply", help="run a copy/move plan file")
    p.add_argument("plan")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_apply)
    p = sub.add_parser("remove", help="send copies to the Trash")
    p.add_argument("paths", nargs="+", help="files or folders, relative to the root")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_remove)
    p = sub.add_parser("fix-tags", help="fill missing artist/title tags from file names and optionally set genre tags to the genre folder")
    p.add_argument("--genre", action="store_true", help="also set the genre tag to the genre folder name")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_fix_tags)
    p = sub.add_parser("intake", help="move reviewed downloads (picks JSON) to 00 Inbox / 00 Rejected")
    p.add_argument("picks")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_intake)
    p = sub.add_parser("intake-decided", help="move the songs decided on the Downloads page")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_intake_decided)
    p = sub.add_parser("undo", help="revert the last applied batch, or --batch ID")
    p.add_argument("--batch")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_undo)
    p = sub.add_parser("history", help="recent batches")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)
    sub.add_parser("dupes", help="duplicate songs").set_defaults(func=cmd_dupes)
    sub.add_parser("index", help="JSON of every library file").set_defaults(func=cmd_index)
    sub.add_parser("review", help="measure and group the downloads (read-only)").set_defaults(func=cmd_review)
    p = sub.add_parser("analyze", help="loudness analysis of files or folders, in one run (read-only)")
    p.add_argument("paths", nargs="+", metavar="path")
    p.set_defaults(func=cmd_analyze)
    sub.add_parser("refresh-playlists", help="read the Spotify playlists and match them").set_defaults(
        func=cmd_refresh)
    sub.add_parser("scan-library", help="update the app's view of the library").set_defaults(func=cmd_scan_library)
    p = sub.add_parser("discover", help="new-song candidates for a genre folder, from Last.fm (stored, no files change)")
    p.add_argument("genre", help="genre folder name under Genres/")
    p.add_argument("--artists", type=int, default=20, help="how many similar artists to use")
    p.add_argument("--tracks", type=int, default=2, help="top tracks taken per artist")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_discover)
    p = sub.add_parser("candidates", help="stored new-song candidates")
    p.add_argument("--status", choices=("new", "wanted", "dismissed"))
    p.add_argument("--genre")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_candidates)
    p = sub.add_parser("mark", help="mark candidates wanted, dismissed (never suggested again) or new")
    p.add_argument("status", choices=("wanted", "dismissed", "new"))
    p.add_argument("ids", nargs="+", type=int)
    p.set_defaults(func=cmd_mark)
    p = sub.add_parser("import-legacy", help="import data from the old DJ projects (read-only on them)")
    p.add_argument("--legacy-dir")
    p.set_defaults(func=cmd_import_legacy)
    args = parser.parse_args(argv)
    if not get_config().root.is_dir():
        sys.exit(f"Library not found: {get_config().root}")
    db.migrate()
    try:
        args.func(args)
    except library.BatchError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
