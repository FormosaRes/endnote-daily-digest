#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Deploy this repo's (config-driven) scripts to the live working dirs.
# Repo = single source of truth; run this after editing repo scripts.
# Live keeps its own config.json (real paths/secrets) beside the scripts.
# Live target dirs come from config.json -> paths.live_scripts_dir / paths.live_daemon_dir.
import os, shutil, json
HERE=os.path.dirname(os.path.abspath(__file__))                 # .../endnote-daily-digest/scripts
REPO=os.path.dirname(HERE)

def _load_cfg():
    for c in (os.environ.get("DIGEST_CONFIG"), os.path.join(HERE,"config.json"), os.path.join(REPO,"config.json")):
        if c and os.path.exists(c): return json.load(open(c,encoding="utf-8"))
    raise FileNotFoundError("config.json not found (set DIGEST_CONFIG, or place at repo root)")

cfg=_load_cfg(); paths=cfg.get("paths",{})
LIVE_SCRIPTS=paths.get("live_scripts_dir")
LIVE_DAEMON=paths.get("live_daemon_dir")
if not LIVE_SCRIPTS or not LIVE_DAEMON:
    raise SystemExit("set paths.live_scripts_dir and paths.live_daemon_dir in config.json")

for f in os.listdir(HERE):
    if f.endswith((".py",".bat")) and f!="sync_live.py":
        shutil.copy2(os.path.join(HERE,f), os.path.join(LIVE_SCRIPTS,f)); print("->",f)
# NOTE: notify-daemon.py is maintained LIVE-canonical — its DIGEST_DIR is a real local path,
# while the repo copy is scrubbed to a placeholder. Syncing repo -> live would clobber the live
# vault path (breaking /today /want /seeds). Edit the live daemon, then copy live -> repo instead.
# (LIVE_DAEMON is still read above so config validation stays meaningful.)
_ = LIVE_DAEMON
# ensure live config.json exists beside live scripts (copy repo's real config if present)
rc=os.path.join(REPO,"config.json")
if os.path.exists(rc) and not os.path.exists(os.path.join(LIVE_SCRIPTS,"config.json")):
    shutil.copy2(rc, os.path.join(LIVE_SCRIPTS,"config.json")); print("-> config.json (live)")
print("synced. (live scripts now read config.json via DIGEST_CONFIG or ./config.json)")
