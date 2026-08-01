"""Windows compatibility launcher for the bundled documents-skill renderer.

LibreOffice's GUI launcher (soffice.exe) returns before headless conversion is
complete on this machine. The console launcher waits correctly. Windows also
requires a canonical file:/// URI for the temporary user profile.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


CANONICAL_RENDERER = Path(
    os.environ.get("MEETING_DOCUMENTS_RENDERER", "render_docx.py")
).expanduser()
SOFFICE_COM = Path(r"C:\Program Files\LibreOffice\program\soffice.com")


def main() -> None:
    spec = importlib.util.spec_from_file_location("bundled_render_docx", CANONICAL_RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load renderer: {CANONICAL_RENDERER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_run_cmd = module._run_cmd

    def windows_run_cmd(cmd: list[str], env: dict, verbose: bool):
        fixed = list(cmd)
        if fixed and fixed[0] == "soffice":
            fixed[0] = str(SOFFICE_COM)
        for idx, arg in enumerate(fixed):
            prefix = "-env:UserInstallation=file://"
            if arg.startswith(prefix):
                profile_path = Path(arg[len(prefix) :])
                fixed[idx] = "-env:UserInstallation=" + profile_path.as_uri()
        return original_run_cmd(fixed, env, verbose)

    module._run_cmd = windows_run_cmd
    module.main()


if __name__ == "__main__":
    main()
