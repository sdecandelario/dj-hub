"""One ID3 reader for the whole app (merged from djlib.read_tags and check_playlists.read_id3)."""
import os
import re
import struct

WANTED = {"TIT2": "title", "TPE1": "artist", "TCON": "genre", "TBPM": "bpm",
          "TT2": "title", "TP1": "artist", "TCO": "genre", "TBP": "bpm"}


def _decode_text(payload):
    if not payload:
        return ""
    encoding, raw = payload[0], payload[1:]
    try:
        text = raw.decode({0: "latin-1", 1: "utf-16", 2: "utf-16-be"}.get(encoding, "utf-8"))
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    # Multiple values are NUL-separated in ID3v2.4; keep them joined.
    return " / ".join(p.strip() for p in text.split("\x00") if p.strip())


def _syncsafe(data):
    return (data[0] << 21) | (data[1] << 14) | (data[2] << 7) | data[3]


def read_tags(path):
    """Return title, artist, genre and bpm from ID3v2 (2.2-2.4) or ID3v1 tags. Read-only."""
    tags = {}
    try:
        with open(path, "rb") as handle:
            header = handle.read(10)
            if len(header) == 10 and header[:3] == b"ID3":
                major, flags = header[3], header[5]
                body = handle.read(_syncsafe(header[6:10]))
                if flags & 0x80 and major < 4:  # whole-tag unsynchronisation
                    body = body.replace(b"\xff\x00", b"\xff")
                pos = 0
                if flags & 0x40 and major >= 3:  # extended header
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
                    # Frame flags differ by version: v2.3 has compression 0x80 and encryption 0x40,
                    # v2.4 has compression 0x08, encryption 0x04, unsynchronisation 0x02 and a data length 0x01.
                    skip = 0xC0 if major == 3 else 0x0C if major == 4 else 0
                    if frame_id in WANTED and not frame_flags & skip:  # skip compressed/encrypted
                        data = body[pos + header_len:pos + header_len + size]
                        if major == 4 and frame_flags & 0x01:   # a 4-byte data length comes first
                            data = data[4:]
                        if major == 4 and frame_flags & 0x02:
                            data = data.replace(b"\xff\x00", b"\xff")
                        tags.setdefault(WANTED[frame_id], _decode_text(data))
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
    genre = re.sub(r"^(\(\d+\))+\s*", "", tags.get("genre", ""))   # "(17)Rock" is "Rock"; "(17)" alone is only a number
    if genre:
        tags["genre"] = genre
    else:
        tags.pop("genre", None)
    return {k: v for k, v in tags.items() if v}


# --- Writing (only used by batches: files just moved to the Inbox, and "tags" batches) ----------------------

FRAMES = {"artist": "TPE1", "title": "TIT2", "album": "TALB", "year": "TDRC", "genre": "TCON"}


def write_tags(path, values, fill=None):
    """Set ID3v2 text frames (v2.4 files stay v2.4, others become v2.3) and return the values they had before ({key: old text or None}),
    so the change can be undone. `values` overwrites; `fill` only sets keys that are empty.
    A value of None removes the frame. Audio data is not touched."""
    from mutagen import id3

    try:
        tag = id3.ID3(path)
    except id3.ID3NoHeaderError:
        tag = id3.ID3()

    def current(key):
        frame = tag.get(FRAMES[key])
        return " / ".join(str(t) for t in frame.text) if frame else None

    wanted = dict(values or {})
    for key, value in (fill or {}).items():
        if value and not current(key):
            wanted[key] = value
    before = {}
    for key, value in wanted.items():
        old = current(key)
        if old == value or (old is None and not value):
            continue
        before[key] = old
        tag.delall(FRAMES[key])
        if value:
            tag.add(getattr(id3, FRAMES[key])(encoding=1, text=[str(value)]))
    if before:
        # Keep ID3v2.4 when the file already has it; anything older (or no tag) is written as v2.3.
        tag.save(path, v2_version=4 if tag.version[:2] == (2, 4) else 3)
    return before
