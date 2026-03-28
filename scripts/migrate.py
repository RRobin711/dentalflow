#!/usr/bin/env python3
"""Run Alembic migrations. Used in Docker entrypoints and Makefile."""

import os
import subprocess
import sys

def main():
    database_url = os.environ.get("DATABASE_URL", "postgresql://dentalflow:dentalflow@localhost:5432/dentalflow")
    os.environ["DATABASE_URL"] = database_url

    alembic_ini = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini")

    result = subprocess.run(
        ["alembic", "-c", alembic_ini, "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": database_url},
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
