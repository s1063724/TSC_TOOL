#!/usr/bin/env python3
"""Flask backend for Dispatch Generator.

Serves index.html and provides CRUD API for named presets stored in MariaDB.
Config in config.ini (chmod 600).
"""
import configparser
import json
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


# ---------- preset API ----------

@app.route("/api/presets", methods=["GET"])
def list_presets():
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, updated_by, updated_at, created_at "
                "FROM presets ORDER BY name"
            )
            rows = cur.fetchall()
        return jsonify([
            {
                "name": r["name"],
                "updated_by": r["updated_by"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ])
    finally:
        conn.close()


@app.route("/api/presets/<name>", methods=["GET"])
def get_preset(name):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, config, updated_by, updated_at, created_at "
                "FROM presets WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "name": row["name"],
            "config": json.loads(row["config"]) if isinstance(row["config"], str) else row["config"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })
    finally:
        conn.close()


@app.route("/api/presets", methods=["POST"])
def save_preset():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    config = data.get("config")
    updated_by = (data.get("updated_by") or "unknown")[:50]

    if not name:
        return jsonify({"error": "name is required"}), 400
    if config is None:
        return jsonify({"error": "config is required"}), 400
    if len(name) > 100:
        return jsonify({"error": "name too long (max 100)"}), 400

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO presets (name, config, updated_by) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE config = VALUES(config), updated_by = VALUES(updated_by)",
                (name, json.dumps(config, ensure_ascii=False), updated_by),
            )
        return jsonify({"ok": True, "name": name})
    finally:
        conn.close()


@app.route("/api/presets/<name>", methods=["DELETE"])
def delete_preset(name):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM presets WHERE name = %s", (name,))
            deleted = cur.rowcount
        if deleted == 0:
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True, "deleted": deleted})
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
