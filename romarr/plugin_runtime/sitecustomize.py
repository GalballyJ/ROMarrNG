"""Trusted startup hook that confines a Hub child before its plugin loads."""

from __future__ import annotations

import json
import os


def _install_filesystem_boundary() -> None:
    marker = os.environ.pop("ROMARR_HUB_LANDLOCK", "")
    if marker != "1":
        raise RuntimeError("ROMarr Hub plugin bootstrap marker is missing")

    # The trusted bootstrap consumes this after the boundary is active, then
    # removes it before the upstream runner imports the plugin.
    plugin_dir = os.environ.get("ROMARR_HUB_PLUGIN_DIR", "")
    assets_text = os.environ.pop("ROMARR_HUB_DATA_ASSETS", "[]")
    scratch_dir = os.environ.pop("ROMARR_HUB_SCRATCH", "")
    # The bootstrap path is already on sys.path, so keeping it in the
    # environment would only disclose host filesystem layout to the plugin.
    os.environ.pop("PYTHONPATH", None)
    try:
        assets = json.loads(assets_text)
        if not isinstance(assets, list) or not all(
            isinstance(item, str) for item in assets
        ):
            raise ValueError("asset path list is malformed")
        if not plugin_dir or not scratch_dir:
            raise ValueError("plugin or scratch path is missing")

        from rom_hub import sandbox
        # pyseccomp resolves libseccomp through the dynamic linker. That may
        # inspect ld.so.cache or invoke ldconfig, neither of which belongs in
        # the plugin's filesystem allowlist. Load it while still in trusted
        # bootstrap code; the Hub's later sandbox.install() reuses this module.
        seccomp_error = None
        try:
            import pyseccomp  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - keep Landlock independent
            seccomp_error = exc
        from landlock import install
        from syscall_guard import install as install_syscall_guard

        install(plugin_dir, assets, scratch_dir)
        # Landlock cannot restrict chmod/chown/time/xattr changes, and ROM
        # Hub's network filter permits fork/clone. Stack those denials before
        # the upstream runner imports its plugin.
        install_syscall_guard()
        if seccomp_error is not None:
            reason = ("seccomp library could not be loaded before filesystem "
                      f"confinement ({seccomp_error.__class__.__name__})")

            def refuse_without_seccomp():
                raise sandbox.SandboxUnavailable(reason)

            sandbox.install = refuse_without_seccomp
    except Exception as exc:  # noqa: BLE001 - report confinement failure to host
        try:
            from rom_hub import sandbox
        except Exception as import_error:  # noqa: BLE001
            raise RuntimeError(
                "ROMarr could not load the Hub sandbox: "
                f"{import_error.__class__.__name__}"
            ) from import_error

        reason = f"plugin confinement setup failed ({exc.__class__.__name__})"
        detail = str(exc).strip()
        if detail:
            reason += f": {detail}"

        def refuse_without_filesystem_sandbox():
            raise sandbox.SandboxUnavailable(reason)

        # The runner reports an unsandboxed status through its normal init
        # protocol. PluginProcess then refuses by default, while preserving
        # ROM Hub's explicit development-only unsandboxed override.
        sandbox.install = refuse_without_filesystem_sandbox


_install_filesystem_boundary()
