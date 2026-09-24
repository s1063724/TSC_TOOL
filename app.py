#!/usr/bin/env python3
"""Flask backend for TSC TOOL.

Serves index.html and provides a small settings key-value API
(currently storing the shared exclude-devices list).
Config in config.ini (chmod 600).
"""
import configparser
import os
import re

import pymysql
from flask import Flask, jsonify, render_template, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

_cfg = configparser.ConfigParser()
_cfg.read(CONFIG_PATH)

DB = {
    "host": _cfg.get("db", "host"),
    "port": _cfg.getint("db", "port"),
    "user": _cfg.get("db", "user"),
    "password": _cfg.get("db", "password"),
    "database": _cfg.get("db", "database"),
    "charset": "utf8mb4",
    "autocommit": True,
    "cursorclass": pymysql.cursors.DictCursor,
}
SERVER_HOST = _cfg.get("server", "host", fallback="0.0.0.0")
SERVER_PORT = _cfg.getint("server", "port", fallback=9000)

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=None)
# Jinja2 defaults to caching compiled templates in production; enable auto-reload
# so template edits show up without a service restart.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


def db():
    return pymysql.connect(**DB)


# ---------- pages (Jinja templates) ----------

def parse_changelog(path, limit=4):
    """Parse CHANGELOG.md into a list of {version, entries: [{kind, text}]} dicts."""
    out = []
    if not os.path.isfile(path):
        return out
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            m = re.match(r"^##\s+(v[\d.]+)(?:\s+—\s+(.+))?", line)
            if m:
                if current:
                    out.append(current)
                    if len(out) >= limit:
                        return out
                current = {"version": m.group(1), "note": (m.group(2) or "").strip(), "entries": []}
                continue
            if current is None:
                continue
            m2 = re.match(r"^\*\s+\*\*(\w+):\*\*\s+(.+)$", line)
            if m2:
                text = m2.group(2)
                # Convert markdown `code` and **bold** to HTML for safe rendering
                text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
                text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
                current["entries"].append({"kind": m2.group(1), "text": text})
    if current and len(out) < limit:
        out.append(current)
    return out


def read_exclude_devices():
    try:
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `value`, updated_at FROM settings WHERE `name` = %s",
                ("exclude_devices",),
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return {"value": "", "updated_at": None}
        return {
            "value": row["value"] or "",
            "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row["updated_at"] else None,
        }
    except Exception:
        return {"value": "", "updated_at": None}


@app.route("/home")
def home_page():
    changelog = parse_changelog(os.path.join(BASE_DIR, "CHANGELOG.md"), limit=4)
    excl = read_exclude_devices()
    excl_chips = [s.strip() for s in excl["value"].split(",") if s.strip()]
    return render_template(
        "home.html",
        active="home",
        changelog=changelog,
        exclude_chips=excl_chips,
        exclude_updated_at=excl["updated_at"],
        server_port=SERVER_PORT,
    )


@app.route("/")
def index():
    return render_template("index.html", active="index")


@app.route("/check")
def check_page():
    return render_template("check.html", active="check")


@app.route("/stats")
def stats_page():
    return render_template("stats.html", active="stats")


@app.route("/vehicle")
def vehicle_page():
    return render_template("vehicle.html", active="vehicle")


# ---------- spec API (vehicle-log analysis) ----------

@app.route("/api/specs", methods=["GET"])
def list_specs():
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, `version`, label, source, is_default, "
                "updated_at FROM spec_versions ORDER BY `version`"
            )
            rows = cur.fetchall()
        for r in rows:
            if r.get("updated_at"):
                r["updated_at"] = r["updated_at"].isoformat()
        return jsonify({"specs": rows})
    finally:
        conn.close()


@app.route("/api/specs/<int:spec_id>/messages", methods=["GET"])
def list_spec_messages(spec_id):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT msg_id, description, direction, structure, "
                "fields, raw_text FROM spec_messages WHERE spec_id = %s "
                "ORDER BY msg_id",
                (spec_id,),
            )
            rows = cur.fetchall()
        import json as _json
        out = {}
        for r in rows:
            r["fields"] = _json.loads(r["fields"]) if r["fields"] else []
            out[r["msg_id"]] = r
        return jsonify({"spec_id": spec_id, "messages": out})
    finally:
        conn.close()


@app.route("/api/specs/<int:spec_id>/messages/<msg_id>", methods=["PUT"])
def update_spec_message(spec_id, msg_id):
    import json as _json
    data = request.get_json(silent=True) or {}
    fields = data.get("fields")
    if fields is None or not isinstance(fields, list):
        return jsonify({"error": "fields (list) is required"}), 400
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE spec_messages SET fields=%s WHERE spec_id=%s AND msg_id=%s",
                (_json.dumps(fields, ensure_ascii=False), spec_id, msg_id),
            )
            if cur.rowcount == 0:
                # insert if new
                cur.execute(
                    "INSERT INTO spec_messages (spec_id, msg_id, description, "
                    "direction, structure, fields) VALUES (%s, %s, %s, %s, %s, %s)",
                    (spec_id, msg_id, data.get("description", ""),
                     data.get("direction", ""), data.get("structure", ""),
                     _json.dumps(fields, ensure_ascii=False)),
                )
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------- other static files (favicons, offline libs) ----------

@app.route("/<path:filename>")
def static_file(filename):
    if filename.startswith(("config", "app.py", "schema.sql", "templates", ".")):
        return jsonify({"error": "forbidden"}), 403
    full = os.path.join(BASE_DIR, filename)
    if not os.path.isfile(full):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(BASE_DIR, filename)


# ---------- settings API (key-value) ----------

@app.route("/api/settings/<key>", methods=["GET"])
def get_setting(key):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `value`, updated_at FROM settings WHERE `name` = %s",
                (key,),
            )
            row = cur.fetchone()
        return jsonify({
            "key": key,
            "value": row["value"] if row else None,
            "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None,
        })
    finally:
        conn.close()


@app.route("/api/settings/<key>", methods=["PUT"])
def put_setting(key):
    data = request.get_json(silent=True) or {}
    if "value" not in data:
        return jsonify({"error": "value is required"}), 400
    value = data["value"] if data["value"] is not None else ""
    if len(key) > 100:
        return jsonify({"error": "key too long (max 100)"}), 400
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO settings (`name`, `value`) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
                (key, value),
            )
        return jsonify({"ok": True, "key": key})
    finally:
        conn.close()


@app.route("/api/health", methods=["GET"])
def health():
    try:
        conn = db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        return jsonify({"ok": True, "db": "ok"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)
