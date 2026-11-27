#!/usr/bin/env python3
"""
Build the data pack (ADD, SVS, ICD) from the documentation site pages.

Each document is a list of site pages under docs/ plus pandoc metadata in
docs/datapack/<doc>.meta.yaml. The script writes one Markdown file per
document that pandoc can render on its own:

- snippets (`--8<-- "path"`, `--8<-- "path:section"`) are expanded, so the
  generated tables (docs/_gen/, from tools/gen_docs.py) and the example files
  are in the PDF exactly as on the site;
- admonitions (`!!! warning "Title"`) become block quotes;
- links to other site pages point at the site of this version;
- `{version}` and `{date}` in the metadata are filled in.

Then, unless --md-only, it runs pandoc with the eisvogel template.

Usage:
    python tools/build_datapack.py                 # docs/datapack/out/*.pdf
    python tools/build_datapack.py --md-only       # build/datapack/*.md only
    python tools/build_datapack.py --version 1.4.0 --date 2026-12-01

Implements: SVF-DEV-226
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
DATAPACK = DOCS / "datapack"
SITE = "https://opensvf.readthedocs.io/en/{version}/"

# Document -> site pages, in order. Each page's H1 becomes a chapter.
DOCUMENTS: dict[str, list[str]] = {
    "add": ["architecture.md", "abstraction-layer.md", "obc-modes.md"],
    "svs": ["validation.md", "system-tests.md"],
    "icd": ["icd.md"],
}

_SNIPPET = re.compile(r'^(?P<indent>[ \t]*)--8<-- "(?P<target>[^"]+)"[ \t]*$')
_SECTION = re.compile(r"--8<-- \[(start|end):([\w-]+)\]")
_ADMONITION = re.compile(r'^(?P<indent>[ \t]*)!!! (?P<kind>\w+)(?: "(?P<title>[^"]*)")?[ \t]*$')
_LINK = re.compile(r"\]\((?P<target>[^)\s]+)\)")


class DatapackError(Exception):
    pass


def _section(text: str, name: str, source: str) -> str:
    out, inside, found = [], False, False
    for line in text.splitlines():
        m = _SECTION.search(line)
        if m and m.group(2) == name:
            inside = m.group(1) == "start"
            found = found or inside
            continue
        if inside:
            out.append(line)
    if not found:
        raise DatapackError(f"{source}: no snippet section '{name}'")
    return "\n".join(out) + "\n"


def expand_snippets(text: str, repo: Path = REPO, depth: int = 0) -> str:
    """Replace each snippet line with the file (or section) it names."""
    if depth > 5:
        raise DatapackError("snippets nested more than 5 deep")
    out = []
    for line in text.splitlines():
        m = _SNIPPET.match(line)
        if m is None:
            out.append(line)
            continue
        target = m.group("target")
        path, _, section = target.partition(":")
        file = repo / path
        if not file.is_file():
            raise DatapackError(f"snippet target not found: {path} (run tools/gen_docs.py?)")
        body = file.read_text(encoding="utf-8")
        if section:
            body = _section(body, section, path)
        body = expand_snippets(body, repo, depth + 1)
        indent = m.group("indent")
        out.extend((indent + b) if b.strip() else "" for b in body.rstrip("\n").splitlines())
    return "\n".join(out) + "\n"


def convert_admonitions(text: str) -> str:
    """`!!! kind "Title"` plus its indented body -> a block quote."""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        m = _ADMONITION.match(lines[i])
        if m is None:
            out.append(lines[i])
            i += 1
            continue
        indent = m.group("indent")
        title = m.group("title") or m.group("kind").capitalize()
        body_indent = indent + "    "
        i += 1
        body = []
        while i < len(lines) and (lines[i].startswith(body_indent) or not lines[i].strip()):
            body.append(lines[i][len(body_indent):] if lines[i].strip() else "")
            i += 1
        while body and not body[-1]:
            body.pop()
        out.append(f"{indent}> **{title}.**")
        out.append(f"{indent}>")
        out.extend(f"{indent}> {b}".rstrip() for b in body)
        out.append("")
    return "\n".join(out) + "\n"


def rewrite_links(text: str, version: str) -> str:
    """Links to other site pages (`page.md`, `page.md#anchor`) -> the site."""
    base = SITE.format(version=version)

    def repl(m: re.Match[str]) -> str:
        target = m.group("target")
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            return m.group(0)
        page, _, anchor = target.partition("#")
        if not page.endswith(".md"):
            return m.group(0)
        path = "" if page == "index.md" else page[:-3] + "/"
        return f"]({base}{path}{'#' + anchor if anchor else ''})"

    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        out.append(line if fenced else _LINK.sub(repl, line))
    return "\n".join(out) + "\n"


def metadata(doc: str, version: str, date: str) -> str:
    meta = DATAPACK / f"{doc}.meta.yaml"
    if not meta.is_file():
        raise DatapackError(f"missing {meta.relative_to(REPO)}")
    text = meta.read_text(encoding="utf-8")
    return text.replace("{version}", version).replace("{date}", date)


def build_markdown(doc: str, version: str, date: str) -> str:
    parts = ["---", metadata(doc, version, date).rstrip("\n"), "---", ""]
    base = SITE.format(version=version)
    pages = ", ".join(f"[{p[:-3]}]({base}{p[:-3]}/)" for p in DOCUMENTS[doc])
    parts.append(f"This document is generated from the opensvf {version} "
                 f"documentation site: {pages}. The site is the reference; "
                 f"tables marked as generated are built from the sources.\n")
    for page in DOCUMENTS[doc]:
        text = (DOCS / page).read_text(encoding="utf-8")
        text = expand_snippets(text)
        text = convert_admonitions(text)
        text = rewrite_links(text, version)
        parts.append(text)
    return "\n".join(parts)


def _pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    if m is None:
        raise DatapackError("pyproject.toml has no version")
    return m.group(1)


def _commit_date() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%cs"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unreleased"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--version", default=None,
                        help="opensvf version for the title page and site links "
                             "(default: pyproject.toml)")
    parser.add_argument("--site-version", default=None,
                        help="Read the Docs version the links point at "
                             "(default: --version)")
    parser.add_argument("--date", default=None, help="date on the title page "
                        "(default: date of the last commit)")
    parser.add_argument("--md-dir", type=Path, default=REPO / "build" / "datapack")
    parser.add_argument("--out", type=Path, default=DATAPACK / "out")
    parser.add_argument("--md-only", action="store_true",
                        help="write the Markdown files only; do not run pandoc")
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--template", default=None,
                        help="eisvogel template (default: docs/datapack/eisvogel.latex "
                             "if present, else pandoc's 'eisvogel')")
    args = parser.parse_args()

    version = args.version or _pyproject_version()
    site_version = args.site_version or version
    date = args.date or _commit_date()
    try:
        gen = subprocess.run([sys.executable, str(REPO / "tools" / "gen_docs.py")])
        if gen.returncode != 0:
            raise DatapackError("tools/gen_docs.py failed")
        args.md_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for doc in DOCUMENTS:
            md = build_markdown(doc, version, date)
            if site_version != version:
                md = md.replace(SITE.format(version=version), SITE.format(version=site_version))
            path = args.md_dir / f"{doc}.md"
            path.write_text(md, encoding="utf-8")
            written.append(path)
        print(f"build_datapack: wrote {len(written)} Markdown files to {args.md_dir}")
        if args.md_only:
            return 0

        local = DATAPACK / "eisvogel.latex"
        template = args.template or (str(local) if local.is_file() else "eisvogel")
        args.out.mkdir(parents=True, exist_ok=True)
        for path in written:
            pdf = args.out / f"{path.stem}.pdf"
            subprocess.run([args.pandoc, str(path), "-o", str(pdf),
                            f"--template={template}", "--pdf-engine=xelatex"],
                           check=True)
            print(f"build_datapack: {pdf}")
    except DatapackError as e:
        print(f"build_datapack: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"build_datapack: pandoc failed ({e.returncode})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
