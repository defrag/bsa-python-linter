"""Distribution integration test with a synthetic consumer and an invalid import."""

import json
import os
import subprocess
import sys
import tarfile
import tomllib
from email.parser import Parser
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def main() -> None:
    package = Path(__file__).resolve().parents[2]
    uv = os.environ.get("UV", "uv")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    with TemporaryDirectory(prefix="bsa-python-package-") as directory:
        root = Path(directory)

        def command(args: list[str]) -> None:
            subprocess.run(args, cwd=root, env=env, check=True, timeout=180)

        command([uv, "build", "--no-sources", str(package), "--out-dir", str(root / "dist")])
        wheels = list((root / "dist").glob("*.whl"))
        assert len(wheels) == 1, wheels
        sdists = list((root / "dist").glob("*.tar.gz"))
        assert len(sdists) == 1
        with tarfile.open(sdists[0]) as archive:
            assert any(name.endswith("/src/bsa_linter/py.typed") for name in archive.getnames())
        with ZipFile(wheels[0]) as archive:
            names = archive.namelist()
            assert "bsa_linter/py.typed" in names
            metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
            metadata = Parser().parsestr(archive.read(metadata_path).decode())
            project = tomllib.loads((package / "pyproject.toml").read_text())["project"]
            assert metadata["Name"] == project["name"], metadata
            assert metadata["Version"] == project["version"], metadata
            assert metadata["License-Expression"] == "MIT", metadata
            license_path = next(name for name in names if name.endswith("/licenses/LICENSE"))
            assert archive.read(license_path) == (package / "LICENSE").read_bytes()
            assert all(name.startswith("bsa_linter/") or ".dist-info/" in name for name in names), (
                names
            )
        environment = root / "environment"
        command([uv, "venv", "--python", sys.executable, str(environment)])
        python = environment / "bin/python"
        command([uv, "pip", "install", "--python", str(python), str(wheels[0])])
        command(
            [
                str(python),
                "-I",
                "-c",
                "import bsa_linter; from pathlib import Path; "
                f"assert Path(bsa_linter.__file__).is_relative_to({str(environment)!r})",
            ]
        )
        # Resolve types from the installed wheel, with no checkout on the search path.
        subprocess.run(
            [
                str(Path(sys.executable).with_name("pyright")),
                "--verifytypes",
                "bsa_linter",
                "--ignoreexternal",
            ],
            cwd=root,
            env={**env, "PATH": str(environment / "bin") + os.pathsep + env.get("PATH", "")},
            check=True,
            timeout=60,
        )
        app = root / "consumer"
        files = {
            "app/__init__.py": "",
            "app/api.py": "from app.catalog.deps import get_books\n",
            "app/catalog/__init__.py": "from .book import Book\n",
            "app/catalog/book.py": "class Book: pass\n",
            "app/catalog/deps.py": "from app.catalog import Book\ndef get_books(): return []\n",
            "app/catalog/_storage.py": "secret = 1\n",
        }
        for name, content in files.items():
            path = app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

        def check(status: int) -> dict[str, object]:
            result = subprocess.run(
                [str(environment / "bin/bsa-lint"), "--root", str(app), "--json"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            assert result.returncode == status, result.stdout + result.stderr
            payload = json.loads(result.stdout)
            assert payload["pass"] is (status == 0), payload
            return payload

        check(0)
        (app / "app/api.py").write_text("from app.catalog._storage import secret\n")
        assert check(1)["violations"]
        (app / "app/api.py").write_text(files["app/api.py"])
        check(0)
        (app / "pyproject.toml").write_text("[tool.bsa]\nallow-type-checking-imports = true\n")
        (app / "app/api.py").write_text(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from external_stubs.client import Client\n"
        )
        check(0)
        (app / "app/api.py").write_text(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from app.catalog._storage import secret\n"
        )
        assert check(1)["violations"]
        result = subprocess.run(
            [str(environment / "bin/bsa-lint"), "--root", str(root / "missing")],
            cwd=root,
            env=env,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 2, result
        print(
            "Packed Python checker: installed CLI, rejection, restoration and tool errors passed."
        )


if __name__ == "__main__":
    main()
