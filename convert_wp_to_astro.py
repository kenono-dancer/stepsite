#!/usr/bin/env python3
"""
WordPress WXR → Astro Microblog 変換スクリプト
必要ライブラリ: lxml, requests, beautifulsoup4, markdownify
インストール: pip install lxml requests beautifulsoup4 markdownify
"""

import os
import re
import sys
import logging
import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    sys.exit("ERROR: lxml が必要です。`pip install lxml` を実行してください。")

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests が必要です。`pip install requests` を実行してください。")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: beautifulsoup4 が必要です。`pip install beautifulsoup4` を実行してください。")

try:
    import markdownify
except ImportError:
    sys.exit("ERROR: markdownify が必要です。`pip install markdownify` を実行してください。")

# ─── 設定 ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
XML_PATH     = SCRIPT_DIR / "WordPress.2026-03-22.xml"
ASTRO_ROOT   = SCRIPT_DIR / "astro-microblog"
POSTS_DIR    = ASTRO_ROOT / "src" / "content" / "posts"
IMAGES_DIR   = ASTRO_ROOT / "public" / "assets" / "images"
CONFIG_TS    = ASTRO_ROOT / "src" / "content" / "config.ts"
REDIRECTS    = ASTRO_ROOT / "public" / "_redirects"

OLD_BASE     = "https://itxdancer.com/step"
NEW_BASE     = "https://step.itxdancer.com"

