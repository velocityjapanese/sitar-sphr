"""Per-frame sitar view: a real CC0 Met sitar with glowing playing points.

The instrument is a CC0 photograph of a sitar from The Metropolitan Museum of
Art (object 502150), cut out and placed on the cinematic stage. Points along
the strings light as the melody moves; the gourd glows on accents and sheds a
few warm embers. The synced paper score panel is drawn by the section
compositor.
"""
import math
import queue
import random
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from config import FPS, H, W
from render.scene import load_font, make_spark_sprite, palette
from render.score_layer import PANEL_H, PANEL_W, PANEL_X, PANEL_Y

BODY_PHOTO = Path(__file__).resolve().parents[1] / "assets" / "sitar_body.png"

TARGET_H = 1020.0
SITAR_X = 315.0
SITAR_BOTTOM = 1048.0
SITAR_Y = SITAR_BOTTOM - TARGET_H

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Playing points along the strings, high notes near the nut.
N_KEYS = 12
# Playing positions along the sitar neck, from the nut to the body.
KEY_NORM = (
    (0.335, 0.090), (0.365, 0.150), (0.395, 0.210), (0.425, 0.270),
    (0.455, 0.330), (0.485, 0.390), (0.515, 0.450), (0.545, 0.510),
    (0.575, 0.570), (0.605, 0.630), (0.635, 0.690), (0.665, 0.750),
)
BELL_NORM = (0.660, 0.915)
REED_NORM = (0.300, 0.060)


def _glow_sprite(size):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / c
    return np.clip(1.0 - r, 0, 1) ** 2.4


def _glow_rgba(size, color):
    alpha = _glow_sprite(size)
    rgb = np.ones((size, size, 3), np.float32) * color[None, None, :]
    return np.dstack([rgb, alpha * 255.0]).astype(np.uint8)


def _ring_rgba(size, radius, width, color):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    alpha = np.exp(-((r - radius) / width) ** 2)
    rgb = np.ones((size, size, 3), np.float32) * color[None, None, :]
    return np.dstack([rgb, np.clip(alpha, 0, 1) * 255.0]).astype(np.uint8)


def _clip_add(roi, add):
    roi[:] = np.minimum(roi.astype(np.uint16) + add.astype(np.uint16),
                        255).astype(np.uint8)


_BODY_CACHE = {}


def _body_image():
    cached = _BODY_CACHE.get("body")
    if cached is not None:
        return cached
    src = Image.open(BODY_PHOTO).convert("RGBA")
    scale = TARGET_H / src.height
    width = int(round(src.width * scale))
    src = src.resize((width, int(round(TARGET_H))), Image.Resampling.LANCZOS)
    _BODY_CACHE["body"] = src
    return src


def make_sitar_base(palette_name):
    pal = palette(palette_name)
    accent = np.array(pal["accent"], dtype=np.float32)
    sitar = _body_image()

    # A gentle warm lift so the gold reads against the dark stage.
    arr = np.asarray(sitar, dtype=np.uint8).copy()
    rgb = arr[:, :, :3].astype(np.float32) / 255.0
    gray = rgb.mean(axis=2, keepdims=True)
    rgb = np.clip(gray + (rgb - gray) * 1.06, 0, 1)
    rgb = np.clip(rgb * 255.0 + accent[None, None, :] * 0.018, 0, 255)
    arr[:, :, :3] = rgb.astype(np.uint8)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        (SITAR_X + 0.22 * sitar.width, SITAR_BOTTOM - 16,
         SITAR_X + 0.78 * sitar.width, SITAR_BOTTOM + 40),
        fill=(0, 0, 0, 150))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)))
    canvas.alpha_composite(Image.fromarray(arr, "RGBA"), (int(SITAR_X), int(SITAR_Y)))
    return np.array(canvas, dtype=np.uint8)


