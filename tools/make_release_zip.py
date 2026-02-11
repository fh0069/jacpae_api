from __future__ import annotations

import argparse
import fnmatch
import os
from pathlib import Path
import zipfile
from datetime import datetime


# Carpetas/archivos a excluir SIEMPRE del ZIP
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "logs",
    "releases",
    "current",
    "shared",
}

EXCLUDE_FILE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.sqlite",
    "*.db",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    ".env",          # NO meter secretos
    ".env.*",        # NO meter secretos
]

# Qué incluimos explícitamente (si existen)
INCLUDE_TOP_LEVEL = [
    "requirements.txt",
    "README.md",
    ".env.example",
    "src",
    "tests",  # opcional, pero útil
]


def should_exclude(rel_path: str) -> bool:
    """Decide si un path relativo debe excluirse del ZIP."""
    parts = Path(rel_path).parts
    if parts and parts[0] in EXCLUDE_DIRS:
        return True

    # Si alguna parte del path es una carpeta excluida
    if any(p in EXCLUDE_DIRS for p in parts):
        return True

    # Excluir por patrones de fichero
    name = Path(rel_path).name
    for pat in EXCLUDE_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True

    return False


def add_path_to_zip(zf: zipfile.ZipFile, root: Path, path: Path) -> None:
    """Añade archivos de 'path' al zip, preservando estructura relativa a root."""
    if path.is_file():
        rel = path.relative_to(root).as_posix()
        if not should_exclude(rel):
            zf.write(path, arcname=rel)
        return

    # Directorio: recorrer recursivo
    for p in path.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if should_exclude(rel):
                continue
            zf.write(p, arcname=rel)


def validate_zip(zip_path: Path) -> None:
    """Validación rápida: que estén requirements.txt y src/app."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())

    if "requirements.txt" not in names:
        raise SystemExit("ERROR: El ZIP no contiene requirements.txt en la raíz.")

    # mínimo: src/app/ (tu estructura actual)
    if not any(n.startswith("src/app/") for n in names):
        raise SystemExit("ERROR: El ZIP no contiene src/app/. ¿Estás ejecutando desde la raíz correcta?")

    print("OK: ZIP validado (requirements.txt + src/app presentes).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea un ZIP de release para jacpae_api (sin secretos).")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Ruta raíz del proyecto (donde está requirements.txt). Por defecto: .",
    )
    parser.add_argument(
        "--out-dir",
        default="dist",
        help="Carpeta de salida del ZIP (se crea si no existe). Por defecto: dist",
    )
    parser.add_argument(
        "--name",
        default="jacpae_api_update",
        help="Nombre base del ZIP (sin .zip). Por defecto: jacpae_api_update",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Nombre con timestamp para no pisarte
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"{args.name}_{ts}.zip"

    # Comprobaciones básicas
    req = root / "requirements.txt"
    src = root / "src"
    if not req.exists():
        raise SystemExit(f"ERROR: No existe {req}. Ejecuta el script desde la raíz del proyecto.")
    if not src.exists():
        raise SystemExit(f"ERROR: No existe {src}. Falta carpeta src/.")

    print(f"Creando ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in INCLUDE_TOP_LEVEL:
            p = root / item
            if p.exists():
                add_path_to_zip(zf, root, p)

    validate_zip(zip_path)
    print(f"LISTO: {zip_path}")


if __name__ == "__main__":
    main()

print("SCRIPT ARRANCÓ OK")