DOWNLOAD_TIMEOUT = 20  # 秒

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(SCRIPT_DIR / "convert.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

NS = {
    "wp":      "http://wordpress.org/export/1.2/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
}

# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def txt(el):
    """lxml要素のテキストをNoneセーフで返す"""
    return el.text.strip() if el is not None and el.text else ""


def slugify(text: str) -> str:
    """URLスラッグ用に変換（日本語はそのまま保持）"""
    # URLエンコード済みならデコード
    try:
        text = urllib.parse.unquote(text)
    except Exception:
        pass
    text = text.strip().lower()
    text = re.sub(r"[\s/\\]+", "-", text)
    text = re.sub(r"[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "post"


def escape_yaml(s: str) -> str:
    """YAML文字列として安全にエスケープ"""
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return s


def download_image(url: str, dest: Path) -> bool:
    """画像をダウンロード。失敗してもFalseを返すだけで例外を上げない"""
    if dest.exists():
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log.info(f"  ✓ DL: {url}")
        return True
    except Exception as e:
        log.warning(f"  ✗ DL FAILED [{url}]: {e}")
        return False


def image_dest_path(url: str, year: str, month: str) -> tuple[Path, str]:
    """
    画像URLから保存先Pathと /assets/... 形式のpublic相対パスを返す
    """
    filename = Path(urllib.parse.urlparse(url).path).name
    if not filename:
        filename = hashlib.md5(url.encode()).hexdigest()[:12] + ".jpg"
    rel = Path("assets") / "images" / year / month / filename
    dest = ASTRO_ROOT / "public" / rel
    public_path = "/" + rel.as_posix()
    return dest, public_path


def html_to_markdown(html: str) -> str:
    """Gutenberg HTMLをMarkdownに変換"""
    # Gutenbergコメントブロック除去
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # markdownify変換
    md = markdownify.markdownify(html, heading_style="atx", strip=["script", "style"])
    # 余分な空行を圧縮
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def replace_image_urls_in_md(md: str, url_map: dict[str, str]) -> str:
    """Markdown本文中のWordPress画像URLをローカルパスに置換"""
    for old_url, new_path in url_map.items():
        md = md.replace(old_url, new_path)
    return md

# ─── メイン処理 ───────────────────────────────────────────────────────────────

def parse_xml(xml_path: Path):
    log.info(f"XMLを解析中: {xml_path}")
    tree = etree.parse(str(xml_path), etree.XMLParser(recover=True))
    return tree.getroot()


def build_attachment_map(root) -> dict[str, str]:
    """attachment ID → URL マッピングを構築"""
    att_map = {}
    for item in root.findall(".//item"):
        pt = item.find("wp:post_type", NS)
        if pt is None or pt.text != "attachment":
            continue
        pid = item.find("wp:post_id", NS)
        att_url = item.find("wp:attachment_url", NS)
        if pid is not None and att_url is not None and att_url.text:
            att_map[txt(pid)] = txt(att_url)
    log.info(f"  添付ファイル数: {len(att_map)}")
    return att_map


def process_posts(root, att_map: dict[str, str]):
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    posts = [i for i in root.findall(".//item")
             if txt(i.find("wp:post_type", NS)) == "post"
             and txt(i.find("wp:status", NS)) == "publish"]
    log.info(f"公開記事数: {len(posts)}")

    redirects_lines = [
        "# itxdancer.com/step → step.itxdancer.com リダイレクト",
        f"https://itxdancer.com/step/*  https://step.itxdancer.com/:splat  301",
        "",
    ]

    for item in posts:
        title   = txt(item.find("title"))
        pub_str = txt(item.find("pubDate"))
        creator = txt(item.find("dc:creator", NS))
        slug_raw = txt(item.find("wp:post_name", NS))
        post_id  = txt(item.find("wp:post_id", NS))

        # pubDate パース
        try:
            pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            pub_dt = datetime.utcnow()
        year  = pub_dt.strftime("%Y")
        month = pub_dt.strftime("%m")
        pub_iso = pub_dt.isoformat()

        # カテゴリ・タグ
        tags = []
        for cat in item.findall("category"):
            domain = cat.get("domain", "")
            if domain in ("category", "post_tag") and cat.text:
                if cat.text not in tags:
                    tags.append(cat.text)

        # 抜粋（description）
        excerpt_el = item.find("excerpt:encoded", NS)
        excerpt    = txt(excerpt_el)
        if not excerpt:
            content_el = item.find("content:encoded", NS)
            raw_html   = txt(content_el)
            soup       = BeautifulSoup(raw_html, "html.parser")
            plain      = soup.get_text(" ", strip=True)
            excerpt    = plain[:120].strip() + ("…" if len(plain) > 120 else "")

        # 本文HTML → Markdown変換
        content_el = item.find("content:encoded", NS)
        raw_html   = txt(content_el)

        # 画像URLマップ（本文内の全画像）
        url_map = {}
        soup = BeautifulSoup(raw_html, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "itxdancer.com" in src or "wp-content/uploads" in src:
                dest, pub_path = image_dest_path(src, year, month)
                download_image(src, dest)
                url_map[src] = pub_path
                # srcset も置換用マップに追加
                srcset = img.get("srcset", "")
                for part in srcset.split(","):
                    parts = part.strip().split()
                    if parts and parts[0].startswith("http"):
                        url_map[parts[0]] = pub_path

        body_md = html_to_markdown(raw_html)
        body_md = replace_image_urls_in_md(body_md, url_map)

        # アイキャッチ画像（_thumbnail_id）
        hero_url     = ""
        hero_alt     = title
        hero_pub_path = ""
        for meta in item.findall("wp:postmeta", NS):
            mk = meta.find("wp:meta_key", NS)
            mv = meta.find("wp:meta_value", NS)
            if mk is not None and mk.text == "_thumbnail_id" and mv is not None and mv.text:
                thumb_id = mv.text.strip()
                att_url  = att_map.get(thumb_id, "")
                if att_url:
                    dest, pub_path = image_dest_path(att_url, year, month)
                    if download_image(att_url, dest):
                        hero_url      = att_url
                        hero_pub_path = pub_path
                break

        # スラッグ生成
        slug = slugify(slug_raw) or slugify(title) or f"post-{post_id}"

        # Frontmatter 組み立て
        tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]"
        fm_lines  = [
            "---",
            f'title: "{escape_yaml(title)}"',
            f'pubDate: "{pub_iso}"',
            f'description: "{escape_yaml(excerpt)}"',
            f'author: "{escape_yaml(creator)}"',
            f'tags: {tags_yaml}',
        ]
        if hero_pub_path:
            fm_lines.append(f'image:')
            fm_lines.append(f'  url: "{hero_pub_path}"')
            fm_lines.append(f'  alt: "{escape_yaml(hero_alt)}"')
        fm_lines.append("---")

        # ファイル書き出し
        md_filename = f"{pub_dt.strftime('%Y-%m-%d')}-{slug}.md"
        md_path = POSTS_DIR / md_filename
        md_path.write_text("\n".join(fm_lines) + "\n\n" + body_md + "\n",
                           encoding="utf-8")
        log.info(f"  ✓ POST: {md_filename}")

        # リダイレクト行
        wp_path = f"/step/?p={post_id}"
        redirects_lines.append(f"{wp_path}  /{slug}/  301")

    return redirects_lines


def write_config_ts():
    """src/content/config.ts を生成"""
    CONFIG_TS.parent.mkdir(parents=True, exist_ok=True)
    config = """\
import { defineCollection, z } from "astro:content";

const posts = defineCollection({
  type: "content",
  schema: z.object({
    title:       z.string(),
    pubDate:     z.coerce.date(),
    description: z.string().optional().default(""),
    author:      z.string().optional().default(""),
    tags:        z.array(z.string()).optional().default([]),
    image: z
      .object({
        url: z.string(),
        alt: z.string().optional().default(""),
      })
      .optional(),
  }),
});

export const collections = { posts };
"""
    CONFIG_TS.write_text(config, encoding="utf-8")
    log.info(f"✓ config.ts → {CONFIG_TS}")


def write_redirects(lines: list[str]):
    """public/_redirects を生成"""
    REDIRECTS.parent.mkdir(parents=True, exist_ok=True)
    REDIRECTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info(f"✓ _redirects → {REDIRECTS}")


def print_next_steps():
    print("""
╔══════════════════════════════════════════════════════════════╗
║              次のステップ（ローカル実行）                        ║
╚══════════════════════════════════════════════════════════════╝

1. Astro Microblog テンプレートのセットアップ（初回のみ）
   ─────────────────────────────────────────────────────
   cd astro-microblog
   npm create astro@latest . -- --template microblog --skip-houston
   # ※ すでにテンプレートがある場合はスキップ

2. 依存パッケージのインストール
   ─────────────────────────────────────────────────────
   npm install

3. 開発サーバーを起動（http://localhost:4321）
   ─────────────────────────────────────────────────────
   npm run dev

4. ビルド確認
   ─────────────────────────────────────────────────────
   npm run build && npm run preview

────────────────────────────────────────────────────────────────
📁 生成されたファイル:
   astro-microblog/src/content/posts/     ← Markdown記事
   astro-microblog/src/content/config.ts  ← コレクション型定義
   astro-microblog/public/assets/images/  ← ダウンロード画像
   astro-microblog/public/_redirects      ← 301リダイレクト設定
   convert.log                            ← 変換ログ
""")


def main():
    if not XML_PATH.exists():
        sys.exit(f"ERROR: XML が見つかりません: {XML_PATH}")

    root             = parse_xml(XML_PATH)
    att_map          = build_attachment_map(root)
    redirects_lines  = process_posts(root, att_map)

    write_config_ts()
    write_redirects(redirects_lines)
    print_next_steps()
    log.info("=== 変換完了 ===")


if __name__ == "__main__":
    main()
