"""GUI entry point for packaged and source-based execution."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from importlib import import_module

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from plug_analyzer.ui import MainWindow
from plug_analyzer.ui.theme import apply_light_theme


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create or return the process-wide Qt application."""

    existing = QApplication.instance()
    app = existing or QApplication(list(argv) if argv is not None else sys.argv)
    QCoreApplication.setOrganizationName("Plug Analyzer Team")
    QCoreApplication.setApplicationName("Plug Analyzer")
    QCoreApplication.setApplicationVersion("0.2.2")
    apply_light_theme(app)
    return app


def run(
    argv: Sequence[str] | None = None,
    *,
    connect_controller: Callable[[MainWindow], object] | None = None,
) -> int:
    """Launch the UI and optionally attach an application controller.

    Keeping controller construction injectable makes the Qt layer independently
    testable and allows the command-line and packaged builds to share one pipeline.
    The returned controller is retained for the window lifetime.
    """

    app = create_application(argv)
    window = MainWindow()
    if connect_controller is not None:
        window._application_controller = connect_controller(window)  # type: ignore[attr-defined]
    window.show()
    return app.exec()


def main() -> int:
    """Console-script entry point."""

    def connect_default_controller(window: MainWindow) -> object | None:
        """Attach the application controller when the full prototype includes it."""

        try:
            module = import_module("plug_analyzer.controller")
        except ModuleNotFoundError as error:
            if error.name != "plug_analyzer.controller":
                raise
            return None
        connector = getattr(module, "connect_main_window", None)
        if connector is None:
            raise RuntimeError("plug_analyzer.controller must expose connect_main_window(window)")
        return connector(window)

    return run(connect_controller=connect_default_controller)


if __name__ == "__main__":
    raise SystemExit(main())
