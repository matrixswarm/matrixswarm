#!/usr/bin/env python3
"""
slice_sprite.py
Simple slicer for sprite sheets -> individual PNG icons.

Usage examples:
  python slice_sprite.py --input sprite.png --rows 2 --cols 3 --names hunt scatter ping shield lock cowbell --out icons/panel/npc_simulator/gameboard --size 32

"""
import argparse
import os
from PIL import Image, ImageOps

def parse_args():
    p = argparse.ArgumentParser(description="Slice sprite sheet into icons")
    p.add_argument("--input", "-i", required=True, help="Input sprite image path")
    p.add_argument("--rows", "-r", type=int, default=1, help="Number of rows in sprite")
    p.add_argument("--cols", "-c", type=int, default=1, help="Number of cols in sprite")
    p.add_argument("--names", "-n", nargs="+", help="Names for icons (left-to-right, top-to-bottom)")
    p.add_argument("--out", "-o", required=True, help="Output directory")
    p.add_argument("--size", "-s", type=int, default=0, help="Optional resize (square) e.g. 24 or 32. 0 = keep original slice size")
    p.add_argument("--trim", action="store_true", help="Trim transparent border from each slice before optionally resizing")
    return p.parse_args()

def main():
    args = parse_args()
    img = Image.open(args.input).convert("RGBA")
    w, h = img.size
    icon_w = w // args.cols
    icon_h = h // args.rows

    os.makedirs(args.out, exist_ok=True)

    total = args.rows * args.cols
    names = args.names or [f"icon_{i}" for i in range(total)]
    if len(names) < total:
        # fill remaining with generic names
        names += [f"icon_{i}" for i in range(len(names), total)]

    idx = 0
    for r in range(args.rows):
        for c in range(args.cols):
            left = c * icon_w
            upper = r * icon_h
            right = left + icon_w
            lower = upper + icon_h
            slice_img = img.crop((left, upper, right, lower))

            if args.trim:
                # trim transparent pixels
                bbox = slice_img.getbbox()
                if bbox:
                    slice_img = slice_img.crop(bbox)

            # optional resize while preserving aspect (pad to square)
            if args.size and args.size > 0:
                # fit into a square canvas with transparency
                slice_img = ImageOps.contain(slice_img, (args.size, args.size))
                # optionally center on square background
                canvas = Image.new("RGBA", (args.size, args.size), (0,0,0,0))
                cx = (args.size - slice_img.width) // 2
                cy = (args.size - slice_img.height) // 2
                canvas.paste(slice_img, (cx, cy), slice_img)
                slice_img = canvas

            out_name = names[idx] if idx < len(names) else f"icon_{idx}"
            out_path = os.path.join(args.out, f"{out_name}.png")
            slice_img.save(out_path)
            print(f"Saved: {out_path}")
            idx += 1

if __name__ == "__main__":
    main()
