"""
Manga PDF Indexer — Full Page Scan Edition
-------------------------------------------
Extracts every Nth page from each PDF, sends them all in ONE Claude API call
per manga for comprehensive character/genre/theme tagging.

pip install anthropic pdf2image pillow
Windows poppler: https://github.com/oschwartz10612/poppler-windows/releases
  → Extract → add the /bin folder to your PATH → restart terminal

Usage:
    set ANTHROPIC_API_KEY=sk-ant-...
    python indexer.py --manga-dir "C:/Users/Aayan/Documents/manga" --output-dir "C:/Users/Aayan/Documents/manga-site"

Optional flags:
    --every-nth 3        Sample every 3rd page (default: 3)
    --max-pages 20       Max pages to sample per manga (default: 20)
    --scan-dpi 72        DPI for analysis images — lower = fewer tokens (default: 72)
    --cover-dpi 120      DPI for cover thumbnail (default: 120)
"""

import os, re, json, base64, argparse, unicodedata
from pathlib import Path
import anthropic
from pdf2image import convert_from_path
from PIL import Image

MODEL = "claude-sonnet-4-20250514"


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "_", text)


def parse_filename(filename):
    name = filename.removesuffix(".pdf").replace(" - PDF Room", "").strip()

    artist_match = re.search(r"\[([^\]]+)\]", name)
    artist = artist_match.group(1) if artist_match else "Unknown"
    name = re.sub(r"\s*\[[^\]]+\]", "", name).strip()

    franchise_match = re.search(r"\(([^)]+)\)$", name) or re.search(r"\(([^)]+)\)", name)
    franchise = franchise_match.group(1) if franchise_match else None
    name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()
    if not franchise:
        name = re.sub(r"\s*\([^)]+\)", "", name).strip()

    vol_match = re.match(r"^(.*?)\s+-\s+(\d{1,2}(?:\.\d+)?)\s*(.*)?$", name)
    base_title, volume, volume_subtitle, series_id = name, None, None, None

    if vol_match:
        base_title = vol_match.group(1).strip()
        volume = float(vol_match.group(2))
        volume_subtitle = vol_match.group(3).strip() or None
        if volume_subtitle and volume_subtitle.lower().startswith(base_title.lower()):
            volume_subtitle = volume_subtitle[len(base_title):].lstrip("- ").strip() or None
        series_id = slugify(base_title)

    return dict(base_title=base_title, franchise=franchise, artist=artist,
                volume=volume, volume_subtitle=volume_subtitle, series_id=series_id)


def img_to_b64(img: Image.Image, max_width=400) -> str:
    """Resize image and return base64 JPEG string."""
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return base64.standard_b64encode(buf.getvalue()).decode()


def extract_pages(pdf_path, cover_out, cover_dpi, scan_dpi, every_nth, max_pages):
    """
    Returns:
      cover_ok  (bool)
      scan_imgs (list of PIL Images — sampled pages for analysis)
      page_count (int)
    """
    from pdf2image import pdfinfo_from_path
    POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"

    try:
        info = pdfinfo_from_path(pdf_path, poppler_path=POPPLER_PATH)
        total = info.get("Pages", 0)
    except Exception:
        total = 0

    # Extract cover (page 1) at higher DPI
    try:
        cover_pages = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=cover_dpi, poppler_path=POPPLER_PATH)
        cover_img = cover_pages[0]
        cover_img.thumbnail((600, 850), Image.LANCZOS)
        if cover_img.mode != "RGB":
            cover_img = cover_img.convert("RGB")
        cover_img.save(cover_out, "JPEG", quality=85)
        cover_ok = True
    except Exception as e:
        print(f"  x Cover failed: {e}")
        cover_ok = False
        cover_pages = []

    if total == 0:
        return cover_ok, [], 0

    # Adaptive sampling: every 2nd page for short manga, every 3rd for long ones
    if total <= 20:
        step = 2
    elif total <= 40:
        step = 3
    else:
        step = 4

    # Build page list: adaptive step, capped at max_pages
    page_nums = list(range(1, total + 1, step))[:max_pages]
    # Always include first and last page if not already there
    if total not in page_nums:
        page_nums.append(total)
    page_nums = sorted(set(page_nums))

    scan_imgs = []
    try:
        for pn in page_nums:
            pages = convert_from_path(pdf_path, first_page=pn, last_page=pn, dpi=scan_dpi, poppler_path=POPPLER_PATH)
            if pages:
                scan_imgs.append(pages[0])
    except Exception as e:
        print(f"  x Page extraction error: {e}")

    return cover_ok, scan_imgs, total


