import json

R2_BASE = "https://pub-519d670b800e4669a001260983688d43.r2.dev"  # no trailing slash

with open("index.json", encoding="utf-8") as f:
    entries = json.load(f)

for e in entries:
    # Update PDF path
    e["file_url"] = f"{R2_BASE}/{e['file']}"
    # Update cover path
    if e.get("cover"):
        cover_filename = e["cover"].replace("covers/", "")
        e["cover"] = f"{R2_BASE}/covers/{cover_filename}"

with open("index.json", "w", encoding="utf-8") as f:
    json.dump(entries, f, indent=2, ensure_ascii=False)

print(f"Updated {len(entries)} entries")