import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

BOARD = "liveuranus"
TARGET_THREAD_KEYWORD = "なんJNVA部"
SUBBACK_URL = f"https://fate.5ch.io/{BOARD}/subback.html"
OUTPUT_DIR = pathlib.Path("data")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

KEYWORDS = [
    "Anima", "anima", "LoRA", "lora", "Qwen", "GPT", "ChatGPT", "GPTImage", "GPT-Image",
    "Gemini", "Banana", "Claude", "ComfyUI", "Comfy", "WebUI", "Forge", "NovelAI", "NAI",
    "SDXL", "Pony", "Illustrious", "NoobAI", "Flux", "Civitai", "Hugging", "HuggingFace",
    "規約", "規制", "BAN", "ban", "販売", "FANZA", "DLsite", "Patreon", "Fantia",
    "生成", "学習", "モデル", "プロンプト", "キャプション", "タグ", "GPU", "VRAM", "4070", "4080", "4090", "5070", "5080", "5090",
]


def fetch_bytes(url: str) -> tuple[bytes, str, int]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.geturl(), getattr(resp, "status", 200)


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp932", "shift_jis", "euc_jp"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp932", errors="replace")


def clean_text(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def find_current_thread() -> dict:
    raw, final_url, status = fetch_bytes(SUBBACK_URL)
    text = decode_text(raw)

    # Example link shape varies:
    # ../test/read.cgi/liveuranus/1779353469/l50
    # /test/read.cgi/liveuranus/1779353469/
    pattern = re.compile(
        rf"<a[^>]+href=[\"'][^\"']*/test/read\.cgi/{re.escape(BOARD)}/(\d+)/[^\"']*[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    candidates = []
    for m in pattern.finditer(text):
        thread_id = m.group(1)
        title = clean_text(m.group(2))
        if TARGET_THREAD_KEYWORD in title:
            count_match = re.search(r"\((\d+)\)\s*$", title)
            count = int(count_match.group(1)) if count_match else None
            candidates.append({"thread_id": thread_id, "title": title, "subback_count": count})

    if not candidates:
        # Save a short debug file so failure can be inspected without dumping everything.
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / "debug_subback_head.txt").write_text(text[:4000], encoding="utf-8")
        raise RuntimeError(f"Could not find thread containing {TARGET_THREAD_KEYWORD!r} in subback.html")

    # subback is normally update-order sorted. Use first matching candidate.
    found = candidates[0]
    found["subback_url"] = final_url
    found["subback_status"] = status
    return found


def fetch_dat(thread_id: str) -> tuple[str, str]:
    urls = [
        f"https://fate.5ch.io/{BOARD}/dat/{thread_id}.dat",
        f"http://fate.5ch.io/{BOARD}/dat/{thread_id}.dat",
        f"https://fate.5ch.net/{BOARD}/dat/{thread_id}.dat",
        f"http://fate.5ch.net/{BOARD}/dat/{thread_id}.dat",
    ]
    last_error = None
    for url in urls:
        try:
            raw, final_url, _status = fetch_bytes(url)
            return decode_text(raw), final_url
        except Exception as e:  # keep trying mirrors/protocols
            last_error = e
    raise RuntimeError(f"Could not fetch dat for {thread_id}: {last_error}")


def parse_dat(dat_text: str) -> tuple[list[dict], str | None]:
    posts = []
    thread_title = None
    for idx, line in enumerate(dat_text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("<>")
        if len(parts) < 4:
            continue
        name = clean_text(parts[0])
        mail = clean_text(parts[1]) if len(parts) > 1 else ""
        date_id = clean_text(parts[2]) if len(parts) > 2 else ""
        body = clean_text(parts[3]) if len(parts) > 3 else ""
        title = clean_text(parts[4]) if len(parts) > 4 else ""
        if title:
            thread_title = title
        posts.append({
            "no": idx,
            "name": name,
            "mail": mail,
            "date_id": date_id,
            "body": body,
        })
    return posts, thread_title


def post_to_block(post: dict) -> str:
    header = f"[{post['no']}] {post.get('date_id', '')} name:{post.get('name', '')}".strip()
    body = post.get("body", "")
    return f"{header}\n{body}".strip()


def extract_links(posts: list[dict]) -> list[dict]:
    out = []
    url_re = re.compile(r"https?://[^\s<>\"']+")
    for post in posts:
        for url in url_re.findall(post.get("body", "")):
            url = url.rstrip(".,)]}、。）」)
            out.append({"no": post["no"], "url": url})
    return out


def keyword_hits(posts: list[dict]) -> list[dict]:
    hits = []
    for post in posts:
        body = post.get("body", "")
        matched = [kw for kw in KEYWORDS if kw in body]
        if matched:
            item = dict(post)
            item["matched_keywords"] = matched[:10]
            hits.append(item)
    return hits


def write_outputs(meta: dict, posts: list[dict], dat_url: str, thread_title: str | None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    title = thread_title or meta.get("title", "")
    thread_id = meta["thread_id"]
    thread_url = f"https://fate.5ch.io/test/read.cgi/{BOARD}/{thread_id}/"

    full_meta = {
        "target_keyword": TARGET_THREAD_KEYWORD,
        "title": title,
        "thread_id": thread_id,
        "thread_url": thread_url,
        "dat_url": dat_url,
        "subback_url": meta.get("subback_url"),
        "response_count": len(posts),
        "fetched_at_utc": fetched_at,
    }
    (OUTPUT_DIR / "latest_meta.json").write_text(
        json.dumps(full_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    header = (
        f"title: {title}\n"
        f"thread_id: {thread_id}\n"
        f"thread_url: {thread_url}\n"
        f"dat_url: {dat_url}\n"
        f"response_count: {len(posts)}\n"
        f"fetched_at_utc: {fetched_at}\n"
        "\n"
    )

    full_text = header + "\n---\n".join(post_to_block(p) for p in posts) + "\n"
    (OUTPUT_DIR / "latest.txt").write_text(full_text, encoding="utf-8")

    recent = posts[-250:]
    recent_text = header + "\n---\n".join(post_to_block(p) for p in recent) + "\n"
    (OUTPUT_DIR / "latest_recent.txt").write_text(recent_text, encoding="utf-8")

    hits = keyword_hits(posts)
    hits_text = header + "\n---\n".join(
        post_to_block(p) + f"\nmatched_keywords: {', '.join(p['matched_keywords'])}" for p in hits[-300:]
    ) + "\n"
    (OUTPUT_DIR / "latest_candidates.txt").write_text(hits_text, encoding="utf-8")

    links = extract_links(posts)
    links_text = header + "\n" + "\n".join(f"[{x['no']}] {x['url']}" for x in links[-300:]) + "\n"
    (OUTPUT_DIR / "latest_links.txt").write_text(links_text, encoding="utf-8")


def main() -> int:
    try:
        meta = find_current_thread()
        dat_text, dat_url = fetch_dat(meta["thread_id"])
        posts, thread_title = parse_dat(dat_text)
        if not posts:
            raise RuntimeError("dat fetched but no posts parsed")
        write_outputs(meta, posts, dat_url, thread_title)
        print(f"OK: {thread_title or meta['title']} / {len(posts)} posts")
        return 0
    except Exception as e:
        OUTPUT_DIR.mkdir(exist_ok=True)
        now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        (OUTPUT_DIR / "last_error.txt").write_text(f"{now}\n{type(e).__name__}: {e}\n", encoding="utf-8")
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
