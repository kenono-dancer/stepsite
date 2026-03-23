#!/usr/bin/env python3
"""
WordPress ライブサイトから ID 670〜1600 の記事をスクレイピングして
Astro Markdown に変換するスクリプト
"""
import os, re, time, urllib.parse, hashlib, logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import markdownify

# ─── 設定 ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://itxdancer.com/step/?p="
POSTS_DIR   = Path(__file__).parent / "astro-microblog/src/content/blog"
IMAGES_DIR  = Path(__file__).parent / "astro-microblog/public/assets/images"
ID_START    = 670
ID_END      = 1600
WORKERS     = 6
TIMEOUT     = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "scrape.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    try:
        text = urllib.parse.unquote(text)
    except Exception:
        pass
    text = text.strip()
    text = re.sub(r"[\s/\\]+", "-", text)
    text = re.sub(r"[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f-]", "", text)
    return re.sub(r"-+", "-", text).strip("-") or "post"

def escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')

def download_image(url: str, year: str, month: str):
    filename = Path(urllib.parse.urlparse(url).path).name
    if not filename or "." not in filename:
        filename = hashlib.md5(url.encode()).hexdigest()[:12] + ".jpg"
    dest = IMAGES_DIR / year / month / filename
    pub_path = f"/assets/images/{year}/{month}/{filename}"
    if dest.exists():
        return pub_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(url, timeout=TIMEOUT, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return pub_path
    except Exception as e:
        log.warning(f"  IMG FAIL [{url}]: {e}")
        return url  # フォールバック: 元URLを返す

def html_to_md(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    md = markdownify.markdownify(html, heading_style="atx", strip=["script", "style"])
    return re.sub(r"\n{3,}", "\n\n", md).strip()

# ─── 記事スクレイパー ─────────────────────────────────────────────────────────

def scrape_post(pid: int) -> bool:
    """記事をスクレイプして Markdown に保存。記事でなければ False を返す"""
    url = BASE_URL + str(pid)
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return False
    except Exception as e:
        log.warning(f"  FETCH FAIL [{pid}]: {e}")
        return False

    soup = BeautifulSoup(r.text, "html.parser")

    # タイトル取得
    title_el = (
        soup.select_one(".entry-title")
        or soup.select_one(".post-title")
        or soup.select_one("h1.title")
        or soup.select_one("article h1")
    )
    if not title_el:
        return False
    title = title_el.get_text(strip=True)
    if not title:
        return False

    # 公開日取得
    date_el = (
        soup.select_one("time[datetime]")
        or soup.select_one(".entry-date")
        or soup.select_one(".post-date")
        or soup.select_one(".date")
    )
    pub_dt = None
    if date_el:
        dt_str = date_el.get("datetime") or date_el.get_text(strip=True)
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
            try:
                pub_dt = datetime.strptime(dt_str[:19], fmt[:len(dt_str[:19])])
                break
            except Exception:
                continue
    if pub_dt is None:
        # metaタグから取得試み
        meta_date = soup.select_one('meta[property="article:published_time"]')
        if meta_date:
            try:
                pub_dt = datetime.fromisoformat(meta_date["content"].replace("Z", "+00:00"))
            except Exception:
                pass
    if pub_dt is None:
        pub_dt = datetime.utcnow()

    year  = pub_dt.strftime("%Y")
    month = pub_dt.strftime("%m")
    pub_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # カテゴリ/タグ
    tags = []
    for el in soup.select(".cat-links a, .tag-links a, .post-categories a, .post-tags a, [rel='category tag'], [rel='tag']"):
        t = el.get_text(strip=True)
        if t and t not in tags:
            tags.append(t)

    # 本文取得
    content_el = (
        soup.select_one(".entry-content")
        or soup.select_one(".post-content")
        or soup.select_one("article .content")
        or soup.select_one("article")
    )
    if not content_el:
        return False

    # 本文内画像をダウンロードしてパス置換
    url_map = {}
    for img in content_el.find_all("img"):
        src = img.get("src", "")
        if "itxdancer.com" in src and "wp-content/uploads" in src:
            new_path = download_image(src, year, month)
            url_map[src] = new_path
            for part in img.get("srcset", "").split(","):
                parts = part.strip().split()
                if parts and parts[0].startswith("http"):
                    url_map[parts[0]] = new_path

    body_html = str(content_el)
    for old, new in url_map.items():
        body_html = body_html.replace(old, new)

    body_md = html_to_md(body_html)

    # アイキャッチ画像
    hero_path = ""
    hero_alt  = title
    og_img = soup.select_one('meta[property="og:image"]')
    if og_img and og_img.get("content"):
        src = og_img["content"]
        if "itxdancer.com" in src:
            hero_path = download_image(src, year, month)

    # description（先頭120文字）
    plain = soup.select_one('.entry-content, .post-content')
    desc = ""
    if plain:
        desc = plain.get_text(" ", strip=True)[:120].strip()
        if len(plain.get_text()) > 120:
            desc += "…"
    desc = re.sub(r"\s+", " ", desc)

    # スラッグ
    slug = slugify(title) or f"post-{pid}"

    # 既存ファイルと衝突チェック
    md_filename = f"{pub_dt.strftime('%Y-%m-%d')}-{slug}.md"
    md_path = POSTS_DIR / md_filename
    if md_path.exists():
        # 日付プレフィックスが同じ別記事の可能性 → IDをサフィックスに
        md_filename = f"{pub_dt.strftime('%Y-%m-%d')}-{slug}-{pid}.md"
        md_path = POSTS_DIR / md_filename

    # Frontmatter
    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]"
    fm = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f'pubDate: "{pub_iso}"',
        f'description: "{escape_yaml(desc)}"',
        f'author: "itxdancer_step"',
        f'tags: {tags_yaml}',
    ]
    if hero_path:
        fm += [f'image:', f'  url: "{hero_path}"', f'  alt: "{escape_yaml(hero_alt)}"']
    fm.append("---")

    md_path.write_text("\n".join(fm) + "\n\n" + body_md + "\n", encoding="utf-8")
    log.info(f"✓ [{pid}] {title[:50]}")
    return True


# ─── メイン ───────────────────────────────────────────────────────────────────

def main():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    ids = list(range(ID_START, ID_END + 1))
    log.info(f"Checking {len(ids)} IDs ({ID_START}〜{ID_END}) with {WORKERS} workers...")

    found = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(scrape_post, pid): pid for pid in ids}
        for f in as_completed(futs):
            if f.result():
                found += 1

    log.info(f"=== 完了: {found} 件の新記事を取得 ===")

if __name__ == "__main__":
    main()
