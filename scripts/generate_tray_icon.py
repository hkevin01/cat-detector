#!/usr/bin/env python3
"""Generate the Windows tray .ico asset from a simple branded drawing."""

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_path = root / "installer" / "cat-detector-status-tray.ico"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 244, 244), radius=48, fill="#f5f7f2")
    draw.ellipse((40, 40, 216, 216), fill="#1f7a3f")
    draw.ellipse((76, 76, 180, 180), fill="#ffffff")
    draw.ellipse((98, 98, 158, 158), fill="#1f7a3f")
    draw.polygon([(70, 62), (94, 26), (110, 76)], fill="#1f7a3f")
    draw.polygon([(186, 62), (162, 26), (146, 76)], fill="#1f7a3f")

    image.save(out_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()