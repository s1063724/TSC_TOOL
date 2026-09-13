#!/usr/bin/env python3
"""Flask backend for Dispatch Generator.

Serves index.html and provides a small settings key-value API
(currently storing the shared exclude-devices list).
Config in config.ini (chmod 600).
"""
import configparser
import os

import pymysql
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

app = Flask(__name__, static_folder=None)


def db():
    return pymysql.connect(**DB)


# ---------- static files ----------

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_file(filename):
    if filename.startswith(("config", "app.py", "schema.sql", ".")):
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
