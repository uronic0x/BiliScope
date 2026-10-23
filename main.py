r"""Entry point; launch with .venv\Scripts\python.exe -I -B main.py."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from biliscope.runtime import configure, setup_logging, ROOT, RUNTIME, atomic_json, path_report
configure()
log = setup_logging()


def main():
    import argparse
    p = argparse.ArgumentParser(description='BiliScope — independent Bilibili assistant')
    p.add_argument('--doctor', action='store_true')
    p.add_argument('--test', action='store_true')
    args = p.parse_args()
    if args.test:
        import unittest
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
        return 0 if result.wasSuccessful() else 1
    if args.doctor:
        from biliscope.provenance import inventory
        report = path_report()
        report['dependencies'] = inventory()
        atomic_json(RUNTIME/'exports'/'doctor.json', report)
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(x['inside_project'] for x in report['paths'].values()) else 1
    try:
        from biliscope.ui_qt import App
    except ImportError:
        log.warning('PySide6 unavailable; falling back to Tkinter UI')
        from biliscope.ui import App
    App().run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        log.exception('Application failure')
        raise
