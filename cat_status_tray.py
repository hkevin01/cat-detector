#!/usr/bin/env python3
"""Tiny Windows tray process for cat-detector status."""

from __future__ import annotations

import threading
import time

from cat_detector import open_status_page, read_runtime_status_snapshot


def _icon_image(freshness_label: str):
    from PIL import Image, ImageDraw

    palette = {
        "fresh": "#0a7a2f",
        "active": "#0a7a2f",
        "stale": "#a56a00",
        "idle": "#a56a00",
        "offline": "#b42318",
        "quiet": "#b42318",
        "unknown": "#6b7280",
    }
    color = palette.get(freshness_label, "#6b7280")
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), fill=color)
    draw.ellipse((18, 18, 46, 46), fill="#ffffff")
    draw.ellipse((24, 24, 40, 40), fill=color)
    return image


def _tooltip(status: dict) -> str:
    if not status.get("available"):
        return "cat-detector: no heartbeat yet"
    reason = status.get("last_detection_reason") or "none"
    return (
        f"cat-detector: {status.get('freshness_label')} | "
        f"input {status.get('input_freshness_label')} | last={reason}"
    )


def main() -> None:
    import pystray

    status = read_runtime_status_snapshot()
    icon = pystray.Icon(
        "cat-detector-status",
        _icon_image(status.get("freshness_label", "unknown")),
        _tooltip(status),
    )

    def _quit(_icon, _item):
        icon.stop()

    def _open(_icon, _item):
        open_status_page()

    status_item = pystray.MenuItem(lambda _item: _tooltip(read_runtime_status_snapshot()), None, enabled=False)
    icon.menu = pystray.Menu(
        status_item,
        pystray.MenuItem("Open status page", _open),
        pystray.MenuItem("Quit", _quit),
    )

    def _refresh_loop():
        while icon.visible:
            latest = read_runtime_status_snapshot()
            icon.title = _tooltip(latest)
            icon.icon = _icon_image(latest.get("freshness_label", "unknown"))
            icon.update_menu()
            time.sleep(5)

    threading.Thread(target=_refresh_loop, daemon=True).start()
    icon.run()