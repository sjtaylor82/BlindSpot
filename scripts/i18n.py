"""Maintain BlindSpot's translation catalogues.

Run from the repository root (Babel is required: ``pip install babel``)::

    python scripts/i18n.py extract      refresh locale/blindspot.pot
    python scripts/i18n.py update       merge new strings into every .po
    python scripts/i18n.py compile      build the .mo files the app loads
    python scripts/i18n.py check        validate translations, show coverage
    python scripts/i18n.py new pl Polski  start a new language

A translator only edits ``locale/<code>/LC_MESSAGES/blindspot.po``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from babel.messages import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "blindspot"
LOCALE = ROOT / "locale"
DOMAIN = "blindspot"
POT = LOCALE / f"{DOMAIN}.pot"
KEYWORDS = {
    "tr": None,
    "ntr": (1, 2),
    "ptr": ((1, "c"), 2),
    "tr_noop": None,
    "pgettext": ((1, "c"), 2),
}
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:![rsa])?(?::[^{}]*)?\}")
NATIVE_NAME_CONTEXT = "The name of this language, written in that language"


def version() -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        (SOURCE / "__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def catalogue_files() -> list[Path]:
    return sorted(LOCALE.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))


def build_template() -> Catalog:
    catalog = Catalog(
        project="BlindSpot",
        version=version(),
        charset="utf-8",
        copyright_holder="Sam Taylor",
        msgid_bugs_address="https://github.com/sjtaylor82/BlindSpot/issues",
    )
    method_map = [("**.py", "python")]
    options = {"**.py": {"encoding": "utf-8"}}
    for filename, lineno, message, comments, context in extract_from_dir(
        str(SOURCE),
        method_map=method_map,
        options_map=options,
        keywords=KEYWORDS,
        comment_tags=["Translators:"],
    ):
        location = (Path(SOURCE.name) / filename).as_posix()
        catalog.add(
            message,
            locations=[(location, 0)],
            auto_comments=comments,
            context=context,
        )
    return catalog


def command_extract(_: argparse.Namespace) -> int:
    catalog = build_template()
    LOCALE.mkdir(exist_ok=True)
    with POT.open("wb") as handle:
        write_po(
            handle,
            catalog,
            width=79,
            include_lineno=False,
            sort_by_file=True,
        )
    print(f"{POT.relative_to(ROOT)}: {len(catalog)} messages")
    return 0


def _write_po(catalog: Catalog, path: Path) -> None:
    with path.open("wb") as handle:
        write_po(handle, catalog, width=79, include_lineno=False)


def command_update(_: argparse.Namespace) -> int:
    command_extract(_)
    with POT.open("rb") as handle:
        template = read_po(handle)
    for path in catalogue_files():
        with path.open("rb") as handle:
            catalog = read_po(handle, locale=path.parent.parent.name)
        catalog.update(template, no_fuzzy_matching=True)
        _write_po(catalog, path)
        print(f"updated {path.relative_to(ROOT)}")
    return 0


def command_new(args: argparse.Namespace) -> int:
    path = LOCALE / args.code / "LC_MESSAGES" / f"{DOMAIN}.po"
    if path.exists():
        print(f"{path.relative_to(ROOT)} already exists", file=sys.stderr)
        return 1
    command_extract(args)
    with POT.open("rb") as handle:
        template = read_po(handle)
    catalog = Catalog(
        locale=args.code,
        project="BlindSpot",
        version=version(),
        charset="utf-8",
        header_comment=(
            f"# {args.native_name} translation for BlindSpot.\n"
            "# This file is distributed under the same license as the "
            "BlindSpot project."
        ),
        last_translator="BlindSpot contributors",
        language_team=args.native_name,
        msgid_bugs_address="https://github.com/sjtaylor82/BlindSpot/issues",
        fuzzy=False,
    )
    catalog.update(template)
    catalog.get("English", context=NATIVE_NAME_CONTEXT).string = (
        args.native_name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_po(catalog, path)
    print(f"created {path.relative_to(ROOT)}")
    return 0


def problems(catalog: Catalog) -> list[str]:
    """Translation mistakes that would break the app or the screen reader."""
    found: list[str] = []
    for message in catalog:
        if not message.id or not message.string:
            continue
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        strings = (
            message.string
            if isinstance(message.string, tuple)
            else (message.string,)
        )
        if isinstance(message.id, tuple) and len(strings) != (
            catalog.num_plurals
        ):
            found.append(f"{ids[0]!r}: expected {catalog.num_plurals} forms")
            continue
        source_names = set(PLACEHOLDER.findall(ids[0])) | set(
            PLACEHOLDER.findall(ids[-1])
        )
        for translated in strings:
            if not translated:
                continue
            names = set(PLACEHOLDER.findall(translated))
            if isinstance(message.id, tuple):
                # A plural form may leave out the count (e.g. "one" forms).
                if not names <= source_names:
                    found.append(
                        f"{ids[0]!r}: unknown placeholder in {translated!r}"
                    )
            elif names != source_names:
                found.append(
                    f"{ids[0]!r}: placeholders {sorted(source_names)} "
                    f"do not match {translated!r}"
                )
            if ids[0].count("&") != translated.count("&"):
                # A menu mnemonic (& before a letter) must survive.
                if _mnemonics(ids[0]) != _mnemonics(translated):
                    found.append(
                        f"{ids[0]!r}: keyboard mnemonic '&' mismatch in "
                        f"{translated!r}"
                    )
            if "\n" in ids[0] and "\n" not in translated:
                found.append(f"{ids[0]!r}: line breaks lost in {translated!r}")
    return found


def _mnemonics(text: str) -> int:
    return len(re.findall(r"&(?=[^\W_&])", text))


def command_check(_: argparse.Namespace) -> int:
    failures = 0
    with POT.open("rb") as handle:
        template = read_po(handle)
    total = len([m for m in template if m.id])
    current = {
        (m.id, m.context) for m in build_template() if m.id
    }
    recorded = {(m.id, m.context) for m in template if m.id}
    if current != recorded:
        print(
            "locale/blindspot.pot is out of date with the source; run "
            "'python scripts/i18n.py update' and commit the result.",
            file=sys.stderr,
        )
        failures += 1
    for path in catalogue_files():
        with path.open("rb") as handle:
            catalog = read_po(handle, locale=path.parent.parent.name)
        translated = sum(
            1
            for m in catalog
            if m.id
            and not m.fuzzy
            and (all(m.string) if isinstance(m.string, tuple) else m.string)
        )
        stale = [
            m.id
            for m in catalog
            if m.id and template.get(m.id, m.context) is None
        ]
        issues = problems(catalog)
        print(
            f"{path.parent.parent.name}: {translated}/{total} translated, "
            f"{len(issues)} problems, {len(stale)} obsolete"
        )
        for issue in issues:
            print(f"  {issue}")
        failures += len(issues)
    return 1 if failures else 0


def compile_catalogues(*, quiet: bool = False, output: Path | None = None) -> int:
    """Compile every .po to a .mo, beside it or under ``output``."""
    count = 0
    for path in catalogue_files():
        code = path.parent.parent.name
        with path.open("rb") as handle:
            catalog = read_po(handle, locale=code)
        if output is None:
            target = path.with_suffix(".mo")
        else:
            target = output / code / "LC_MESSAGES" / f"{DOMAIN}.mo"
            target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            write_mo(handle, catalog)
        count += 1
        if not quiet:
            print(f"compiled {target}")
    return count


def command_compile(_: argparse.Namespace) -> int:
    compile_catalogues()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("extract").set_defaults(run=command_extract)
    sub.add_parser("update").set_defaults(run=command_update)
    sub.add_parser("compile").set_defaults(run=command_compile)
    sub.add_parser("check").set_defaults(run=command_check)
    new = sub.add_parser("new")
    new.add_argument("code", help="language code such as pl or de")
    new.add_argument("native_name", help="language name in that language")
    new.set_defaults(run=command_new)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
