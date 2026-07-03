import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.request

SUBBACK_URL = "https://fate.5ch.io/liveuranus/subback.html"
DAT_BASE_URL = "https://fate.5ch.io/liveuranus/dat/{}.dat"
THREAD_URL = "https://fate.5ch.io/test/read.cgi/liveuranus/{}/"
TARGET = "なんJNVA部"
MAX_THREADS = 2
OUT_DIR = pathlib.Path("data")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
COMMON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_bytes(url: str) -> bytes:
    headers = dict(COMMON_HEADERS)
    if "dat/" in url:
        headers["Accept"] = "text/plain,*/*;q=0.8"
        headers["Referer"] = SUBBACK_URL
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def decode_subback(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def decode_dat(raw: bytes) -> str:
    for enc in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def clean_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def find_threads(subback_html: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"href=[\"'](?:[^\"']*test/read\.cgi/liveuranus/)?(\d+)/[^\"']*[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    checked = []
    matches: dict[str, str] = {}
    for thread_id, raw_title in pattern.findall(subback_html):
        title = clean_html(raw_title)
        checked.append(f"{thread_id}: {title}")
        if TARGET in title:
            matches.setdefault(thread_id, title)

    (OUT_DIR / "debug_checked_threads.txt").write_text("\n".join(checked[:200]), encoding="utf-8")
    if not matches:
        raise RuntimeError(f"target thread not found: {TARGET}; checked_links={len(checked)}")

    newest = sorted(matches.items(), key=lambda item: int(item[0]), reverse=True)[:MAX_THREADS]
    return sorted(newest, key=lambda item: int(item[0]))


def count_dat_responses(dat_text: str) -> int:
    last_res = 0
    for no, line in enumerate(dat_text.splitlines(), start=1):
        if line.strip():
            last_res = no
    return last_res


def dat_to_text(dat_text: str) -> str:
    blocks = []
    for no, line in enumerate(dat_text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("<>")
        if len(parts) < 4:
            blocks.append(f"[{no}]\n{clean_html(line)}")
            continue
        name = clean_html(parts[0])
        mail = clean_html(parts[1])
        date_id = clean_html(parts[2])
        body = clean_html(parts[3])
        blocks.append(f"[{no}] {date_id} name:{name} mail:{mail}\n{body}")
    return "\n\n---\n\n".join(blocks) + "\n"


def load_previous_last_res() -> dict[str, int]:
    meta_path = OUT_DIR / "latest_meta.json"
    if not meta_path.exists():
        return {}

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    previous: dict[str, int] = {}
    threads = meta.get("threads")
    if isinstance(threads, list):
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            thread_id = str(thread.get("thread_id", ""))
            last_res = thread.get("last_res")
            if thread_id and isinstance(last_res, int) and last_res >= 0:
                previous[thread_id] = last_res
        return previous

    thread_id = str(meta.get("thread_id", ""))
    last_res = meta.get("last_res")
    if thread_id and isinstance(last_res, int) and last_res >= 0:
        previous[thread_id] = last_res
    elif thread_id:
        legacy_dat = OUT_DIR / "latest.dat"
        if legacy_dat.exists():
            try:
                previous[thread_id] = count_dat_responses(legacy_dat.read_text(encoding="utf-8"))
            except OSError:
                pass
    return previous


def build_thread_text(index: int, total: int, thread: dict[str, object]) -> str:
    previous_last_res = int(thread["previous_last_res"])
    last_res = int(thread["last_res"])
    if last_res > previous_last_res:
        new_range = f"{previous_last_res + 1}-{last_res}"
    else:
        new_range = "なし"

    header = (
        f"===== THREAD {index}/{total} =====\n"
        f"title: {thread['title']}\n"
        f"thread_id: {thread['thread_id']}\n"
        f"thread_url: {thread['thread_url']}\n"
        f"response_range: 1-{last_res}\n"
        f"previous_last_res: {previous_last_res}\n"
        f"new_response_range: {new_range}\n"
        f"===== POSTS =====\n\n"
    )
    return header + str(thread["text"]).rstrip() + "\n"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    try:
        previous_last_res = load_previous_last_res()
        subback_raw = fetch_bytes(SUBBACK_URL)
        subback_text = decode_subback(subback_raw)
        (OUT_DIR / "debug_subback.html").write_text(subback_text, encoding="utf-8")

        selected = find_threads(subback_text)
        fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        threads = []

        for thread_id, title in selected:
            dat_url = DAT_BASE_URL.format(thread_id)
            dat_text = decode_dat(fetch_bytes(dat_url))
            last_res = count_dat_responses(dat_text)
            previous = min(previous_last_res.get(thread_id, 0), last_res)
            threads.append(
                {
                    "title": title,
                    "thread_id": thread_id,
                    "thread_url": THREAD_URL.format(thread_id),
                    "dat_url": dat_url,
                    "last_res": last_res,
                    "previous_last_res": previous,
                    "new_res_start": previous + 1 if last_res > previous else None,
                    "new_res_end": last_res if last_res > previous else None,
                    "new_res_count": max(last_res - previous, 0),
                    "dat": dat_text,
                    "text": dat_to_text(dat_text),
                }
            )

        latest_text = "\n\n".join(
            build_thread_text(index, len(threads), thread)
            for index, thread in enumerate(threads, start=1)
        )
        meta = {
            "target": TARGET,
            "subback_url": SUBBACK_URL,
            "fetched_at_utc": fetched_at,
            "thread_count": len(threads),
            "threads": [
                {key: value for key, value in thread.items() if key not in {"dat", "text"}}
                for thread in threads
            ],
            "new_res_count_total": sum(int(thread["new_res_count"]) for thread in threads),
        }

        newest = threads[-1]
        (OUT_DIR / "latest.dat").write_text(str(newest["dat"]), encoding="utf-8")
        (OUT_DIR / "latest.txt").write_text(latest_text, encoding="utf-8")
        (OUT_DIR / "latest_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        error_path = OUT_DIR / "last_error.txt"
        if error_path.exists():
            error_path.unlink()

        thread_summary = ", ".join(
            f"{thread['thread_id']}:{thread['last_res']}" for thread in threads
        )
        print(f"OK: threads={len(threads)} / {thread_summary}")
        return 0
    except Exception as e:
        (OUT_DIR / "last_error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