class SitarStripGenerator:
    def __init__(self, section, notes, seed=0):
        pal = palette(section["palette"])
        # Signature cool-blue key light, matching the paper-score glow.
        self.key_color = np.array((86, 158, 214), dtype=np.float32)
        self.accent = np.array(pal["accent"], dtype=np.float32)
        self.spark_color = np.array((255, 188, 96), dtype=np.float32)
        self.base = make_sitar_base(section["palette"])
        sitar = _body_image()
        self.sitar_w, self.sitar_h = sitar.width, sitar.height
        self.keys = [(SITAR_X + nx * self.sitar_w, SITAR_Y + ny * self.sitar_h)
                     for nx, ny in KEY_NORM]
        self.bell = (SITAR_X + BELL_NORM[0] * self.sitar_w,
                     SITAR_Y + BELL_NORM[1] * self.sitar_h)
        self.reed = (SITAR_X + REED_NORM[0] * self.sitar_w,
                     SITAR_Y + REED_NORM[1] * self.sitar_h)

        self.key_halo = _glow_rgba(64, self.key_color)
        self.key_ring = _ring_rgba(62, 16.0, 4.0, self.key_color)
        self.bell_glow = _glow_rgba(230, self.key_color)
        self.bell_ring = _ring_rgba(190, 76.0, 18.0, self.key_color)
        self.reed_glow = _glow_rgba(80, self.key_color)
        self.reed_ring = _ring_rgba(64, 16.0, 5.0, self.key_color)
        self.spark = make_spark_sprite(18)

        self.energy = np.zeros(N_KEYS, dtype=np.float32)
        self.flash = np.zeros(N_KEYS, dtype=np.float32)
        self.bell_energy = 0.0
        self.reed_energy = 0.0
        self.last_meta = [(67, False)] * N_KEYS

        self.badge_sprites = {}
        self.badge_key = None
        self.badge_alpha = 0.0
        self.badge_since = -10.0
        self.badge_hold = 0.36

        self.section = section
        self.rng = random.Random(seed * 7919 + section["index"] * 104729)
        sec_start, sec_end = section["start"], section["end"]
        self.notes = [n for n in notes
                      if n["start"] <= sec_end and n["end"] >= sec_start - 0.4]
        self.sitar_notes = [n for n in self.notes if n["hand"] == "R"]
        self.frame_events = {}
        for n in self.sitar_notes:
            fr = int(round((n["start"] - sec_start) * FPS))
            if 0 <= fr < section["frames"]:
                self.frame_events.setdefault(fr, []).append(n)
        self.particles = []

    # ------------------------------------------------------------------
    def frames(self):
        sec = self.section
        dt = 1.0 / FPS
        for i in range(sec["frames"]):
            t = sec["start"] + i * dt
            layer = self.base.copy()
            self._on_onsets(i, t)
            self._decay(dt)
            self._draw_sitar(layer, t)
            self._update_badge(t)
            self._draw_badge(layer)
            yield layer.tobytes()

    # ------------------------------------------------------------------
    def _key_for_pitch(self, pitch):
        t = (max(60.0, min(91.0, float(pitch))) - 60.0) / 31.0
        return int(round((1.0 - t) * (N_KEYS - 1)))

    def _on_onsets(self, frame_index, t):
        for n in self.frame_events.get(frame_index, ()):
            si = self._key_for_pitch(n["pitch"])
            self.energy[si] = min(1.3, self.energy[si] + 0.6 + n["vel"] / 190.0)
            self.flash[si] = 1.0
            self.bell_energy = min(1.25, self.bell_energy + 0.48 + n["vel"] / 260.0)
            self.reed_energy = min(1.1, self.reed_energy + 0.5 + n["vel"] / 300.0)
            self.last_meta[si] = (int(n["pitch"]), bool(n.get("arp", False)))

    def _decay(self, dt):
        self.energy *= math.exp(-dt / 0.9)
        self.flash *= math.exp(-dt / 0.12)
        self.bell_energy *= math.exp(-dt / 0.62)
        self.reed_energy *= math.exp(-dt / 0.55)
        self.energy[self.energy < 0.004] = 0.0
        self.flash[self.flash < 0.02] = 0.0
        if self.bell_energy < 0.004:
            self.bell_energy = 0.0
        if self.reed_energy < 0.004:
            self.reed_energy = 0.0

    # ------------------------------------------------------------------
    def _draw_sitar(self, layer, t):
        # Reed light at the mouthpiece.
        if self.reed_energy > 0.02:
            a = min(0.85, 0.35 + 0.55 * self.reed_energy)
            x, y = self.reed
            self._blend_rgba(layer, self.reed_glow, int(x - 55), int(y - 55), a)
            self._blend_rgba(layer, self.reed_ring, int(x - 45), int(y - 45),
                             0.75 * self.reed_energy)

        # Bell glow: the sitar's signature light.
        if self.bell_energy > 0.02:
            e = min(1.0, self.bell_energy)
            x, y = self.bell
            bob = int(round(math.sin(t * 1.8) * 5))
            self._blend_rgba(layer, self.bell_glow,
                             int(x - 130), int(y - 130 + bob), 0.35 * e)
            self._blend_rgba(layer, self.bell_ring,
                             int(x - 110), int(y - 110 + bob), 0.45 * e)

        for si in range(N_KEYS):
            e = float(self.energy[si])
            if e <= 0.02:
                continue
            x, y = self.keys[si]
            self._blend_rgba(layer, self.key_halo, int(x - 43), int(y - 43),
                             0.24 * min(1.0, e))
            self._blend_rgba(layer, self.key_ring, int(x - 42), int(y - 42),
                             0.82 * min(1.0, e))

    def _stamp(self, layer, cx, cy, sprite, color, intensity):
        sh = sprite.shape[0]
        x0, y0 = int(round(cx - sh / 2)), int(round(cy - sh / 2))
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(W, x0 + sh), min(H, y0 + sh)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        sub = sprite[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0][:, :, None]
        add = (sub * color[None, None, :] * (255.0 * min(1.0, intensity))).astype(np.uint16)
        _clip_add(layer[cy0:cy1, cx0:cx1, :3], add)
        a = np.clip(sub[:, :, 0] * 255.0 * min(1.0, intensity * 0.9),
                    0, 255).astype(np.uint8)
        layer[cy0:cy1, cx0:cx1, 3] = np.maximum(
            layer[cy0:cy1, cx0:cx1, 3], a)

    def _blend_rgba(self, layer, sprite, x, y, alpha_mul):
        sh, sw = sprite.shape[:2]
        cx0, cy0 = max(0, x), max(0, y)
        cx1, cy1 = min(W, x + sw), min(H, y + sh)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        sub = sprite[cy0 - y:cy1 - y, cx0 - x:cx1 - x].astype(np.float32) / 255.0
        a = sub[:, :, 3:4] * alpha_mul
        roi = layer[cy0:cy1, cx0:cx1].astype(np.float32) / 255.0
        rgb = roi[:, :, :3] * (1.0 - a) + sub[:, :, :3] * a
        layer[cy0:cy1, cx0:cx1, :3] = (rgb * 255.0).astype(np.uint8)
        layer[cy0:cy1, cx0:cx1, 3] = np.maximum(
            layer[cy0:cy1, cx0:cx1, 3],
            (a[:, :, 0] * 255.0).astype(np.uint8))

    # ------------------------------------------------------------------
    def _spawn(self, si, note):
        count = 1 + int(note["vel"] / 130)
        x, y = self.bell
        for _ in range(count):
            self.particles.append({
                "x": x + self.rng.uniform(-30, 30),
                "y": y + self.rng.uniform(-20, 20),
                "vx": self.rng.uniform(-8, 40),
                "vy": self.rng.uniform(-55, -18),
                "life": self.rng.uniform(0.45, 1.0),
                "age": 0.0,
            })

    def _update_particles(self, layer, dt):
        alive = []
        sprite = self.spark
        sh = sprite.shape[0]
        for p in self.particles:
            p["age"] += dt
            if p["age"] >= p["life"]:
                continue
            p["x"] += p["vx"] * dt
            p["vy"] += 9 * dt
            p["y"] += p["vy"] * dt
            life = 1.0 - p["age"] / p["life"]
            x, y = int(p["x"]), int(p["y"])
            x0, y0 = x - sh // 2, y - sh // 2
            x1, y1 = x0 + sh, y0 + sh
            if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
                continue
            cx0, cy0 = max(0, x0), max(0, y0)
            cx1, cy1 = min(W, x1), min(H, y1)
            sub = sprite[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
            add = (sub[:, :, None] * self.spark_color[None, None, :]
                   * (life ** 1.4) * 110).astype(np.uint16)
            _clip_add(layer[cy0:cy1, cx0:cx1, :3], add)
            a = np.clip(sub * (life ** 1.3) * 120, 0, 255).astype(np.uint8)
            layer[cy0:cy1, cx0:cx1, 3] = np.maximum(
                layer[cy0:cy1, cx0:cx1, 3], a)
            alive.append(p)
        self.particles = alive

    # ------------------------------------------------------------------
    def _badge_sprite(self, pitch, arp):
        key = (pitch, arp)
        sprite = self.badge_sprites.get(key)
        if sprite is not None:
            return sprite
        note = f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"
        detail = "ornament" if arp else "sitar"
        f_note = load_font("sans", 14)
        f_detail = load_font("sans", 11)
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        nw = int(probe.textlength(note, font=f_note))
        dw = int(probe.textlength(detail, font=f_detail))
        pad_x, gap, h = 10, 8, 29
        w = pad_x * 2 + nw + gap + dw
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8, fill=(7, 10, 17, 214),
                            outline=tuple(int(c) for c in self.accent) + (105,), width=1)
        d.text((pad_x, 6), note, font=f_note, fill=(236, 243, 255, 240))
        d.text((pad_x + nw + gap, 9), detail, font=f_detail,
               fill=(204, 214, 232, 225))
        arr = np.asarray(img, dtype=np.float32)
        sprite = (arr[:, :, :3], arr[:, :, 3] / 255.0, w, h)
        self.badge_sprites[key] = sprite
        return sprite

    def _update_badge(self, t):
        loudest = int(np.argmax(self.energy))
        if self.energy[loudest] > 0.05:
            pitch, arp = self.last_meta[loudest]
            key = (pitch, loudest, arp)
            if key != self.badge_key and t - self.badge_since >= self.badge_hold:
                self.badge_key = key
                self.badge_since = t
            target = 1.0
        else:
            target = 0.0
        self.badge_alpha += (target - self.badge_alpha) * 0.18

    def _draw_badge(self, frame):
        if self.badge_key is None or self.badge_alpha < 0.03:
            return
        pitch, si, arp = self.badge_key
        rgb, alpha, w, h = self._badge_sprite(pitch, arp)
        sx, sy = self.keys[si]
        x = int(round(sx + 26))
        y = int(round(sy + 16))
        if (x + w > PANEL_X - 6 and x < PANEL_X + PANEL_W + 6
                and y + h > PANEL_Y - 6 and y < PANEL_Y + PANEL_H + 6):
            x = int(round(sx - w - 26))
        x = max(16, min(W - w - 16, x))
        y = max(16, min(H - h - 16, y))
        self._blend(frame, x, y, rgb, alpha, min(1.0, self.badge_alpha))

    def _blend(self, frame, x, y, rgb, alpha, mul=1.0):
        sh, sw = alpha.shape
        cx0, cy0 = max(0, x), max(0, y)
        cx1, cy1 = min(W, x + sw), min(H, y + sh)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        a = (alpha[cy0 - y:cy1 - y, cx0 - x:cx1 - x] * mul)[:, :, None]
        roi = frame[cy0:cy1, cx0:cx1]
        roi[:, :, :3] = np.clip(roi[:, :, :3] * (1.0 - a)
                                + rgb[cy0 - y:cy1 - y, cx0 - x:cx1 - x] * a,
                                0, 255).astype(np.uint8)
        roi[:, :, 3] = np.maximum(roi[:, :, 3], (a[:, :, 0] * 255).astype(np.uint8))


class PipeWriter:
    """Writes frames to a subprocess stdin on a background thread."""

    def __init__(self, stream, maxsize=4):
        self.stream = stream
        self.q = queue.Queue(maxsize=maxsize)
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def write(self, data):
        while not self.error:
            try:
                self.q.put(data, timeout=0.5)
                return
            except queue.Full:
                continue

    def close(self):
        while True:
            try:
                self.q.put(None, timeout=0.5)
                break
            except queue.Full:
                continue
        self.thread.join()

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                break
            if self.error is not None:
                continue
            try:
                self.stream.write(item)
            except (BrokenPipeError, ValueError, OSError) as exc:
                self.error = exc


def stream_section(section, notes, stream, seed=0):
    gen = SitarStripGenerator(section, notes, seed)
    writer = PipeWriter(stream)
    try:
        for frame in gen.frames():
            writer.write(frame)
    finally:
        writer.close()
        try:
            stream.close()
        except Exception:
            pass
