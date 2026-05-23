import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.request

SUBBACK_URL = "https://fate.5ch.io/liveuranus/subback.html"
DAT_BASE_URL = "https://fate.5ch.io/liveuranus/dat/{}.dat"
TARGET = "なんJNVA部"
OUT_DIR = pathlib.Path("data")
USER_AGENT = "Mozilla/5.0"


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def find_thread_id(subback_html: str) -> tuple[str, str]:
    pattern = re.compile(
        r"href=[\"'](?:[^\"']*test/read\.cgi/liveuranus/)?(\d+)/[^\"']*[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    checked = []
    for thread_id, raw_title in pattern.findall(subback_html):
        title = clean_html(raw_title)
        checked.append(f"{thread_id}: {title}")
        if TARGET in title:
            return thread_id, title

    (OUT_DIR / "debug_checked_threads.txt").write_text("\n".join(checked[:200]), encoding="utf-8")
    raise RuntimeError(f"target thread not found: {TARGET}; checked_links={len(checked)}")


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


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    try:
        subback_raw = fetch_bytes(SUBBACK_URL)
        subback_text = decode_subback(subback_raw)
        (OUT_DIR / "debug_subback.html").write_text(subback_text, encoding="utf-8")

        thread_id, title = find_thread_id(subback_text)

        dat_url = DAT_BASE_URL.format(thread_id)
        dat_text = decode_dat(fetch_bytes(dat_url))
        fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()

        meta = {
            "title": title,
            "thread_id": thread_id,
            "subback_url": SUBBACK_URL,
            "dat_url": dat_url,
            "fetched_at_utc": fetched_at,
        }

        (OUT_DIR / "latest.dat").write_text(dat_text, encoding="utf-8")
        (OUT_DIR / "latest.txt").write_text(dat_to_text(dat_text), encoding="utf-8")
        (OUT_DIR / "latest_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"OK: {title} / {dat_url}")
        return 0
    except Exception as e:
        (OUT_DIR / "last_error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
