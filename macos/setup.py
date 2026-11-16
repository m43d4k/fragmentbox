"""Build the local viewer app: uv run --group macos-app python macos/setup.py py2app."""

import os
import sys
import tomllib
from pathlib import Path


def build_icon(root: Path) -> Path:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(root / "macos" / "FragmentBox.svg"))
    if not renderer.isValid():
        raise RuntimeError("Could not load the FragmentBox icon SVG.")

    output = root / "build" / "viewer-app"
    output.mkdir(parents=True, exist_ok=True)
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    icon = output / "FragmentBox.icns"
    for path in (output / "FragmentBox.png", icon):
        if not image.save(str(path)):
            raise RuntimeError(f"Could not save the icon: {path}")
    return icon


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The viewer app can only be built on macOS.")

    from setuptools import setup

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    icon = build_icon(root)

    # Keep the app build separate from the project's Hatch packaging configuration.
    os.chdir(root / "macos")
    setup(
        name="FragmentBox",
        version=project["version"],
        app=[{"script": str(root / "viewer.py"), "dest_base": "FragmentBox"}],
        py_modules=[],
        options={
            "py2app": {
                "alias": True,
                "iconfile": str(icon),
                "argv_emulation": False,
                "emulate_shell_environment": False,
                "bdist_base": str(root / "build" / "viewer-app"),
                "dist_dir": str(root / "dist"),
                "plist": {
                    "CFBundleName": "FragmentBox",
                    "CFBundleDisplayName": "FragmentBox",
                    "CFBundleIdentifier": "local.fragmentbox.viewer",
                    "CFBundleShortVersionString": project["version"],
                    "LSUIElement": False,
                    "NSHighResolutionCapable": True,
                },
            },
        },
    )


if __name__ == "__main__":
    main()
