"""Tests for the persistence layer (against a throwaway SQLite db)."""
import uuid

import storage


def _new_user():
    uid = uuid.uuid4().hex
    storage.create_account(uid, "user_" + uid[:8], "hash")
    return uid


def test_tools_are_stored_and_returned():
    uid = _new_user()
    tid = storage.create_thread(uid, "t")
    storage.add_message(uid, "weather?", "It's sunny.", tid, ["get_weather"])
    history = storage.load_history(uid, tid)
    assert history[-1]["tools"] == ["get_weather"]


def test_no_tools_gives_empty_list():
    uid = _new_user()
    tid = storage.create_thread(uid, "t")
    storage.add_message(uid, "hi", "hello", tid)
    assert storage.load_history(uid, tid)[-1]["tools"] == []


def test_summary_roundtrip():
    uid = _new_user()
    tid = storage.create_thread(uid, "t")
    assert storage.get_summary(uid, tid) == ""
    storage.set_summary(uid, tid, "- likes cats")
    assert storage.get_summary(uid, tid) == "- likes cats"
