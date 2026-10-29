# -*- coding: utf-8 -*-
"""Convert all .tlg under the extraction dir to PNG via tlg2png.exe, verify outputs."""
import os, sys, subprocess, shutil

TOOL = r"D:\K\galgame\tlg2png\tlg2png.exe"
DEST = None
pork = [os.path.join(r"D:\HY", d) for d in os.listdir(r"D:\HY") if "pork" in d.lower()][0]
game = [os.path.join(pork, g) for g in os.listdir(pork) if "陥落" in g][0]
DEST = os.path.join(r"D:\K\zcode\game\_extracted", os.path.basename(game), "KrkrExtract_Output")
print("dest:", DEST)

png_dir = os.path.join(DEST, "png")
os.makedirs(png_dir, exist_ok=True)

tlgs = []
for dp, _dn, fns in os.walk(DEST):
    for fn in fns:
        if fn.lower().endswith(".tlg"):
            tlgs.append(os.path.join(dp, fn))
print("tlg count:", len(tlgs))

ok = 0
fail = []
for i, t in enumerate(tlgs, 1):
    rel = os.path.relpath(t, DEST)
    flat = rel.replace("\\", "_").replace("/", "_")
    out = os.path.join(png_dir, flat[:-4] + ".png")
    r = subprocess.run([TOOL, t, out], capture_output=True)
    if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 8:
        with open(out, "rb") as f:
            if f.read(4) == b"\x89PNG":
                ok += 1
                continue
    fail.append((rel, r.returncode, r.stderr.decode("utf-8", "replace")[:120]))
    if os.path.isfile(out):
        os.remove(out)
    if len(fail) <= 10:
        print("FAIL:", fail[-1])

print("converted ok: %d / %d, fail: %d" % (ok, len(tlgs), len(fail)))
