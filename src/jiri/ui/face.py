from __future__ import annotations


FACE_STATES = {"idle", "happy", "alert", "annoyed", "angry", "rage", "sleeping"}


def validate_face_state(state: str) -> str:
    if state not in FACE_STATES:
        raise ValueError(f"Unknown face state: {state}")
    return state
