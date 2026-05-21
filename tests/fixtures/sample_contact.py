"""Generate a tiny SQLite DB that mimics the relevant Weixin 4.x contact table.

Run once to create sample_contact.db; tests assume it exists.
"""
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "sample_contact.db"


def build():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE contact (
            username TEXT PRIMARY KEY,
            nickname TEXT,
            remark TEXT,
            type INTEGER
        );
        INSERT INTO contact VALUES ('wxid_alice', 'Alice', '小爱', 3);
        INSERT INTO contact VALUES ('wxid_bob',   'Bob',   '',   3);
        INSERT INTO contact VALUES ('123@chatroom', 'Test Group', '', 2);

        CREATE TABLE chatroom (
            roomid TEXT PRIMARY KEY,
            memberlist TEXT
        );
        INSERT INTO chatroom VALUES ('123@chatroom', 'wxid_alice,wxid_bob');

        CREATE TABLE chatroom_member_nickname (
            roomid TEXT,
            wxid TEXT,
            display_name TEXT,
            PRIMARY KEY (roomid, wxid)
        );
        INSERT INTO chatroom_member_nickname VALUES ('123@chatroom', 'wxid_alice', '群里的爱丽丝');
    """)
    con.commit()
    con.close()
    print(f"Wrote {DB}")


if __name__ == "__main__":
    build()
