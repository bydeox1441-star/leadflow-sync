"""Render docs/workflow.png from workflow/leadflow-sync.json (node positions and connections as n8n stores them).

Usage: python docs/render_workflow.py   (needs Pillow)
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = "/System/Library/Fonts/Helvetica.ttc"
SCALE, PAD, W_NODE, H_NODE = 0.9, 60, 158, 62
COLORS = {  # fill, border, label
    "webhook": ("#FFF1E6", "#F97316", "Trigger"),
    "code": ("#EEF2FF", "#6366F1", "Code"),
    "if": ("#ECFDF5", "#10B981", "If"),
    "httpRequest": ("#EFF6FF", "#3B82F6", "HTTP"),
}
ERROR, LINE, INK, MUTED = "#DC2626", "#9CA3AF", "#1B2A41", "#6B7280"


def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT, size, index=1 if bold else 0)
    except OSError:
        return ImageFont.load_default(size)


def main() -> Path:
    wf = json.loads((ROOT / "workflow" / "leadflow-sync.json").read_text())
    nodes = {n["name"]: n for n in wf["nodes"] if n["type"] != "n8n-nodes-base.stickyNote"}
    xs = [n["position"][0] for n in nodes.values()]
    ys = [n["position"][1] for n in nodes.values()]
    ox, oy = min(xs), min(ys)
    width = int((max(xs) - ox) * SCALE) + W_NODE + 2 * PAD
    height = int((max(ys) - oy) * SCALE) + H_NODE + 2 * PAD + 70

    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    d.text((PAD, 18), "LeadFlow Sync: n8n workflow (demo)", fill=INK, font=font(22, True))
    d.text((PAD, 46), "Blue = HTTP calls with 3 retries · green = decisions · red dashed = error output after retries",
           fill=MUTED, font=font(14))

    def box(name):
        x, y = nodes[name]["position"]
        left = PAD + (x - ox) * SCALE
        top = PAD + 70 + (y - oy) * SCALE
        return left, top, left + W_NODE, top + H_NODE

    for src, conn in wf["connections"].items():
        for out_idx, targets in enumerate(conn["main"]):
            for t in targets:
                a, b = box(src), box(t["node"])
                is_if = nodes[src]["type"].endswith(".if")
                is_err = out_idx == 1 and not is_if
                x1 = a[2]
                y1 = (a[1] + a[3]) / 2 + (0 if not (is_if or is_err) else (-10 if out_idx == 0 else 10))
                x2, y2 = b[0], (b[1] + b[3]) / 2
                mid = x1 + max(18, (x2 - x1) / 2) if x2 > x1 else x1 + 18
                pts = [(x1, y1), (mid, y1), (mid, y2), (x2, y2)] if x2 > x1 + 10 else \
                      [(x1, y1), (x1 + 18, y1), (x1 + 18, b[3] + 14), (x2 - 18, b[3] + 14), (x2 - 18, y2), (x2, y2)]
                color = ERROR if is_err else LINE
                for p, q in zip(pts, pts[1:]):
                    if is_err:  # dashed
                        n = max(1, int(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 // 8))
                        for i in range(0, n, 2):
                            s, e = i / n, min(1, (i + 1) / n)
                            d.line((p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s,
                                    p[0] + (q[0] - p[0]) * e, p[1] + (q[1] - p[1]) * e), fill=color, width=2)
                    else:
                        d.line((*p, *q), fill=color, width=2)
                d.polygon([(x2, y2), (x2 - 8, y2 - 5), (x2 - 8, y2 + 5)], fill=color)
                if is_if:
                    d.text((x1 + 4, y1 - 15), "true" if out_idx == 0 else "false", fill=MUTED, font=font(11))

    for name, n in nodes.items():
        kind = n["type"].split(".")[-1]
        fill, border, label = COLORS.get(kind, ("#F3F4F6", "#9CA3AF", kind))
        l, t, r, b = box(name)
        d.rounded_rectangle((l, t, r, b), radius=10, fill=fill, outline=border, width=2)
        d.text((l + 10, t + 7), label.upper(), fill=border, font=font(10, True))
        words, lines, cur = name.split(), [], ""
        for w in words:
            if len(cur + " " + w) > 19 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        for i, line in enumerate(lines[:2]):
            d.text((l + 10, t + 23 + i * 16), line, fill=INK, font=font(13, True))
        if n.get("retryOnFail"):
            d.text((r - 34, t + 7), f"×{n['maxTries']}", fill=border, font=font(10, True))

    out = ROOT / "docs" / "workflow.png"
    img.save(out, optimize=True)
    return out


if __name__ == "__main__":
    print(main())
