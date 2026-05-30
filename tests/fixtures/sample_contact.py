"""Generate a tiny SQLite DB mirroring the REAL Weixin 4.x decrypted contact schema.

Schema verified against wechat-decrypt sidecar source (docs/sidecar-verification.md):
- table `contact`: columns username / nick_name (underscore) / remark — NO `type`
- table `contact_label`: label_id_ / label_name_ / sort_order_ (grouping lives here)
- table `Name2Id`: rowid -> user_name (recovers group msg senders in the message DB)
- NO `chatroom_member_nickname` table exists in real Weixin 4.x

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
    cur.executescript(
        """
        CREATE TABLE contact (
            username TEXT PRIMARY KEY,
            nick_name TEXT,
            remark TEXT,
            extra_buffer BLOB
        );
        INSERT INTO contact (username, nick_name, remark) VALUES ('wxid_alice', 'Alice', '小爱');
        INSERT INTO contact (username, nick_name, remark) VALUES ('wxid_bob',   'Bob',   '');
        INSERT INTO contact (username, nick_name, remark) VALUES ('123@chatroom', 'Test Group', '');

        CREATE TABLE contact_label (
            label_id_ INTEGER PRIMARY KEY,
            label_name_ TEXT,
            sort_order_ INTEGER
        );
        INSERT INTO contact_label VALUES (1, '客户', 0);

        CREATE TABLE Name2Id (
            user_name TEXT
        );
        INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'wxid_alice');
        INSERT INTO Name2Id (rowid, user_name) VALUES (2, 'wxid_bob');
        """
    )
    con.commit()
    con.close()
    print(f"Wrote {DB}")


if __name__ == "__main__":
    build()
