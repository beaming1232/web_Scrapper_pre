"""Read-only HTTP API serving the `jobs` table to the frontend.

This is the only part of the codebase that serves HTTP. It never scrapes,
rewrites, or writes - it shares db/session.py's async engine/session
factory with the rest of the app in read-only fashion. See api/main.py's
docstring for how to run it and api/schemas.py's docstring for what a
JobModel row looks like once it crosses this boundary (deliberately not
a 1:1 passthrough of every DB column).
"""
