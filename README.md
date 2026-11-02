# Ampify catalog

The catalog that Ampify's Marketplace reads: themes and extensions for Apple Music on Windows. Ampify itself lives in
its own repository; this one only holds what the Marketplace offers.

| Path | What it holds |
|---|---|
| `catalog.json` | Every element, with the address of its archive and the SHA-256 of that archive |
| `versions.json` | The Apple Music versions that the Ampify kernel accepts |
| `packages/` | The archives, one `.zip` per element and version, and the preview picture shown on its Marketplace card |
| `sources/` | The files of each archive, so anyone can read what an element does before installing it |

Ampify downloads an archive only from the address in `catalog.json` and refuses it when its SHA-256 differs from the
one written there. An element asks for permissions in its `manifest.json` (network hosts, audio gain, interface
places...), and the Marketplace shows them before the element is switched on.

## Add or update an element

You need [Ampify](https://github.com/Shirowwww/ampify) and, to send the pull request for you, the
[GitHub CLI](https://cli.github.com) signed in (`gh auth login`). You do not clone any repository.

1. Make the element (`ampify new <kind> <id>` gives a starter). To update one, raise `version` in its manifest.
2. Run `ampify test <folder>`.
3. Run `ampify publish <folder>`. It runs the same checks as `ampify validate` and `ampify test`, forks this
   repository (or reuses your fork), puts the folder in `sources/<id>/` on a branch, and opens the pull request with the
   description filled in. `--dry-run` shows what it would do and sends nothing. Without `gh`, it prints the steps to do
   by hand in the browser.

A pull request only adds or changes `sources/<id>/`. It never touches `packages/` or `catalog.json`.

### Review

A check runs on every pull request and comments with its result. It refuses an element when:

- its manifest is not valid, or the folder is not named after its `id`;
- its `version` is not higher than the one in `catalog.json`, or its archive already exists;
- its code calls something (`Ampify.http`, `Ampify.storage`, `Ampify.notify`...) without declaring the permission;
- a script looks minified or obfuscated (a line of more than 400 characters, names like `_0x1f3a`);
- the pull request changes `packages/` or `catalog.json`.

The check does not replace a person: a maintainer reads the code, and the permissions it asks for, before merging. An
element must also reach no host beyond the ones it declares.

### After the merge

A bot (`github-actions[bot]`) packs each changed element with `tools/pack.py` of Ampify, writes
`packages/<id>-<version>.zip` (with the preview picture next to it), updates the entry in `catalog.json` with the
address and the SHA-256, and commits that to `main`. The Marketplace lists the element from then on. An archive never
changes: a new version gets a new archive, and the old one stays, so a pinned install keeps working. Removing an element
is done by a maintainer.
