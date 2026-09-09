from __future__ import annotations

import io
from typing import Dict

from PIL import Image, ImageColor, ImageDraw, ImageFont


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
        # Local Windows development uses the same Cyrillic-capable font contract.
        try:
            return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf", size=size)
        except OSError:
            pass
        return ImageFont.load_default()

    @staticmethod
    def _wrap(draw, text, font, width):
        lines = []
        for paragraph in text.splitlines():
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).strip()
                if draw.textlength(candidate, font=font) <= width:
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                line = ""
                for char in word:
                    if line and draw.textlength(line + char, font=font) > width:
                        lines.append(line)
                        line = ""
                    line += char
            if line:
                lines.append(line)
        return lines

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

        text_color = palette[0] if palette else "#FFFFFF"
        try:
            ImageColor.getrgb(text_color)
        except (ValueError, TypeError):
            text_color = "#FFFFFF"
        shadow_color = "#000000"
        for scale in range(100, 9, -5):
            blocks = []
            for text, fraction, bold in ((headline, .12, True), (subtitle, .07, False), (cta, .06, True)):
                if not text:
                    continue
                font = self._load_font(max(10, int(height * fraction * scale / 100)), bold=bold)
                lines = self._wrap(draw, text, font, width - 4)
                line_height = max(font.size + 4, draw.textbbox((0, 0), "АруЙ", font=font)[3] + 4)
                blocks.append((font, lines, line_height))
            spacing = max(6, int(height * .025))
            needed = sum(len(lines) * line_height for _, lines, line_height in blocks) + spacing * max(0, len(blocks) - 1)
            if needed <= height:
                break
        else:
            raise ValueError("Overlay cannot fit into the image safely")
        current_y = y0 + max(0, (height - needed) // 2)
        for font, lines, line_height in blocks:
            for line in lines:
                text_x = x0 + max((width - draw.textlength(line, font=font)) / 2, 0)
                draw.text((text_x + 2, current_y + 2), line, font=font, fill=shadow_color)
                draw.text((text_x, current_y), line, font=font, fill=text_color)
                current_y += line_height
            current_y += spacing

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
