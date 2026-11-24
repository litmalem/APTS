from pathlib import Path

from governance_ui.main_window import run_console


if __name__ == "__main__":
    raise SystemExit(run_console(Path(__file__).resolve().parent))
