from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from locale import strcoll
from sqlite3 import Connection, Row
from typing import Iterator, Mapping, Sequence

from std2.sqllite3 import escape, with_transaction

from ...shared.executor import Executor
from ...shared.parse import lower, normalize
from .sql import sql, sqlt


def _like_esc(like: str) -> str:
    escaped = escape(nono={"%", "_"}, escape="!", param=like)
    return f"{escaped}%"


def _init(location: str) -> Connection:
    conn = Connection(location, isolation_level=None)
    conn.row_factory = Row
    conn.create_collation("X_COLL", strcoll)
    conn.create_function("X_LOWER", narg=1, func=lower, deterministic=True)
    conn.create_function("X_NORM", narg=1, func=normalize, deterministic=True)
    conn.create_function("X_LIKE_ESC", narg=1, func=_like_esc, deterministic=True)
    conn.executescript(sql("create", "pragma"))
    conn.executescript(sql("create", "tables"))
    return conn


class Database:
    def __init__(self, pool: ThreadPoolExecutor, location: str) -> None:
        self._pool = Executor(pool)
        self._conn: Connection = self._pool.submit(_init, location)

    def periodical(self, panes: Mapping[str, Sequence[str]]) -> None:
        def cont() -> None:
            def it() -> Iterator[Mapping]:
                for pane_id, words in panes.items():
                    for word in words:
                        yield {
                            "pane_id": pane_id,
                            "word": word,
                        }

            with closing(self._conn.cursor()) as cursor:
                with with_transaction(cursor):
                    template = sqlt("delete", "words")
                    instruction = template.substitute(pane_ids=tuple(panes.keys()))
                    cursor.execute(instruction, ())
                    cursor.executemany(sql("insert", "words"), it())

        self._pool.submit(cont)

    def select(self, prefix_len: int, word: str, active_pane: str) -> Sequence[str]:
        def cont() -> Sequence[str]:
            with closing(self._conn.cursor()) as cursor:
                cursor.execute(
                    sql("select", "words"),
                    {
                        "prefix_len": prefix_len,
                        "pane_id": active_pane,
                        "word": word,
                    },
                )
                return tuple(row["word"] for row in cursor.fetchall())

        return self._pool.submit(cont)

