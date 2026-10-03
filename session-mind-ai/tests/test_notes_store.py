from session_mind_ai.notes_store import InMemoryNotesStore, Note


def test_add_and_retrieve_notes_for_sessions():
    store = InMemoryNotesStore()
    store.add_note(Note(session_id="s1", text="note a", author="me"))
    store.add_note(Note(session_id="s2", text="note b", author="me"))
    store.add_note(Note(session_id="s1", text="note c", author="me"))

    notes = store.notes_for_sessions(["s1"])
    assert {n.text for n in notes} == {"note a", "note c"}


def test_all_notes_returns_everything():
    store = InMemoryNotesStore()
    store.add_note(Note(session_id="s1", text="note a", author="me"))
    store.add_note(Note(session_id="s2", text="note b", author="me"))
    assert len(store.all_notes()) == 2


def test_notes_for_unknown_session_returns_empty():
    store = InMemoryNotesStore()
    store.add_note(Note(session_id="s1", text="note a", author="me"))
    assert store.notes_for_sessions(["does-not-exist"]) == []


def test_note_recording_url_defaults_to_none():
    note = Note(session_id="s1", text="note a", author="me")
    assert note.recording_url is None


def test_note_recording_url_is_stored_and_retrievable():
    store = InMemoryNotesStore()
    store.add_note(Note(session_id="s1", text="note a", author="me", recording_url="https://example.com/video"))
    notes = store.notes_for_sessions(["s1"])
    assert notes[0].recording_url == "https://example.com/video"
