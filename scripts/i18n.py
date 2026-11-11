"""Translation workflow without GNU gettext.

    python -m uv run python scripts/i18n.py extract            # update django.po
    python -m uv run python scripts/i18n.py merge locale/uk/parts   # fill msgstr from fragments
    python -m uv run python scripts/i18n.py check              # fail if anything is untranslated
    python -m uv run python scripts/i18n.py compile            # django.po -> django.mo (commit it)

Run from the repository root. See README.md ("Translations").
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_django() -> None:
    import django
    from django.conf import settings

    if not settings.configured:
        if os.environ.get("DJANGO_SETTINGS_MODULE"):
            pass
        else:
            # Template parsing needs configured settings only; avoid touching the data folder.
            settings.configure(USE_I18N=True)
    django.setup()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-l", "--lang", default="uk")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("extract", help="collect msgids into django.po (keeps translations)")
    sub.add_parser("compile", help="compile django.po into django.mo")
    p_merge = sub.add_parser("merge", help="fill django.po from *.po fragments in DIR")
    p_merge.add_argument("dir", type=Path)
    p_merge.add_argument("--overwrite", action="store_true", help="replace existing translations")
    sub.add_parser("check", help="exit 1 on untranslated/fuzzy entries or placeholder mismatches")
    args = parser.parse_args(argv)

    _setup_django()
    from apps.core import i18n_tools as tools

    if args.command == "extract":
        stats = tools.extract(args.lang)
        for warning in stats["warnings"]:
            print(f"warning: {warning}")
        print(
            f"{stats['path']}: {stats['total']} messages, {stats['added']} new, "
            f"{stats['obsolete']} obsolete"
        )
        print(f"still untranslated: {len(tools.untranslated(args.lang))}")
        return 0

    if args.command == "compile":
        path, count = tools.compile_catalog(args.lang)
        print(f"{path}: {count} translated entries")
        return 0

    if args.command == "merge":
        result = tools.merge(args.dir, args.lang, overwrite=args.overwrite)
        print(f"filled {result['filled']} entries")
        for title, key in (("unmatched fragment entries", "unmatched"), ("conflicts", "conflicts")):
            if result[key]:
                print(f"\n{title} ({len(result[key])}):")
                for line in result[key]:
                    print(f"  {line}")
        left = result["untranslated"]
        print(f"\nstill untranslated ({len(left)}):")
        for msgid in left:
            print(f"  {msgid!r}")
        return 0

    problems = tools.check(args.lang)
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
