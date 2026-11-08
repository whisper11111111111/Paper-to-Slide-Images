#!/usr/bin/env python3
"""Extract PDF text and page/crop renders with a provenance manifest."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("IDs must contain only ASCII letters, digits, _ or -")
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    if not math.isfinite(args.scale) or not 0 < args.scale <= 8:
        raise ValueError("--scale must be greater than 0 and at most 8")
    import fitz
    spec_path = args.spec.resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    pdf = (spec_path.parent / spec["pdf"]).resolve()
    sid = safe_id(spec["source_id"])
    with fitz.open(pdf) as doc:
        if doc.needs_pass:
            raise ValueError("PDF requires a password; supply an accessible source")
        jobs = []
        seen = set()
        for figure in spec.get("figures", []):
            fid = safe_id(figure["id"])
            if fid in seen:
                raise ValueError("Duplicate figure ID: " + fid)
            seen.add(fid)
            page = figure["page"]
            if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= len(doc):
                raise ValueError("Invalid 1-based page for " + fid)
            box = figure.get("box", [0, 0, 1, 1])
            if len(box) != 4 or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in box):
                raise ValueError("Invalid normalized crop for " + fid)
            l, t, r, b = box
            if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
                raise ValueError("Crop must lie within the page: " + fid)
            jobs.append((figure, page, box, args.out / f"{sid}_{fid}.png"))
        targets = [j[3] for j in jobs] + [args.out / f"{sid}_assets.json"]
        if spec.get("text", True):
            targets.append(args.out / f"{sid}_text.txt")
        if not args.overwrite and any(p.exists() for p in targets):
            raise FileExistsError("Output exists; use a new directory or --overwrite")
        args.out.mkdir(parents=True, exist_ok=True)
        records = []
        for figure, page_no, box, dest in jobs:
            page = doc[page_no - 1]
            w, h = page.rect.width, page.rect.height
            clip = fitz.Rect(box[0] * w, box[1] * h, box[2] * w, box[3] * h)
            page.get_pixmap(matrix=fitz.Matrix(args.scale, args.scale), clip=clip, alpha=False).save(dest)
            records.append({"id": figure["id"], "file": dest.name, "page": page_no,
                            "box": box, "locator": figure.get("locator", "")})
        if spec.get("text", True):
            text = "\n".join(f"=== PDF PAGE {i + 1} ===\n{p.get_text()}" for i, p in enumerate(doc))
            (args.out / f"{sid}_text.txt").write_text(text, encoding="utf-8")
        manifest = {"source_id": sid, "source_file": pdf.name,
                    "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    "page_count": len(doc), "figures": records}
        (args.out / f"{sid}_assets.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"pages": len(doc), "figures": len(jobs), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(str(exc))
