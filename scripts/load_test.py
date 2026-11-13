"""Load test for a classroom: N students take one open session at the same moment (KT-310).

Standard library only, so it runs from any Python 3.12 without the project's environment.

    1. Start the server on scratch data (never your real data folder):
         set KT_DATA_DIR=<scratch>            (PowerShell: $env:KT_DATA_DIR = "<scratch>")
         python -m uv run manage.py migrate
         python -m uv run manage.py seed_demo
         python -m uv run manage.py serve --port 8300 --no-qr
    2. Open a session for any test in the browser (or pass --teacher to let this script do it)
       and run:
         python scripts/load_test.py --base http://127.0.0.1:8300 --code ABC123 --students 32

Each simulated student behaves like the real page: GET the test page, autosave the first answer
(which starts the attempt), keep autosaving a few more answers with think time in between, then
post the whole form to submit. With --teacher (user:password) a teacher also polls the live
stats endpoint of the session every second, as an open share screen does.

Prints, per request kind, the count, errors and the p50/p95/max latency, and exits with 1 when
anything failed or the slowest request took longer than --max-seconds.
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import random
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

lock = threading.Lock()
timings: dict[str, list[float]] = {}
errors: list[str] = []


def record(kind: str, started: float) -> None:
    with lock:
        timings.setdefault(kind, []).append(time.perf_counter() - started)


def fail(message: str) -> None:
    with lock:
        errors.append(message)


class Client:
    """One browser: its own cookie jar, so every student has their own attempt cookie."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self) -> str:
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def request(self, kind, path, data=None, json_body=None, headers=None):
        url = self.base + path
        body = None
        headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode()
        if body is not None:
            headers["X-CSRFToken"] = self.csrf()
            headers["Referer"] = self.base + "/"
        started = time.perf_counter()
        try:
            with self.opener.open(urllib.request.Request(url, body, headers), timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
                final = r.geturl()
        except urllib.error.HTTPError as exc:
            record(kind, started)
            if exc.code != 409:  # 409 = "already finished", an answer rather than a failure
                fail(f"{kind}: HTTP {exc.code} {path}")
            return exc.code, exc.read().decode("utf-8", "replace"), url
        except Exception as exc:  # noqa: BLE001 - a load test reports everything
            record(kind, started)
            fail(f"{kind}: {type(exc).__name__}: {exc} {path}")
            return 0, "", url
        record(kind, started)
        return 200, text, final


def form_fields(page: str) -> dict:
    """The answer inputs of the test form: {name: ('choice', [values]) | ('text', None)}."""
    fields: dict = {}
    for tag in re.findall(r"<input\b[^>]*>|<textarea\b[^>]*>", page):
        name = re.search(r'name="(q_[^"]+)"', tag)
        if not name:
            continue
        if "radio" in tag or "checkbox" in tag:
            value = re.search(r'value="([^"]*)"', tag)
            fields.setdefault(name.group(1), ("choice", []))[1].append(
                html.unescape(value.group(1)) if value else ""
            )
        else:
            fields[name.group(1)] = ("text", None)
    return fields


def student(index: int, args, start_gate: threading.Barrier) -> None:
    client = Client(args.base)
    rng = random.Random(index)
    code = args.code
    status, page, _ = client.request("GET test page", f"/s/{code}/")
    if status != 200:
        return
    token = re.search(r'name="attempt_token"[^>]*value="([^"]+)"', page)
    if not token:
        token = re.search(r'value="([^"]+)"[^>]*name="attempt_token"', page)
    token = token.group(1) if token else ""
    fields = form_fields(page)
    answers = {}
    for name, (kind, values) in fields.items():
        answers[name] = rng.choice(values) if kind == "choice" else "0.75"
    first_name = f"Load Student {index:02d}"
    start_gate.wait()  # everybody starts at the same moment, like a class told to begin

    payload = {"unstarted": True, "tf_name": first_name, "attempt_token": token}
    names = list(fields)
    for n in range(min(args.saves, len(names))):
        # the page sends only what changed; sending everything so far is the heavier case
        payload["answers"] = {name[2:]: answers[name] for name in names[: n + 1]}
        client.request("autosave", f"/s/{code}/save/", json_body=dict(payload))
        payload.pop("unstarted", None)
        time.sleep(rng.uniform(0.2, args.think))
    form = {
        "csrfmiddlewaretoken": client.csrf(),
        "form_sent": "1",
        "attempt_token": token,
        "confirm_unanswered": "1",
    }
    form.update(answers)
    status, _, final = client.request("POST submit", f"/s/{code}/submit/", data=form)
    if status == 200 and "/done/" not in final:
        fail(f"student {index}: submit did not end on the done page ({final})")
    client.request("GET done page", f"/s/{code}/done/")


def teacher_poll(args, stop: threading.Event) -> None:
    user, _, password = args.teacher.partition(":")
    client = Client(args.base)
    _, page, _ = client.request("teacher login page", "/accounts/login/")
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    client.request(
        "teacher login",
        "/accounts/login/",
        data={
            "username": user,
            "password": password,
            "csrfmiddlewaretoken": token.group(1) if token else "",
        },
    )
    while not stop.is_set():
        client.request("teacher stats poll", f"/teach/sessions/{args.session}/stats/")
        stop.wait(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--code", required=True, help="access code of an open session")
    parser.add_argument("--students", type=int, default=32)
    parser.add_argument("--saves", type=int, default=4, help="autosaves before submitting")
    parser.add_argument("--think", type=float, default=1.0, help="max seconds between saves")
    parser.add_argument("--teacher", help="user:password, also poll the live stats once a second")
    parser.add_argument("--session", type=int, help="session id (needed with --teacher)")
    parser.add_argument("--max-seconds", type=float, default=2.0, help="slowest allowed request")
    args = parser.parse_args()
    if args.teacher and not args.session:
        parser.error("--teacher needs --session")

    gate = threading.Barrier(args.students)
    stop = threading.Event()
    poller = None
    if args.teacher:
        poller = threading.Thread(target=teacher_poll, args=(args, stop), daemon=True)
        poller.start()
    started = time.perf_counter()
    threads = [threading.Thread(target=student, args=(i, args, gate)) for i in range(args.students)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    if poller:
        poller.join(5)
    wall = time.perf_counter() - started

    print(f"{args.students} students, {wall:.1f} s wall time\n")
    print(f"{'request':22} {'count':>6} {'p50':>8} {'p95':>8} {'max':>8}")
    slowest = 0.0
    for kind, values in sorted(timings.items()):
        values.sort()
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        slowest = max(slowest, values[-1])
        print(
            f"{kind:22} {len(values):6} {statistics.median(values):8.3f} {p95:8.3f} "
            f"{values[-1]:8.3f}"
        )
    print(f"\nerrors: {len(errors)}")
    for message in errors[:15]:
        print("  ", message)
    if slowest > args.max_seconds:
        print(f"slowest request {slowest:.2f} s is over the {args.max_seconds} s limit")
    return 1 if errors or slowest > args.max_seconds else 0


if __name__ == "__main__":
    sys.exit(main())