def analyze_manga(client, scan_imgs, meta):
    """
    Send all sampled pages in ONE API call.
    Returns dict with characters, genres, themes.
    """
    franchise_hint = f" from '{meta['franchise']}'" if meta["franchise"] else ""
    title_hint = f" titled '{meta['base_title']}'"

    prompt = (
        f"You are tagging an adult manga/doujinshi{franchise_hint}{title_hint}.\n"
        f"I'm giving you {len(scan_imgs)} pages sampled from throughout the entire manga.\n\n"
        "Analyze ALL pages and return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "characters": ["Full Canonical Name", ...],\n'
        '  "pairing": "string",\n'
        '  "acts": ["tag1", ...],\n'
        '  "outfits": ["tag1", ...],\n'
        '  "setting": ["tag1", ...]\n'
        "}\n\n"
        "characters: every named character that appears. Use canonical names (e.g. 'Makoto Niijima' not 'Queen'). Empty list if none identifiable.\n\n"
        "pairing: describe the participants as a short string. Examples:\n"
        "  '1boy1girl', '1boy2girls', '2girls', '1girl', 'group', '1boy1girl1boy' (for NTR/cuck scenarios)\n"
        "  Reflect the actual acts shown — if a second male is watching/cucked include them.\n\n"
        "acts — pick ALL that clearly occur across the pages:\n"
        "  vaginal, oral, anal, handjob, footjob, titjob, fingering, tribadism, scissoring,\n"
        "  yuri, femdom, maledom, netorare, cuckolding, voyeur, group, harem, reverse_harem,\n"
        "  wholesome, romance_only, teasing, grinding, creampie, ahegao, bondage, tentacle\n\n"
        "outfits — pick ALL that appear on any character:\n"
        "  swimsuit, maid, school_uniform, office_wear, catgirl, elf, warrior_armor, nurse,\n"
        "  idol, succubus, shrine_maiden, bunny_suit, wedding_dress, magical_girl, kimono,\n"
        "  lingerie, gym_clothes, naked, casual\n\n"
        "setting — pick ALL that apply:\n"
        "  fantasy, sci_fi, school, office, bedroom, outdoors, dungeon, public, home, supernatural\n\n"
        "Base your answer on ALL pages shown, not just the first one."
    )

    # Build content blocks: all images then the text prompt
    content = []
    for img in scan_imgs:
        b64 = img_to_b64(img, max_width=400)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
        })
    content.append({"type": "text", "text": prompt})

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": content}]
        )
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        # Sanitize
        result.setdefault("characters", [])
        result.setdefault("pairing", "unknown")
        result.setdefault("acts", [])
        result.setdefault("outfits", [])
        result.setdefault("setting", [])
        return result
    except json.JSONDecodeError as e:
        print(f"  x JSON error: {e}")
        return {"characters": [], "pairing": "unknown", "acts": [], "outfits": [], "setting": []}
    except Exception as e:
        print(f"  x API error: {e}")
        return {"characters": [], "pairing": "unknown", "acts": [], "outfits": [], "setting": []}


