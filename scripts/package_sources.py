#!/usr/bin/env python3
"""Package used local source files into standalone ZIPs with citation indexes."""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-mib", type=float, default=45)
    args = ap.parse_args()
    if not math.isfinite(args.max_mib) or args.max_mib <= 0:
        raise ValueError("--max-mib must be positive")
    manifest = args.manifest.resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    used = []
    seen = set()
    for source in data["sources"]:
        if source.get("used", True) is False:
            continue
        sid = source["id"]
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or sid in seen:
            raise ValueError("Invalid or duplicate source ID: " + str(sid))
        seen.add(sid)
        if not source.get("local_file"):
            raise ValueError("Used source has no saved file: " + sid)
        path = (manifest.parent / source["local_file"]).resolve()
        if not path.is_file():
            raise FileNotFoundError("Missing used source: " + sid)
        record = dict(source)
        record["local_file"] = "sources/" + sid + "_" + path.name
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["bytes"] = path.stat().st_size
        used.append((record, path))
    if not used:
        raise ValueError("No used sources to package")
    limit = int(args.max_mib * 1024 * 1024)
    groups = []
    group, size = [], 0
    for item in used:
        nbytes = item[0]["bytes"]
        if group and size + nbytes > limit:
            groups.append(group)
            group, size = [], 0
        group.append(item)
        size += nbytes
    if group:
        groups.append(group)
    outputs = [args.out / f"sources-part-{i + 1:02d}.zip" for i in range(len(groups))]
    if any(p.exists() for p in outputs):
        raise FileExistsError("Package output exists; choose a new output directory")
    index = ["# Source index", "", "Each ZIP is independently extractable; keep every part.", ""]
    for record, _ in used:
        index.extend([f"## {record['id']}: {record.get('title', '')}",
                      f"Authors: {record.get('authors', '')}", f"Year: {record.get('year', '')}",
                      f"Version: {record.get('version', '')}", f"DOI: {record.get('doi', '')}",
                      f"URL: {record.get('url', '')}", f"Slides: {record.get('slides', [])}",
                      f"File: {record['local_file']}", ""])
    buf = io.StringIO(newline="")
    fields = ["id", "title", "authors", "year", "version", "doi", "url", "slides", "local_file", "sha256"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for record, _ in used:
        writer.writerow({k: record.get(k, "") for k in fields})
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-package-", dir=args.out) as tmp:
        staged = []
        for i, group in enumerate(groups):
            temp = Path(tmp) / outputs[i].name
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
                for record, path in group:
                    z.write(path, record["local_file"])
                z.writestr("SOURCE_INDEX.md", "\n".join(index))
                z.writestr("sources.csv", "\ufeff" + buf.getvalue())
                z.writestr("sources.json", json.dumps([r for r, _ in used], ensure_ascii=False, indent=2))
            with zipfile.ZipFile(temp) as z:
                if z.testzip() is not None:
                    raise ValueError("ZIP integrity check failed")
            staged.append(temp)
        for temp, dest in zip(staged, outputs):
            temp.replace(dest)
    print(json.dumps({"source_count": len(used), "parts": [str(p) for p in outputs],
                      "oversize_sources": [r["id"] for r, _ in used if r["bytes"] > limit]}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(str(exc))
