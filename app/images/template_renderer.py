from __future__ import annotations

import io
from typing import Dict

from PIL import Image, ImageDraw, ImageFont


class TemplateRenderer:
    def __init__(self) -> None:
        self.font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        for path in self.font_paths:
            if bold and "Bold" not in path:
                continue
            if (not bold) and "Bold" in path:
                continue
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _draw_text_block(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        overlay: Dict[str, str],
        palette: list[str],
    ) -> None:
        x0, y0, x1, y1 = box
        width = x1 - x0
        height = y1 - y0
        headline = overlay.get("headline") or ""
        subtitle = overlay.get("subtitle") or ""
        cta = overlay.get("cta") or ""

        headline_font = self._load_font(max(int(height * 0.12), 28), bold=True)
        subtitle_font = self._load_font(max(int(height * 0.07), 20), bold=False)
        cta_font = self._load_font(max(int(height * 0.06), 18), bold=True)

        text_color = palette[0] if palette else "#FFFFFF"
        shadow_color = "#000000"
        spacing = int(height * 0.04)

        current_y = y0

        def draw_line(text: str, font: ImageFont.FreeTypeFont) -> None:
            nonlocal current_y
            if not text:
                return
            text_width = draw.textlength(text, font=font)
            text_x = x0 + max((width - text_width) / 2, 0)
            draw.text((text_x + 2, current_y + 2), text, font=font, fill=shadow_color)
            draw.text((text_x, current_y), text, font=font, fill=text_color)
            current_y += font.size + spacing

        draw_line(headline, headline_font)
        draw_line(subtitle, subtitle_font)
        draw_line(cta, cta_font)

    def render(
        self,
        background_bytes: bytes,
        overlay: Dict[str, str],
        layout: str,
        palette: list[str] | None = None,
    ) -> bytes:
        palette = palette or ["#FFFFFF"]
        img = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        width, height = img.size

        safe_margin = int(min(width, height) * 0.08)
        safe_box = (safe_margin, safe_margin, width - safe_margin, height - safe_margin)

        if layout == "left":
            text_box = (
                safe_box[0],
                safe_box[1],
                int(width * 0.55),
                safe_box[3],
            )
        elif layout == "bottom":
            text_box = (
                safe_box[0],
                int(height * 0.65),
                safe_box[2],
                safe_box[3],
            )
            draw.rectangle(
                [text_box[0], text_box[1], text_box[2], text_box[3]],
                fill=(0, 0, 0, 160),
            )
        else:
            text_box = (
                safe_box[0],
                safe_box[1],
                safe_box[2],
                safe_box[3],
            )

        self._draw_text_block(draw, text_box, overlay, palette)

        output = io.BytesIO()
        img.convert("RGB").save(output, format="PNG")
        return output.getvalue()
