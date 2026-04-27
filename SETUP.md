# 🍯 Honey Archive — Setup Guide

## 1. Install Python dependencies

```bash
pip install anthropic pdf2image pillow
```

---

## 2. Install Poppler (Windows)

Poppler lets Python read PDF pages as images.

1. Go to: https://github.com/oschwartz10612/poppler-windows/releases
2. Download the latest `.zip` (e.g. `Release-24.08.0-0.zip`)
3. Extract it somewhere, e.g. `C:\poppler`
4. Add `C:\poppler\Library\bin` to your **System PATH**:
   - Search "Environment Variables" in Start
   - Edit `Path` under System variables
   - Add the bin folder
5. **Restart your terminal** after doing this

Test it worked: `pdfinfo --version` should print a version number.

---

## 3. Get your Anthropic API key

1. Go to https://console.anthropic.com
2. Click **API Keys** in the sidebar
3. Click **Create Key**, copy it

---

## 4. Set up your folder structure

```
manga-site/
  index.html        ← the frontend (already built)
  manga/            ← put ALL your PDFs here (or symlink)
```

You can either:
- Copy your PDFs into `manga-site/manga/`
- Or just leave them in `Documents/manga` and set the output dir separately

---

## 5. Run the indexer

```bash
set ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE

python indexer.py ^
  --manga-dir "C:\Users\Aayan\Documents\manga" ^
  --output-dir "C:\Users\Aayan\Documents\manga-site"
```

This will:
- Extract a cover thumbnail for every PDF → saved to `manga-site/covers/`
- Sample every 3rd page of each manga (up to 20 pages)
- Send all sampled pages to Claude in one call per manga
- Tag characters, genres, and themes
- Save everything to `manga-site/index.json`
- **Auto-resume** if interrupted — already indexed files are skipped

Estimated time: ~1-2 minutes per manga. Estimated cost: **~$1.00–1.50 total** for 95 files.

---

## 6. Make sure your manga folder is accessible

The frontend loads PDFs from `manga/filename.pdf` relative to `index.html`.

So your final structure should look like:

```
manga-site/
  index.html
  index.json          ← generated
  covers/             ← generated
    file1.jpg
    file2.jpg
    ...
  manga/
    Archers Desire (FateStay Night) [Kinkymation] - PDF Room.pdf
    ...
```

Either move/copy your PDFs into `manga-site/manga/`, or use a symlink:

```bash
# In PowerShell (run as admin):
New-Item -ItemType SymbolicLink -Path "C:\Users\Aayan\Documents\manga-site\manga" -Target "C:\Users\Aayan\Documents\manga"
```

---

## 7. Run the site locally

```bash
cd C:\Users\Aayan\Documents\manga-site
python -m http.server 8080
```

Then open **http://localhost:8080** in your browser.

> ⚠️ You must use a local server (not just open index.html directly) — browsers block PDF loading from `file://` URLs.

---

## 8. Share with Sumayyah (GitHub option)

Since some PDFs are large (up to 50MB), use **Git LFS** for them:

```bash
git lfs install
git lfs track "manga/*.pdf"
git add .gitattributes
git add .
git commit -m "initial archive"
git push
```

Then enable **GitHub Pages** on the repo (Settings → Pages → deploy from main branch).

> GitHub LFS free tier = 1GB storage / 1GB bandwidth per month. Your collection is ~700MB so it fits but bandwidth could be tight if you read a lot. Alternatively, self-host with Tailscale so only your devices can reach it.
