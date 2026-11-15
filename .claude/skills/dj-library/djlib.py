#!/usr/bin/env python3
"""Organize the DJ library into genre and session folders.

Layout under the library root:
  00 Inbox/                      chosen downloads, waiting for a genre
  00 Rejected/<Artist - Title>/  download versions not chosen (final check)
  Genres/<genre>/                every song lives in exactly one genre folder
  Sessions/<session>/            a session: extra copies, any number per song
  files at the root, other folders  unsorted

`intake` moves reviewed downloads from the download folders (SOURCES) into
00 Inbox and 00 Rejected.

Every change is a dry run unless --apply is given. Applied changes are logged
to <root>/.djlib-log.jsonl and can be reverted with `undo`. Files are never
deleted: removals go to the macOS Trash.

Standard library only.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import unicodedata
from pathlib import Path

ROOT = Path(os.environ.get("DJ_TRACKS_ROOT", "~/Documents/DJ Tracks")).expanduser()
TRASH = Path(os.environ.get("DJ_TRASH", "~/.Trash")).expanduser()
AUDIO = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a"}
LOG_NAME = ".djlib-log.jsonl"
GENRES, INBOX, REJECTED, SESSIONS = "Genres", "00 Inbox", "00 Rejected", "Sessions"
RESERVED = {GENRES, INBOX, REJECTED, SESSIONS}
SOURCES = [Path(p).expanduser() for p in os.environ.get(
    "DJ_SOURCES", "~/.local/share/nicotine/downloads:~/Downloads").split(":") if p]
KIND_LABELS = {"genre": "Genres", "session": "Sessions", "inbox": "Inbox",
               "unsorted": "Unsorted", "rejected": "Rejected (final check)"}


# --- Tags -------------------------------------------------------------------


def _decode_text(payload):
    if not payload:
        return ""
    encoding, raw = payload[0], payload[1:]
    try:
        text = raw.decode({0: "latin-1", 1: "utf-16", 2: "utf-16-be"}.get(encoding, "utf-8"))
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    return " / ".join(p.strip() for p in text.split("\x00") if p.strip())


def _syncsafe(data):
    return (data[0] << 21) | (data[1] << 14) | (data[2] << 7) | data[3]


WANTED = {"TIT2": "title", "TPE1": "artist", "TCON": "genre", "TBPM": "bpm",
          "TT2": "title", "TP1": "artist", "TCO": "genre", "TBP": "bpm"}


def read_tags(path):
    """Return title, artist, genre and bpm from ID3v2 (2.2-2.4) or ID3v1 tags."""
    tags = {}
    try:
        with open(path, "rb") as handle:
            header = handle.read(10)
            if len(header) == 10 and header[:3] == b"ID3":
                major, flags = header[3], header[5]
                body = handle.read(_syncsafe(header[6:10]))
                if flags & 0x80 and major < 4:
                    body = body.replace(b"\xff\x00", b"\xff")
                pos = 0
                if flags & 0x40 and major >= 3:
                    pos = _syncsafe(body[:4]) if major == 4 else struct.unpack(">I", body[:4])[0] + 4
                while pos < len(body):
                    if major == 2:
                        frame_id = body[pos:pos + 3].decode("latin-1")
                        size = int.from_bytes(body[pos + 3:pos + 6], "big")
                        header_len, frame_flags = 6, 0
                    else:
                        frame_id = body[pos:pos + 4].decode("latin-1")
                        raw_size = body[pos + 4:pos + 8]
                        if len(raw_size) < 4:
                            break
                        size = _syncsafe(raw_size) if major == 4 else struct.unpack(">I", raw_size)[0]
                        header_len = 10
                        frame_flags = body[pos + 9] if pos + 9 < len(body) else 0
                    if not frame_id.strip("\x00") or size <= 0:
                        break
                    if frame_id in WANTED and not frame_flags & 0x0C:
                        tags.setdefault(WANTED[frame_id],
                                        _decode_text(body[pos + header_len:pos + header_len + size]))
                    pos += header_len + size
            if not tags.get("title"):
                handle.seek(-128, os.SEEK_END)
                v1 = handle.read(128)
                if v1[:3] == b"TAG":
                    for key, chunk in (("title", v1[3:33]), ("artist", v1[33:63])):
                        value = chunk.split(b"\x00")[0].decode("latin-1").strip()
                        if value and not tags.get(key):
                            tags[key] = value
    except (OSError, ValueError, struct.error):
        pass
    genre = tags.get("genre", "")
    if re.fullmatch(r"\(\d+\)", genre):  # numeric ID3v1-style genre reference
        tags.pop("genre")
    return {k: v for k, v in tags.items() if v}


def guess_from_filename(stem):
    stem = re.sub(r"^\s*\(?\d{1,3}\)?\s*[-.\s_]\s*", "", stem)
    parts = [p.strip() for p in re.split(r"\s+-\s+", stem) if p.strip()]
    if len(parts) >= 2:
        return {"artist": parts[0], "title": parts[-1]}
    return {"title": stem.strip()}


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# --- Library ----------------------------------------------------------------


def fingerprint(path):
    """Same audio file = same size and same first/last 256 KB."""
    size = path.stat().st_size
    digest = hashlib.md5(str(size).encode())
    with open(path, "rb") as handle:
        digest.update(handle.read(262144))
        if size > 524288:
            handle.seek(-262144, os.SEEK_END)
            digest.update(handle.read())
    return digest.hexdigest()


def classify(rel):
    """(kind, folder name) for a path relative to the root.

    kind is 'genre', 'session', 'inbox', 'rejected' or 'unsorted'.
    """
    parts = rel.parts
    if len(parts) < 2:
        return "unsorted", "(root)"
    top = parts[0]
    if top == GENRES:
        return ("genre", parts[1]) if len(parts) >= 3 else ("unsorted", GENRES)
    if top == INBOX:
        return "inbox", INBOX
    if top == REJECTED:
        return "rejected", parts[1] if len(parts) >= 3 else REJECTED
    if top == SESSIONS:
        return ("session", parts[1]) if len(parts) >= 3 else ("unsorted", SESSIONS)
    return "unsorted", top


def active(copies):
    """Copies that count as part of the library (rejected versions do not)."""
    return [c for c in copies if c["kind"] != "rejected"]


def scan(root=None):
    root = root or ROOT
    tracks = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (not path.is_file() or path.suffix.lower() not in AUDIO
                or any(p.startswith(".") for p in rel.parts)):
            continue
        kind, folder = classify(rel)
        tags = read_tags(path) if path.suffix.lower() == ".mp3" else {}
        guess = guess_from_filename(path.stem)
        tracks.append({
            "path": str(rel), "kind": kind, "folder": folder, "fp": fingerprint(path),
            "artist": tags.get("artist") or guess.get("artist", ""),
            "title": tags.get("title") or guess.get("title", ""),
            "genre_tag": tags.get("genre", ""), "bpm": tags.get("bpm", ""),
        })
    return tracks


def by_song(tracks):
    songs = {}
    for track in tracks:
        songs.setdefault(track["fp"], []).append(track)
    return songs


def genre_folders(copies):
    return sorted({c["folder"] for c in copies if c["kind"] == "genre"})


# --- Log --------------------------------------------------------------------


def log_path():
    return ROOT / LOG_NAME


def write_log(batch, entries):
    with open(log_path(), "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(dict(entry, batch=batch), ensure_ascii=False) + "\n")


def read_log():
    if not log_path().exists():
        return []
    with open(log_path(), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def new_batch():
    base = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    used = {e["batch"] for e in read_log()}
    batch, n = base, 1
    while batch in used:
        n += 1
        batch = f"{base}-{n}"
    return batch


# --- Commands ---------------------------------------------------------------


def cmd_status(args):
    tracks = scan()
    songs = {fp: active(c) for fp, c in by_song(tracks).items()}
    songs = {fp: c for fp, c in songs.items() if c}
    folders = {}
    for t in tracks:
        folders.setdefault((t["kind"], t["folder"]), 0)
        folders[(t["kind"], t["folder"])] += 1
    print(f"Library: {ROOT}")
    print(f"{len(tracks)} files, {len(songs)} different songs (not counting Rejected)\n")
    for kind in ("inbox", "genre", "session", "unsorted", "rejected"):
        rows = sorted((f, n) for (k, f), n in folders.items() if k == kind)
        if rows:
            print(KIND_LABELS[kind])
            for folder, n in rows:
                print(f"  {n:4}  {folder}")
            print()
    no_genre = [c for c in songs.values() if not genre_folders(c)]
    multi = [c for c in songs.values() if len(genre_folders(c)) > 1]
    print(f"Songs without a genre folder: {len(no_genre)}")
    print(f"Songs in more than one genre: {len(multi)}")
    for copies in multi[:20]:
        print(f"  {copies[0]['artist']} - {copies[0]['title']}: {', '.join(genre_folders(copies))}")


def cmd_scan(args):
    """JSON list of songs to sort: by default, every song without a genre folder."""
    tracks = [t for t in scan() if t["kind"] != "rejected"]
    songs = by_song(tracks)
    out = []
    for copies in songs.values():
        if args.folder:
            picked = [c for c in copies if c["path"].startswith(args.folder.rstrip("/") + "/")]
            if not picked:
                continue
        elif genre_folders(copies):
            continue
        else:
            picked = copies
        first = picked[0]
        out.append({"source": first["path"], "artist": first["artist"], "title": first["title"],
                    "genre_tag": first["genre_tag"], "bpm": first["bpm"],
                    "genres": genre_folders(copies),
                    "also_in": sorted({c["path"] for c in copies} - {first["path"]})})
    out.sort(key=lambda s: (normalize(s["artist"]), normalize(s["title"])))
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_find(args):
    words = normalize(" ".join(args.query)).split()
    tracks = scan()
    hits = 0
    for copies in by_song(tracks).values():
        hay = " ".join(normalize(f"{c['artist']} {c['title']} {Path(c['path']).stem}") for c in copies)
        if all(w in hay for w in words):
            hits += 1
            print(f"{copies[0]['artist']} - {copies[0]['title']}")
            for c in copies:
                print(f"    {c['path']}")
    print(f"\n{hits} song(s) found")


def _check_target(to):
    """(kind, name) for a plan target, or ValueError."""
    parts = Path(to).parts
    bad = lambda name: name in ("", ".", "..") or name.startswith(".")
    if len(parts) == 2 and parts[0] == GENRES and not bad(parts[1]):
        return "genre", parts[1]
    if len(parts) == 2 and parts[0] == REJECTED and not bad(parts[1]):
        return "rejected", parts[1]
    if len(parts) == 1 and parts[0] == INBOX:
        return "inbox", INBOX
    if len(parts) == 2 and parts[0] == SESSIONS and not bad(parts[1]):
        return "session", parts[1]
    if len(parts) == 1 and not bad(parts[0]) and parts[0] not in RESERVED:
        raise ValueError(f"sessions live in {SESSIONS}/: use {SESSIONS}/{parts[0]!s}, got {to!r}")
    raise ValueError(f"target must be Genres/<name>, {SESSIONS}/<name>, {INBOX} "
                     f"or {REJECTED}/<song>, got {to!r}")


def _inside_root(rel):
    path = (ROOT / rel).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError(f"path outside the library: {rel}")
    return path


def cmd_apply(args):
    """Run a plan: [{"source": rel path, "to": "Genres/X"|"00 Inbox"|"Sessions/<name>", "action": "copy"|"move"}]."""
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    tracks = scan()
    songs = by_song(tracks)
    fp_of = {t["path"]: t["fp"] for t in tracks}
    planned = {}   # (target folder, fp) -> new file, so a plan cannot add a song twice
    located = {}   # original source -> where an earlier step of this plan moved it
    gone = set()   # files an earlier step moved away
    genres = {fp: set(genre_folders(copies)) for fp, copies in songs.items()}
    steps, problems = [], []
    for item in plan:
        source, to, action = item.get("source", ""), item.get("to", ""), item.get("action", "copy")
        try:
            to_kind, to_name = _check_target(to)
            to = str(Path(to))
            _inside_root(source)
            if action not in ("copy", "move"):
                raise ValueError(f"unknown action {action!r}")
            if source not in fp_of:
                raise ValueError(f"not a library audio file: {source}")
        except ValueError as error:
            problems.append(str(error))
            continue
        current = located.get(source, source)
        if action == "move" and source in located:
            problems.append(f"{source}: moved twice in one plan; list one move per file")
            continue
        kind, folder = classify(Path(current))
        fp = fp_of[source]
        if action == "move" and kind == "genre" and to_kind != "genre":
            problems.append(f"{source}: moving out of a genre folder would leave the song without a genre; use copy")
            continue
        existing = [c["path"] for c in songs[fp]
                    if str(Path(c["path"]).parent) == to and c["path"] not in gone]
        if existing or (to, fp) in planned:
            steps.append(("skip", current, to, f"already there: {existing[0] if existing else planned[(to, fp)]}"))
            continue
        if to_kind == "genre":
            after = set(genres[fp])
            if action == "move" and kind == "genre":
                after.discard(folder)
            after.add(to_name)
            if len(after) > 1:
                problems.append(f"{source}: would be in genres {', '.join(sorted(after))}; "
                                "a song keeps one genre (move it from its genre folder to change genre)")
                continue
            genres[fp] = after
        dest = str(Path(to) / Path(source).name)
        if ((ROOT / dest).exists() and dest not in gone) or dest in planned.values():
            problems.append(f"{source}: a different file named {Path(source).name!r} already exists in {to}")
            continue
        planned[(to, fp)] = dest
        if action == "move":
            located[source] = dest
            gone.add(current)
        steps.append((action, current, dest, ""))

    for action, source, dest, note in steps:
        arrow = {"copy": "copy", "move": "move", "skip": "skip"}[action]
        print(f"{arrow:5} {source}\n      -> {dest if action != 'skip' else note}")
    print(f"\n{sum(s[0] == 'copy' for s in steps)} copy, {sum(s[0] == 'move' for s in steps)} move, "
          f"{sum(s[0] == 'skip' for s in steps)} skip, {len(problems)} problem(s)")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not args.apply:
        print("\nDry run. Nothing changed. Add --apply to run it.")
        return
    batch, done = new_batch(), []
    try:
        for action, source, dest, _ in steps:
            if action == "skip":
                continue
            (ROOT / dest).parent.mkdir(parents=True, exist_ok=True)
            if action == "copy":
                shutil.copy2(ROOT / source, ROOT / dest)
            else:
                shutil.move(str(ROOT / source), str(ROOT / dest))
            done.append({"action": action, "source": source, "dest": dest})
    finally:
        write_log(batch, done)
    print(f"\nApplied {len(done)} change(s). Batch {batch}. Undo with: undo --apply")


def cmd_remove(args):
    tracks = scan()
    songs = by_song(tracks)
    fp_of = {t["path"]: t["fp"] for t in tracks}
    steps, problems = [], []
    paths = []
    for rel in args.paths:
        rel = rel.rstrip("/")
        if (ROOT / rel).is_dir() and rel not in ("", "."):
            inside = sorted(p for p in fp_of if p.startswith(rel + "/"))
            paths.extend(inside or [rel])
        else:
            paths.append(rel)
    for rel in paths:
        if rel not in fp_of:
            problems.append(f"not a library audio file: {rel}")
            continue
        kind, folder = classify(Path(rel))
        if kind == "genre" and len([c for c in songs[fp_of[rel]] if c["kind"] == "genre"]) < 2:
            problems.append(f"{rel}: this is the song's only genre copy; move it to another genre instead")
            continue
        steps.append(rel)
    for rel in steps:
        print(f"trash {rel}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not args.apply:
        print("\nDry run. Nothing changed. Add --apply to run it.")
        return
    batch, done = new_batch(), []
    trash_dir = TRASH / f"djlib-{batch}"
    try:
        for rel in steps:
            dest = trash_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ROOT / rel), str(dest))
            done.append({"action": "trash", "source": rel, "dest": str(dest)})
            _remove_empty_dirs((ROOT / rel).parent)
    finally:
        write_log(batch, done)
    print(f"\nMoved {len(done)} file(s) to the Trash. Batch {batch}. Undo with: undo --apply")


def cmd_undo(args):
    entries = read_log()
    undone = {e["batch"] for e in entries if e.get("action") == "undo"}
    batches = [e["batch"] for e in entries if e.get("action") != "undo" and e["batch"] not in undone]
    if not batches:
        print("Nothing to undo.")
        return
    batch = args.batch or batches[-1]
    todo = [e for e in entries if e["batch"] == batch and e.get("action") != "undo"]
    if batch in undone or not todo:
        print(f"Batch {batch} not found or already undone.")
        return
    for e in reversed(todo):
        if e["action"] == "copy":
            print(f"trash copy {e['dest']}")
        elif e["action"] == "move":
            print(f"move back  {e['dest']} -> {e['source']}")
        else:
            print(f"restore    {e['source']} (from Trash)")
    if not args.apply:
        print(f"\nDry run for batch {batch}. Add --apply to undo it.")
        return
    trash_dir = TRASH / f"djlib-undo-{batch}"
    for e in reversed(todo):
        if e["action"] == "copy":
            target = trash_dir / e["dest"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ROOT / e["dest"]), str(target))
        elif e["action"] == "move":
            (ROOT / e["source"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ROOT / e["dest"]), str(ROOT / e["source"]))
        else:
            (ROOT / e["source"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(e["dest"], str(ROOT / e["source"]))
    write_log(batch, [{"action": "undo", "at": new_batch()}])
    print(f"\nUndid batch {batch}.")


def _remove_empty_dirs(folder):
    """Remove now-empty folders inside 00 Rejected (only truly empty ones)."""
    rejected = (ROOT / REJECTED).resolve()
    folder = folder.resolve()
    while folder != rejected and rejected in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def cmd_index(args):
    """JSON of every library song file, for other tools (e.g. the downloads review)."""
    out = [{k: t[k] for k in ("path", "kind", "folder", "artist", "title", "fp")}
           for t in scan()]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def _inside_sources(raw):
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"download paths must be absolute: {raw}")
    resolved = path.resolve()
    if not any(src.resolve() in resolved.parents for src in SOURCES):
        raise ValueError(f"not inside a download folder ({', '.join(map(str, SOURCES))}): {raw}")
    return resolved


def song_folder_name(song):
    """Folder name for a song's rejected versions (a new folder, never a renamed file)."""
    name = re.sub(r'[/:\x00-\x1f]+', "-", song or "").strip().lstrip(".").strip()
    return name[:120].rstrip() or "Unknown song"


