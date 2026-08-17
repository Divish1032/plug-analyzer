# Third-party notices policy

`scripts/generate_third_party_notices.py` builds an inventory from the installed runtime dependency
closure of the `plug-analyzer` distribution. It evaluates dependency extras, records the installed
package name/version and project URL, and reproduces installed LICENSE, COPYING, COPYRIGHT, NOTICE,
and AUTHORS files when available.

This approach intentionally:

- follows the environment created from committed `uv.lock`, rather than an unpinned global Python;
- includes runtime packages that may be bundled by Nuitka, including requested extras;
- excludes development/build tools unless they are also runtime dependencies;
- remains deterministic for an unchanged installed environment; and
- flags missing installed license text for human release review instead of inventing a license.

The generated file is an inventory, not legal advice. Before any external/public distribution, a
responsible reviewer must resolve packages with absent or ambiguous metadata, confirm all bundled
native libraries and Qt licensing obligations, and approve the notices. Regenerate the file after
every dependency-lock change. Never hand-edit the generated copy inside a release directory; fix
the dependency or policy, regenerate it, and recreate checksums.
