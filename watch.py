import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.request

SUBBACK_URL = "https://fate.5ch.io/liveuranus/subback.html"
DAT_BASE_URL = "http://fate.5ch.io/liveuranus/dat/{}.dat"
TARGET = "なんJNVA部"
OUT_DIR = pathlib.Path("data")
USER_AGENT = "Mozilla/5.0"


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def decode_to_unicode(raw: bytes) -> str:
    for enc in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def clean_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def find_thread_id(subback_html: str) -> tuple[str, str]:
    pattern = re.compile(
        r"href=[\"']([^\"']*test/read\.cgi/liveuranus/(\d+)/[^\"']*)[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    for _url, thread_id, raw_title in pattern.findall(subback_html):
        title = clean_title(raw_title)
        if TARGET in title:
            return thread_id, title

    raise RuntimeError(f"target thread not found: {TARGET}")


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    try:
        subback_text = decode_to_unicode(fetch_bytes(SUBBACK_URL))
        thread_id, title = find_thread_id(subback_text)

        dat_url = DAT_BASE_URL.format(thread_id)
        dat_text = decode_to_unicode(fetch_bytes(dat_url))
        fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()

        meta = {
            "title": title,
            "thread_id": thread_id,
            "subback_url": SUBBACK_URL,
            "dat_url": dat_url,
            "fetched_at_utc": fetched_at,
        }

        (OUT_DIR / "latest.dat").write_text(dat_text, encoding="utf-8")
        (OUT_DIR / "latest.txt").write_text(dat_text, encoding="utf-8")
        (OUT_DIR / "latest_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"OK: {title} / {dat_url}")
        return 0
    except Exception as e:
        (OUT_DIR / "last_error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
