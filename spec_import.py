#!/usr/bin/env python3
"""Import TSC_AGVL Spec (.docx) into DB / JSON.

Extracts one dict per P##/S## message:
    id, description, direction, structure, raw_lines, fields

Usage:
    # dump JSON to stdout
    python3 spec_import.py --docx doc/spec.docx --version 5.0
    # write JSON to file
    python3 spec_import.py --docx doc/spec.docx --version 5.0 -o spec.json
    # upsert directly into DB
    python3 spec_import.py --docx doc/spec.docx --version 5.0 --db
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HDR_RE = re.compile(r"^([PS])(\d{1,3})$")
CONTENTS_RE = re.compile(r"^Contents\s*[:：]\s*(.+)$")
STRUCTURE_RE = re.compile(r"^Structure\s*[:：]\s*(.*)$")
DIR_RE = re.compile(r"^TSC\s*[🡸🡺←→↔↑<>=\-]+\s*Loc", re.IGNORECASE)

# Style A: "N Byte = label", "N~M Byte = label"
BYTE_A_RANGE_RE = re.compile(
    r"^\s*(\d+)\s*[~～\-]\s*([A-Za-z\d]+)\s*Byte\s*[=:：]\s*(.+)$"
)
BYTE_A_SINGLE_RE = re.compile(r"^\s*(\d+)\s*Byte\s*[=:：]\s*(.+)$", re.IGNORECASE)
# Style B: "byte N:" or "byte N~M:" (label on following lines)
BYTE_B_RANGE_RE = re.compile(
    r"^\s*byte\s+(\d+)\s*[~～\-]\s*([A-Za-z\d]+)\s*[:：]\s*(.*)$", re.IGNORECASE
)
BYTE_B_SINGLE_RE = re.compile(r"^\s*byte\s+(\d+)\s*[:：]\s*(.*)$", re.IGNORECASE)
# Style C: "Byte = label" without a leading number (docx paragraph splitter dropped the number)
BYTE_UNPOSITIONED_RE = re.compile(r"^\s*Byte\s*[=:：]\s*(.+)$", re.IGNORECASE)
# Style D: "First <> :", "Second <> :" ...
TAG_ORDINAL_RE = re.compile(
    r"^\s*(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s*<>\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)
# Enum candidate lines: "0 = Idle" or "0: Idle" or "P: Positive"
ENUM_LINE_RE = re.compile(r"^\s*([A-Za-z0-9]{1,4})\s*[:=]\s*(.+)$")


def extract_paragraphs(docx_path):
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    paras = []
    for p in tree.getroot().iter(f"{WORD_NS}p"):
        text = "".join(t.text or "" for t in p.iter(f"{WORD_NS}t"))
        if text.strip():
            paras.append(text.strip())
    return paras


def find_detail_start(paras):
    for i, p in enumerate(paras):
        if p == "Message Detail":
            return i + 1
    return 0


def classify_direction(line):
    s = line.replace(" ", "")
    has_left = "🡸" in s or "←" in s or "<" in s
    has_right = "🡺" in s or "→" in s or ">" in s
    if has_left and has_right:
        return "bidir"
    if has_right:
        return "TSC->Loc"
    if has_left:
        return "TSC<-Loc"
    return "unknown"


def parse_int_or_var(x):
    """'N', 'M', or a number string -> int or the letter."""
    try:
        return int(x)
    except ValueError:
        return x  # variable-length marker


def match_field_header(line):
    """If line starts a new field definition, return the field dict
    (with .label possibly containing the tail text) and a bool telling
    the caller whether to expect the label on following lines.

    Returns (field_dict, expect_more_lines) or (None, False).
    """
    m = BYTE_A_RANGE_RE.match(line)
    if m:
        return ({"start": int(m.group(1)), "end": parse_int_or_var(m.group(2)),
                 "label": m.group(3).strip()}, False)
    m = BYTE_A_SINGLE_RE.match(line)
    if m:
        n = int(m.group(1))
        return ({"start": n, "end": n, "label": m.group(2).strip()}, False)
    m = BYTE_B_RANGE_RE.match(line)
    if m:
        tail = m.group(3).strip()
        return ({"start": int(m.group(1)), "end": parse_int_or_var(m.group(2)),
                 "label": tail}, not tail)
    m = BYTE_B_SINGLE_RE.match(line)
    if m:
        n = int(m.group(1))
        tail = m.group(2).strip()
        return ({"start": n, "end": n, "label": tail}, not tail)
    m = TAG_ORDINAL_RE.match(line)
    if m:
        return ({"tag_index": m.group(1).lower(), "label": m.group(2).strip()},
                False)
    m = BYTE_UNPOSITIONED_RE.match(line)
    if m:
        return ({"start": None, "end": None, "label": m.group(1).strip()}, False)
    return (None, False)


def parse_enum_values(text):
    """Extract enum values from text like '0:Idle, 1:Working, 2:Pause'
    or a single line like '0: Idle' or 'P: Positive'."""
    values = {}
    for m in re.finditer(
        r"([A-Za-z0-9]{1,4})\s*[:=]\s*([^,;\n]+?)(?=,|;|\band\b|$)", text
    ):
        v = m.group(1)
        d = m.group(2).strip().rstrip(".").strip()
        if d and len(d) <= 40 and not d.lower().startswith("e.g"):
            values[v] = d
    return values


def is_enum_or_label_continuation(line):
    """A body line that looks like a lone enum value or a label continuation
    (not a field header, not an example). Used by the state machine to
    keep collecting into the current field."""
    if line.lower().startswith(("e.g", "例", "範例", "data =")):
        return False
    if ENUM_LINE_RE.match(line):
        return True
    # Short continuations (label wrap) — heuristic
    if len(line) <= 80:
        return True
    return False


def parse_message_block(lines):
    """lines = raw paragraph strings for one P##/S## block."""
    if not lines:
        return None
    header = lines[0]
    m = HDR_RE.match(header)
    if not m:
        return None
    kind, num = m.group(1), m.group(2)
    msg_id = f"{kind}{num}"

    description = ""
    structure = ""
    direction = "unknown"
    body = []

    # Walk lines; capture Contents / Structure / Direction
    i = 1
    seen_structure = False
    while i < len(lines):
        ln = lines[i]
        mc = CONTENTS_RE.match(ln)
        if mc and not description:
            description = mc.group(1).strip()
            i += 1
            continue
        ms = STRUCTURE_RE.match(ln)
        if ms:
            structure = ms.group(1).strip()
            seen_structure = True
            i += 1
            continue
        if ln == "Direction":
            i += 1
            continue
        if DIR_RE.match(ln):
            direction = classify_direction(ln)
            i += 1
            continue
        if seen_structure:
            body.append(ln)
        i += 1

    # State-machine parse: field headers open a slot; subsequent
    # continuation lines extend .label / .values until the next header
    # or an example line.
    fields = []
    cur = None
    for ln in body:
        header, expect_more = match_field_header(ln)
        if header is not None:
            if cur is not None:
                cur["values"] = parse_enum_values(
                    cur["label"] + " " + " ".join(cur.get("_extra", []))
                )
                cur.pop("_extra", None)
                fields.append(cur)
            cur = header
            cur["_extra"] = []
            continue
        if cur is not None and is_enum_or_label_continuation(ln):
            cur["_extra"].append(ln)
            if not cur["label"]:
                cur["label"] = ln
            continue
        # Non-continuation (example, note) → close current field
        if cur is not None:
            cur["values"] = parse_enum_values(
                cur["label"] + " " + " ".join(cur.get("_extra", []))
            )
            cur.pop("_extra", None)
            fields.append(cur)
            cur = None
    if cur is not None:
        cur["values"] = parse_enum_values(
            cur["label"] + " " + " ".join(cur.get("_extra", []))
        )
        cur.pop("_extra", None)
        fields.append(cur)

    infer_missing_positions(fields)

    return {
        "id": msg_id,
        "description": description,
        "direction": direction,
        "structure": structure,
        "raw_lines": body,
        "fields": fields,
    }


