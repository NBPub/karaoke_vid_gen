"""Direct frame drawing for the Pillow renderer.

`draw_frame` turns one `frame_state` dict into a finished RGB image, reproducing
the on-screen composition (stacked lyric lines + per-word fill, count-in dots,
wait bar, title card, progress bar). Pure and unit-testable — no ffmpeg.
"""
from __future__ import annotations
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from karaoke.config import Config
from karaoke.metadata import TrackMeta

# Bold TTFs tried when no explicit font_file is set (Windows first).
_FALLBACK_FONTS = ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf")
_WAIT_NOTES = "♪♫♪♫♪♫♪"   # 7 notes


def _rgb(hexs: str):
    h = hexs.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


@lru_cache(maxsize=16)
def _truetype(path: str, size: int):
    for p in (([path] if path else []) + list(_FALLBACK_FONTS)):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load_font(config: Config, size: int | None = None):
    """Bold TTF at the configured (or given) size; falls back to a system bold
    font and finally Pillow's default if none load."""
    r = config.render
    return _truetype(r.font_file or "", size or r.font_size)


# Symbol fonts that contain the musical-note glyphs (the bold UI font does not).
_NOTE_FONTS = ("C:/Windows/Fonts/seguisym.ttf", "C:/Windows/Fonts/seguiemj.ttf")


@lru_cache(maxsize=8)
def note_font(size: int):
    """A font that has the ♪/♫ glyphs, or None when no symbol font is available
    (callers then skip drawing the notes rather than rendering empty boxes)."""
    for p in _NOTE_FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return None


def _blend(c1, c2, t: float):
    return tuple(int(round(a * t + b * (1 - t))) for a, b in zip(c1, c2))


def _wrap_groups(lines):
    """Group each line with its following wrap=True continuation lines.
    Returns list of (start_index, [line_dicts])."""
    groups = []
    for idx, ln in enumerate(lines):
        if ln.get("wrap") and groups:
            groups[-1][1].append(ln)
        else:
            groups.append((idx, [ln]))
    return groups


def line_left_xs(lines, row_width, W):
    """Left x for each line, in order. Multi-line wrap groups share a left edge
    (block centered on the widest row); standalone lines are centered.
    `row_width` is called as row_width((index, line_dict)) -> px."""
    xs = []
    for start, group in _wrap_groups(lines):
        widths = [row_width((start + k, ln)) for k, ln in enumerate(group)]
        if len(group) > 1:
            left = (W - max(widths)) // 2
            xs.extend([left] * len(group))
        else:
            xs.append((W - widths[0]) // 2)
    return xs


def _draw_token(img, d, font, text, x, y, base, fill_rgb, frac):
    """Draw `text` at (x, y) in `base`; overlay its left `frac` slice in
    `fill_rgb` (the per-word fill). Returns the advance width in px."""
    d.text((x, y), text, font=font, fill=base)
    w = int(round(d.textlength(text, font=font)))
    if frac and frac > 0 and w > 0:
        fw = max(0, min(w, int(round(w * frac))))
        if fw > 0:
            asc, desc = font.getmetrics()
            h = max(1, asc + desc)
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((0, 0), text, font=font, fill=fill_rgb + (255,))
            sl = layer.crop((0, 0, fw, h))
            img.paste(sl, (x, y), sl)
    return w


def draw_frame(state: dict, config: Config, meta: TrackMeta | None = None) -> Image.Image:
    r = config.render
    W, H = r.width, r.height
    bg = _rgb(r.background)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    font = load_font(config)
    asc, desc = font.getmetrics()
    line_h = asc + desc
    gap = 14
    fill_rgb = _rgb(r.fill_color)
    role_color = {"active": _rgb(r.base_color), "past": _rgb(r.past_color),
                  "upcoming": _rgb(r.upcoming_color)}

    # --- lyric lines: stacked, vertically centered; wrap-groups left-justified ---
    lines = state.get("lines") or []
    if lines:
        block_h = len(lines) * line_h + (len(lines) - 1) * gap
        y = (H - block_h) // 2
        countin = state.get("countin")

        def tokens_for(ln):
            active = ln["role"] == "active"
            base = role_color.get(ln["role"], role_color["upcoming"])
            toks = []
            if active and countin is not None:
                toks.append(("●  ●  ● ", _rgb(r.upcoming_color), countin))
            for w in ln["words"]:
                toks.append((w["text"] + " ", base, w["fill"] if active else 0.0))
            return toks

        toks_per_line = [tokens_for(ln) for ln in lines]
        widths = [sum(int(round(d.textlength(t, font=font))) for t, _, _ in toks)
                  for toks in toks_per_line]
        xs = line_left_xs(lines, lambda i_ln: widths[i_ln[0]], W)
        for toks, x0 in zip(toks_per_line, xs):
            x = x0
            for text, tbase, frac in toks:
                x += _draw_token(img, d, font, text, x, y, tbase, fill_rgb, frac)
            y += line_h + gap

    # --- wait bar (bottom), with note recolor ---
    wait = state.get("wait")
    if wait is not None:
        bw, bh = int(W * 0.55), 26
        bx, by = (W - bw) // 2, int(H * 0.86)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                            outline=_rgb(r.base_color), width=2)
        fw = int(round((bw - 4) * max(0.0, min(1.0, wait))))
        fill_c = _rgb(r.wait_outro_color) if state.get("wait_outro") else _rgb(r.wait_fill_color)
        if fw > 0:
            d.rounded_rectangle([bx + 2, by + 2, bx + 2 + fw, by + bh - 2],
                                radius=(bh - 4) // 2, fill=fill_c)
        nfont = note_font(18)
        if nfont is not None:
            n = len(_WAIT_NOTES)
            for k, ch in enumerate(_WAIT_NOTES):
                pos = k / (n - 1)
                nx = bx + 16 + int((bw - 32) * pos)
                col = fill_rgb if wait >= pos else _rgb(r.base_color)
                d.text((nx, by + 3), ch, font=nfont, fill=col)

    # --- title card overlay (fades over the lyrics) ---
    title = state.get("title") or 0.0
    if title > 0 and meta is not None and (meta.artist or meta.title):
        card = Image.new("RGBA", (W, H), bg + (255,))
        cd = ImageDraw.Draw(card)
        rows = []
        if meta.artist:
            rows.append((meta.artist, _blend(_rgb(r.base_color), bg, 0.7)))
            rows.append(("", None))
        rows.append((meta.title or "", _rgb(r.base_color)))
        cblock = len(rows) * line_h + (len(rows) - 1) * gap
        cy = (H - cblock) // 2
        for txt, col in rows:
            if txt:
                tw = int(round(cd.textlength(txt, font=font)))
                cd.text(((W - tw) // 2, cy), txt, font=font, fill=col + (255,))
            cy += line_h + gap
        alpha = int(round(max(0.0, min(1.0, title)) * 255))
        card.putalpha(card.getchannel("A").point(lambda v: v * alpha // 255))
        img.paste(card, (0, 0), card)

    # --- progress bar (right edge, on top) ---
    prog = state.get("progress")
    if prog is not None:
        x1, x2 = W - 24 - 10, W - 24
        y1, y2 = int(H * 0.10), int(H * 0.90)
        d.rounded_rectangle([x1, y1, x2, y2], radius=5,
                            outline=_rgb(r.progress_outline_color), width=2)
        fh = int(round((y2 - y1 - 2) * max(0.0, min(1.0, prog))))
        if fh > 0:
            d.rounded_rectangle([x1 + 2, y1 + 2, x2 - 2, y1 + 2 + fh], radius=4,
                                fill=_rgb(r.progress_fill_color))

    return img
