#!/usr/bin/env python3
"""What the catalog's workflows run: check the elements of a pull request, pack the ones that were merged.

    catalog_ci.py check   --ampify <Ampify checkout> --changed <paths.txt> --base-catalog <catalog.json> --summary <out.md>
    catalog_ci.py publish --ampify <Ampify checkout> --changed <paths.txt> --message <out.txt>

`paths.txt` lists the changed files, one per line (git diff --name-only). Only sources/<id>/ counts. The checks and the
packing come from tools/validate.py and tools/pack.py of Ampify, so the archives are the ones `tools/pack.py` writes.
Standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
RAW = "https://raw.githubusercontent.com/Shirowwww/ampify-catalog/main/packages"

# A line this long is not hand-written: the code is minified or packed, and nobody can review it.
MAX_LINE = 400
# Names such as _0x1f3a, as obfuscators make them.
OBFUSCATED_NAME = re.compile(r"\b_0x[0-9a-f]{3,}\b")
OBFUSCATED_LIMIT = 5

# Calls that need a permission, as in docs/extensions/api.md (section 4). A heuristic: it reads the code, it does not
# run it, and only names that have a single permission are listed.
PERMISSION_RULES = [
    (r"\bAmpify\.http\b", "network:"),
    (r"\bAmpify\.storage\b", "storage"),
    (r"\bAmpify\.notify\b", "notifications"),
    (r"\bAmpify\.keyboard\b", "ui.keyboard"),
    (r"\bAmpify\.tray\b", "ui.tray"),
    (r"\bAmpify\.audio\.(onFrame|analyze|loudness)\b", "audio.analyze"),
    (r"\bAmpify\.audio\.setGainDb\b", "audio.gain"),
    (r"\bAmpify\.audio\.eq\b", "audio.eq"),
    (r"\bAmpify\.player\.(play|pause|toggle|next|previous|seek)\s*\(", "player.control"),
    (r"\bAmpify\.player\.(state|lyrics)\s*\(", "player.read"),
]


def import_tools(ampify):
    sys.path.insert(0, os.path.join(ampify, "tools"))
    import pack  # noqa: PLC0415  (found once the path is set)
    return pack


def read_lines(path):
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def split_changes(paths):
    """The ids whose sources/<id>/ changed, and the other changed paths."""
    ids, others = set(), []
    for path in paths:
        parts = path.split("/")
        if parts[0] == "sources" and len(parts) > 2:
            ids.add(parts[1])
        elif parts[0] != "sources":
            others.append(path)
    return sorted(ids), others


def version_key(text):
    return tuple(int(number) for number in re.findall(r"\d+", text))


def code_without_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|\s)//.*$", "", text, flags=re.M)


def readability_errors(folder):
    """Minified or obfuscated scripts are refused: a reviewer has to be able to read them."""
    errors = []
    for current, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if not name.endswith((".js", ".mjs")):
                continue
            path = os.path.join(current, name)
            relative = os.path.relpath(path, folder).replace(os.sep, "/")
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            longest = max((len(line) for line in text.splitlines()), default=0)
            if longest > MAX_LINE:
                errors.append(f"{relative}: a line has {longest} characters (more than {MAX_LINE}): "
                              "the script looks minified, ship the readable source")
            if len(OBFUSCATED_NAME.findall(text)) > OBFUSCATED_LIMIT:
                errors.append(f"{relative}: the script looks obfuscated (names like _0x1f3a)")
    return errors


def permission_errors(folder, manifest):
    """The calls the code makes whose permission the manifest does not declare."""
    main = manifest.get("main")
    path = os.path.join(folder, main) if main else ""
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as handle:
        code = code_without_comments(handle.read())
    declared = manifest.get("permissions", [])
    errors = []
    for pattern, needed in PERMISSION_RULES:
        if re.search(pattern, code) and not any(item.startswith(needed) for item in declared):
            errors.append(f"{main} uses {re.search(pattern, code).group(0).rstrip('( ')} but the manifest does not "
                          f"declare the permission {needed}")
    return errors


def version_errors(manifest, published):
    """A new version must be higher than the one in the catalog; an id never seen has no archive yet."""
    identifier, version = manifest["id"], manifest["version"]
    errors = []
    if identifier in published and version_key(version) <= version_key(published[identifier]):
        errors.append(f"version {version} must be higher than {published[identifier]}, the one in the catalog")
    if os.path.exists(os.path.join(ROOT, "packages", f"{identifier}-{version}.zip")):
        errors.append(f"packages/{identifier}-{version}.zip already exists: an archive never changes, bump the version")
    return errors


def author_errors(manifest, owners, pr_author):
    """An element belongs to the GitHub account that sent it first: its `author` is that login, and only that account
    (or the catalog's owner, who passes no pr_author) may send a new version."""
    if not pr_author:
        return []
    expected = owners.get(manifest["id"], manifest.get("author", ""))
    if expected.lower() == pr_author.lower() and manifest.get("author", "").lower() == pr_author.lower():
        return []
    if manifest["id"] in owners:
        return [f"`{manifest['id']}` belongs to {expected}: only that account can send a new version"]
    return [f"author is {manifest.get('author', '')!r}, but the pull request comes from {pr_author}: "
            "use your GitHub login as `author`"]


def check_element(pack, identifier, published, owners=None, pr_author=""):
    """Returns (manifest or None, errors) for sources/<identifier>."""
    folder = os.path.join(ROOT, "sources", identifier)
    if not os.path.isdir(folder):
        return None, []
    try:
        manifest = pack.check_folder(folder)
    except pack.PackError as error:
        return None, [line.split(": ", 1)[-1] for line in str(error).splitlines()]
    errors = version_errors(manifest, published) + permission_errors(folder, manifest) + readability_errors(folder)
    errors += author_errors(manifest, owners or {}, pr_author)
    return manifest, errors


def plain(text):
    """Text from a manifest, safe inside a comment: no backtick, no @mention."""
    return str(text).replace("`", "'").replace("@", "@​")


def summary_lines(identifier, manifest, errors):
    if manifest is None and not errors:
        return [f"- `{identifier}`: removed from `sources/`. A maintainer removes the catalog entry by hand."]
    if manifest is None:
        return [f"- `{identifier}`: **not valid**"] + [f"  - {plain(error)}" for error in errors]
    permissions = ", ".join(f"`{plain(item)}`" for item in manifest.get("permissions", [])) or "none"
    head = f"- `{identifier}` {plain(manifest['version'])} ({plain(manifest['kind'])}), permissions: {permissions}: "
    if not errors:
        return [head + "ok"]
    return [head + "**needs changes**"] + [f"  - {plain(error)}" for error in errors]


def check(args):
    pack = import_tools(args.ampify)
    ids, others = split_changes(read_lines(args.changed))
    published, owners = {}, {}
    if os.path.isfile(args.base_catalog):
        with open(args.base_catalog, encoding="utf-8") as handle:
            entries = json.load(handle)["extensions"]
        published = {item["id"]: item["version"] for item in entries}
        owners = {item["id"]: item.get("author", "") for item in entries}
    # The catalog's owner may change several elements at once and keeps the elements without an author check.
    pr_author = "" if (args.pr_author or "").lower() == (args.owner or "").lower() else (args.pr_author or "")

    lines, failed = ["### Catalog check", ""], False
    if pr_author and len(ids) > 1:
        failed = True
        lines += [f"- This pull request changes {len(ids)} elements. Send one element per pull request."]
    protected = [path for path in others if path == "catalog.json" or path.startswith("packages/")]
    if protected:
        failed = True
        lines += ["- This pull request changes files that the bot writes after the merge "
                  f"({', '.join(f'`{plain(path)}`' for path in protected)}). Keep only `sources/<id>/`."]
    for identifier in ids:
        manifest, errors = check_element(pack, identifier, published, owners, pr_author)
        failed = failed or bool(errors)
        lines += summary_lines(identifier, manifest, errors)
    if not ids:
        lines.append("- No element under `sources/` changed.")
    lines += ["", "Passing these checks does not replace the review: a maintainer reads the code before the merge.",
              "After the merge, a bot packs the element into `packages/` and lists it in `catalog.json`."]
    with open(args.summary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if failed else 0


def sha256_of(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def publish_one(pack, identifier, catalog):
    """Packs sources/<identifier> unless this version is already there. Returns 'id version' when it packed."""
    folder = os.path.join(ROOT, "sources", identifier)
    manifest = pack.check_folder(folder)
    name = f"{identifier}-{manifest['version']}.zip"
    archive = os.path.join(ROOT, "packages", name)
    if os.path.exists(archive):
        scratch = archive + ".check"
        try:
            same = pack.build_archive(folder, scratch) == sha256_of(archive)
        finally:
            if os.path.exists(scratch):
                os.remove(scratch)
        if not same:
            raise pack.PackError(f"{name} is already published with other content: bump the version in {identifier}")
        print(f"{name}: already published, nothing to do")
        return None
    pack.pack(folder, archive, catalog, f"{RAW}/{name}")
    print(f"{name}: packed")
    return f"{identifier} {manifest['version']}"


def publish(args):
    pack = import_tools(args.ampify)
    ids, _others = split_changes(read_lines(args.changed))
    catalog = os.path.join(ROOT, "catalog.json")
    packed = []
    for identifier in ids:
        if not os.path.isdir(os.path.join(ROOT, "sources", identifier)):
            print(f"{identifier}: removed from sources/, its catalog entry is left for a maintainer")
            continue
        try:
            done = publish_one(pack, identifier, catalog)
        except (pack.PackError, OSError, KeyError, ValueError) as error:
            print(f"{identifier}: {error}", file=sys.stderr)
            return 1
        if done:
            packed.append(done)
    if packed:
        with open(args.message, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("feat: publish " + ", ".join(packed) + "\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Checks and packs the elements of the catalog.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "publish"):
        sub = commands.add_parser(name)
        sub.add_argument("--ampify", required=True, help="a checkout of Shirowwww/ampify (tools/ and schemas/)")
        sub.add_argument("--changed", required=True, help="a file listing the changed paths")
        if name == "check":
            sub.add_argument("--base-catalog", required=True, help="catalog.json as it was before the change")
            sub.add_argument("--summary", required=True, help="where to write the Markdown summary")
            sub.add_argument("--pr-author", default="", help="GitHub login of the pull request's author")
            sub.add_argument("--owner", default="", help="GitHub login of the catalog's owner")
        else:
            sub.add_argument("--message", required=True, help="where to write the commit message")
    args = parser.parse_args(argv)
    return check(args) if args.command == "check" else publish(args)


if __name__ == "__main__":
    sys.exit(main())