def infer_missing_positions(fields):
    """Some docx paragraphs drop the leading '1 ' / '2 ' before 'Byte = ...'
    (Word auto-numbered list bullets don't appear in the text stream).
    Walk the field list in order and fill in start/end based on context:
    the byte immediately after the previous field.

    - Ordinal-tag fields (First <>, Second <>) don't consume byte positions.
    - Variable-length fields ('end' = 'N') break the cursor; subsequent
      fields need an explicit start (we leave them alone).
    """
    pos = 1
    valid_cursor = True
    for f in fields:
        if "tag_index" in f:
            continue
        s, e = f.get("start"), f.get("end")
        if s is None:
            if not valid_cursor:
                continue
            f["start"] = pos
            f["end"] = pos
            pos += 1
        else:
            if isinstance(s, int):
                # A numeric start is authoritative — snap cursor to it
                pos = s
            if isinstance(e, int):
                pos = e + 1
                valid_cursor = True
            else:
                # Variable end ('N') — cursor becomes undefined
                valid_cursor = False


def extract_messages(docx_path):
    paras = extract_paragraphs(docx_path)
    start = find_detail_start(paras)
    # Group by header
    blocks = []
    cur = []
    for p in paras[start:]:
        if HDR_RE.match(p):
            if cur:
                blocks.append(cur)
            cur = [p]
        else:
            if cur:
                cur.append(p)
    if cur:
        blocks.append(cur)

    msgs = []
    for b in blocks:
        parsed = parse_message_block(b)
        if parsed:
            msgs.append(parsed)
    return msgs


