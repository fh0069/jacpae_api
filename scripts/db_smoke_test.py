import asyncio
import os

import asyncmy


async def main() -> None:
    host = os.environ["MARIADB_HOST"]
    port = int(os.environ.get("MARIADB_PORT", "3306"))
    user = os.environ["MARIADB_USER"]
    password = os.environ["MARIADB_PASSWORD"]
    db = os.environ["MARIADB_DB"]

    conn = await asyncmy.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        autocommit=True,
        connect_timeout=5,
        read_timeout=10,
        
    )

    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1;")
            row = await cur.fetchone()
            print("SELECT 1 ->", row)

            await cur.execute("SELECT VERSION();")
            row = await cur.fetchone()
            print("VERSION ->", row)

            await cur.execute("SHOW TABLES;")
            tables = await cur.fetchall()
            print(f"TABLES ({len(tables)}):")
            for t in tables[:20]:
                print(" -", t[0])
            if len(tables) > 20:
                print(" ...")
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