def cmd_intake(args):
    """Move reviewed downloads: the kept version to 00 Inbox, the others to 00 Rejected/<song>.

    PICKS.json: [{"song": "Artist - Title", "keep": "/abs/file" | null,
                  "reject": ["/abs/file", ...], "signatures": {"/abs/file": [size, "mtime_ns"]}}]
    """
    with open(args.picks, encoding="utf-8") as handle:
        picks = json.load(handle)
    tracks = scan()
    library = [t for t in tracks if t["kind"] != "rejected"]
    by_fp = {t["fp"]: t["path"] for t in library}
    by_name = {}
    for t in library:
        if t["kind"] == "genre" and t["title"]:
            by_name.setdefault((normalize(t["artist"]), normalize(t["title"])), []).append(t["path"])
    steps, problems, notes = [], [], []
    taken, seen = set(), set()
    for pick in picks:
        song = pick.get("song") or ""
        signatures = pick.get("signatures") or {}
        entries = [(pick["keep"], INBOX)] if pick.get("keep") else []
        entries += [(r, f"{REJECTED}/{song_folder_name(song)}") for r in pick.get("reject") or []]
        own_steps, own_problems = [], []
        for raw, to in entries:
            try:
                path = _inside_sources(raw)
                if not path.is_file() or path.suffix.lower() not in AUDIO:
                    raise ValueError(f"missing or not an audio file: {raw}")
                if str(path) in seen:
                    raise ValueError(f"listed twice: {raw}")
                signature = signatures.get(raw)
                stat = path.stat()
                if signature and [str(stat.st_size), str(stat.st_mtime_ns)] != [str(v) for v in signature]:
                    raise ValueError(f"changed since the review (review it again): {raw}")
            except (ValueError, OSError) as error:
                own_problems.append(str(error))
                continue
            dest = f"{to}/{path.name}"
            if (ROOT / dest).exists() or dest in taken:
                own_problems.append(f"{path.name}: a file with this name is already in {to}")
                continue
            own_steps.append(("inbox" if to == INBOX else "reject", str(path), dest))
        if own_problems:
            problems += [f"{song or '(no song name)'}: {p} (song skipped)" for p in own_problems]
            continue
        for step in own_steps:
            taken.add(step[2])
            seen.add(step[1])
            if step[0] == "inbox":
                path = Path(step[1])
                if fingerprint(path) in by_fp:
                    notes.append(f"{song}: the same file is already in the library: {by_fp[fingerprint(path)]}")
                else:
                    tags = read_tags(path) if path.suffix.lower() == ".mp3" else {}
                    guess = guess_from_filename(path.stem)
                    key = (normalize(tags.get("artist") or guess.get("artist", "")),
                           normalize(tags.get("title") or guess.get("title", "")))
                    if key in by_name:
                        notes.append(f"{song}: possible upgrade of {', '.join(by_name[key])}")
        steps += own_steps

    for kind, source, dest in steps:
        print(f"{kind:6} {source}\n       -> {dest}")
    print(f"\n{sum(s[0] == 'inbox' for s in steps)} to {INBOX}, "
          f"{sum(s[0] == 'reject' for s in steps)} to {REJECTED}, {len(problems)} problem(s)")
    for note in notes:
        print(f"  NOTE: {note}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not args.apply:
        print("\nDry run. Nothing changed. Add --apply to run it.")
        return
    batch, done = new_batch(), []
    try:
        for _, source, dest in steps:
            (ROOT / dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, str(ROOT / dest))
            done.append({"action": "move", "source": source, "dest": dest})
    finally:
        write_log(batch, done)
    print(f"\nApplied {len(done)} move(s). Batch {batch}. Undo with: undo --apply")


def cmd_dupes(args):
    tracks = [t for t in scan() if t["kind"] != "rejected"]
    songs = by_song(tracks)
    print("Same file saved under different names in one folder:")
    found = 0
    for copies in songs.values():
        per_folder = {}
        for c in copies:
            per_folder.setdefault(str(Path(c["path"]).parent), []).append(c["path"])
        for folder, paths in per_folder.items():
            if len(paths) > 1:
                found += 1
                print(f"  {folder}: " + " | ".join(Path(p).name for p in paths))
    print(f"  {found} found\n")
    print("Same artist and title but different files (other encode or version? check by ear):")
    by_name = {}
    for fp, copies in songs.items():
        key = (normalize(copies[0]["artist"]), normalize(copies[0]["title"]))
        if key[1]:
            by_name.setdefault(key, []).append(copies)
    found = 0
    for groups in by_name.values():
        if len(groups) > 1:
            found += 1
            print(f"  {groups[0][0]['artist']} - {groups[0][0]['title']}")
            for copies in groups:
                print(f"      {copies[0]['path']}")
    print(f"  {found} found")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    p = sub.add_parser("undo", help="revert the last applied batch")
    p.add_argument("--batch")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_undo)
    sub.add_parser("dupes", help="duplicate songs").set_defaults(func=cmd_dupes)
    sub.add_parser("index", help="JSON of every library file").set_defaults(func=cmd_index)
    p = sub.add_parser("intake", help="move reviewed downloads to 00 Inbox / 00 Rejected")
    p.add_argument("picks", help="picks JSON exported from downloads.html")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_intake)
    args = parser.parse_args(argv)
    if not ROOT.is_dir():
        sys.exit(f"Library not found: {ROOT}")
    args.func(args)


if __name__ == "__main__":
    main()