def upsert_into_db(version, label, source, msgs):
    """Idempotent insert/update of one spec + all its messages."""
    import configparser
    import os
    import pymysql

    base = os.path.dirname(os.path.abspath(__file__))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(base, "config.ini"))
    conn = pymysql.connect(
        host=cfg.get("db", "host"),
        port=cfg.getint("db", "port"),
        user=cfg.get("db", "user"),
        password=cfg.get("db", "password"),
        database=cfg.get("db", "database"),
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO spec_versions (`version`, label, source) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE label=VALUES(label), source=VALUES(source)",
                (version, label, source),
            )
            cur.execute("SELECT id FROM spec_versions WHERE `version`=%s", (version,))
            spec_id = cur.fetchone()[0]
            for m in msgs:
                cur.execute(
                    "INSERT INTO spec_messages "
                    "(spec_id, msg_id, description, direction, structure, fields, raw_text) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE description=VALUES(description), "
                    "direction=VALUES(direction), structure=VALUES(structure), "
                    "fields=VALUES(fields), raw_text=VALUES(raw_text)",
                    (
                        spec_id,
                        m["id"],
                        m["description"],
                        m["direction"],
                        m["structure"],
                        json.dumps(m["fields"], ensure_ascii=False),
                        "\n".join(m["raw_lines"]),
                    ),
                )
        conn.commit()
        return spec_id
    finally:
        conn.close()


def _parse_args(argv):
    args = {"docx": None, "version": None, "output": None, "db": False}
    it = iter(argv[1:])
    for a in it:
        if a == "--docx": args["docx"] = next(it)
        elif a == "--version": args["version"] = next(it)
        elif a in ("-o", "--output"): args["output"] = next(it)
        elif a == "--db": args["db"] = True
        elif a in ("-h", "--help"):
            print(__doc__); sys.exit(0)
        else:
            print(f"unknown arg: {a}", file=sys.stderr); sys.exit(2)
    if not args["docx"] or not args["version"]:
        print("--docx and --version are required. -h for help.", file=sys.stderr)
        sys.exit(2)
    return args


if __name__ == "__main__":
    args = _parse_args(sys.argv)
    msgs = extract_messages(args["docx"])
    label = f"TSC_AGVL Spec {args['version']}"
    source = args["docx"].rsplit("/", 1)[-1]
    payload = {"version": args["version"], "label": label, "source": source,
               "messages": msgs}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args["output"]:
        with open(args["output"], "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {len(msgs)} messages to {args['output']}", file=sys.stderr)
    elif not args["db"]:
        print(text)
    if args["db"]:
        spec_id = upsert_into_db(args["version"], label, source, msgs)
        print(f"DB upsert done. spec_id={spec_id}, messages={len(msgs)}",
              file=sys.stderr)
