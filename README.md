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

1. Put the element's folder (its `manifest.json` and files) in `sources/<id>/`.
2. From a clone of the Ampify repository, pack it and pin its hash:

   ```
   python tools/pack.py <catalog>/sources/<id> --out <catalog>/packages/<id>-<version>.zip \
       --catalog <catalog>/catalog.json \
       --url https://raw.githubusercontent.com/Shirowwww/ampify-catalog/main/packages/<id>-<version>.zip
   ```

   The archive is deterministic: the same folder always gives the same hash. When the manifest names a `preview`
   picture (and up to five `tags`), the picture is copied next to the archive as `<id>-<version>.jpg` (or `.png`) and
   the catalog entry points to it.
3. Open a pull request. A new version gets a new archive; the old one stays, so a pinned install keeps working.

An element is accepted when its manifest is valid, it asks only for the permissions its code uses, its code is
readable (no minified or obfuscated scripts), and it reaches no host beyond the ones it declares.