def build_index(manga_dir, output_dir, api_key, every_nth, max_pages, scan_dpi, cover_dpi):
    manga_path  = Path(manga_dir)
    output_path = Path(output_dir)
    covers_path = output_path / "covers"
    covers_path.mkdir(parents=True, exist_ok=True)

    client     = anthropic.Anthropic(api_key=api_key)
    pdfs       = sorted(manga_path.glob("*.pdf"))
    index_file = output_path / "index.json"

    print(f"Found {len(pdfs)} PDFs")
    print(f"Scanning every {every_nth}rd page, max {max_pages} pages per manga at {scan_dpi} DPI\n")

    existing = {}
    if index_file.exists():
        with open(index_file) as f:
            for e in json.load(f):
                existing[e["file"]] = e
        print(f"Resuming — {len(existing)} already indexed\n")

    entries = []
    total_cost_est = 0.0

    for i, pdf in enumerate(pdfs, 1):
        filename = pdf.name
        print(f"[{i}/{len(pdfs)}] {filename[:72]}")

        if filename in existing:
            print("  - Already indexed, skipping\n")
            entries.append(existing[filename])
            continue

        meta = parse_filename(filename)
        cover_slug     = slugify(filename.removesuffix(".pdf")) + ".jpg"
        cover_path     = covers_path / cover_slug
        cover_relative = f"covers/{cover_slug}"

        # Extract cover + sample pages
        print(f"  -> Extracting pages...")
        cover_ok, scan_imgs, page_count = extract_pages(
            str(pdf), str(cover_path), cover_dpi, scan_dpi, every_nth, max_pages
        )
        if not cover_ok:
            cover_relative = None

        print(f"  -> Sending {len(scan_imgs)} pages to Claude ({page_count} total pages in PDF, step=auto)...")

        ai = {"characters": [], "pairing": "unknown", "acts": [], "outfits": [], "setting": []}
        if scan_imgs:
            ai = analyze_manga(client, scan_imgs, meta)
            # Rough cost estimate: ~300 tokens/image for Sonnet at $3/MTok input
            est = len(scan_imgs) * 300 * 3 / 1_000_000
            total_cost_est += est

        print(f"  + Characters : {ai['characters'] or '(none)'}")
        print(f"  + Pairing    : {ai['pairing']}")
        print(f"  + Acts       : {ai['acts'] or '(none)'}")
        print(f"  + Outfits    : {ai['outfits'] or '(none)'}")
        print(f"  + Setting    : {ai['setting'] or '(none)'}")
        print(f"  ~ Est. cost so far: ${total_cost_est:.3f}")

        entry = {
            "file":            filename,
            "cover":           cover_relative,
            "base_title":      meta["base_title"],
            "franchise":       meta["franchise"],
            "artist":          meta["artist"],
            "volume":          meta["volume"],
            "volume_subtitle": meta["volume_subtitle"],
            "series_id":       meta["series_id"],
            "nsfw":            True,
            "page_count":      page_count,
            "characters":      ai["characters"],
            "pairing":         ai["pairing"],
            "acts":            ai["acts"],
            "outfits":         ai["outfits"],
            "setting":         ai["setting"],
        }
        entries.append(entry)

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        print()

    # Group standalones sharing a title into a series
    title_counts = {}
    for e in entries:
        title_counts[e["base_title"]] = title_counts.get(e["base_title"], 0) + 1
    for e in entries:
        if e["series_id"] is None and title_counts[e["base_title"]] > 1:
            e["series_id"] = slugify(e["base_title"])

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"\nDone! {len(entries)} entries written.")
    print(f"Estimated total API cost: ${total_cost_est:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manga-dir",   required=True)
    parser.add_argument("--output-dir",  required=True)
    parser.add_argument("--api-key",     default=None)
    parser.add_argument("--every-nth",   type=int, default=3,   help="Sample every Nth page (default 3)")
    parser.add_argument("--max-pages",   type=int, default=20,  help="Max pages per manga (default 20)")
    parser.add_argument("--scan-dpi",    type=int, default=72,  help="DPI for analysis pages (default 72)")
    parser.add_argument("--cover-dpi",   type=int, default=120, help="DPI for cover thumbnail (default 120)")
    args = parser.parse_args()

    build_index(args.manga_dir, args.output_dir, args.api_key,
                args.every_nth, args.max_pages, args.scan_dpi, args.cover_dpi)
