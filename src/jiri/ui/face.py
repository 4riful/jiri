from __future__ import annotations

from dataclasses import dataclass

FACE_STATES = {
    "idle",
    "happy",
    "alert",
    "annoyed",
    "angry",
    "rage",
    "sleeping",
    "blink",
    "curious",
    "smirk",
    "focused",
    "weather_hot",
    "weather_rain",
    "ai_offline",
    "system_warning",
}
CRITICAL_FACE_STATES = {"angry", "rage"}


@dataclass(frozen=True)
class FaceFrame:
    state: str
    eye_left: str
    eye_right: str
    mouth: str
    label: str


FACE_FRAMES = {
    "idle": FaceFrame("idle", "o", "o", "___", "Idle"),
    "happy": FaceFrame("happy", "^", "^", "___/", "Happy"),
    "alert": FaceFrame("alert", "O", "O", "---", "Alert"),
    "annoyed": FaceFrame("annoyed", "-", "-", "___", "Annoyed"),
    "angry": FaceFrame("angry", ">", "<", "---", "Angry"),
    "rage": FaceFrame("rage", "!", "!", "###", "Rage"),
    "sleeping": FaceFrame("sleeping", "z", "z", "___", "Sleeping"),
    "blink": FaceFrame("blink", "-", "-", "___", "Blink"),
    "curious": FaceFrame("curious", "o", "O", "___", "Curious"),
    "smirk": FaceFrame("smirk", "^", "o", "__/", "Smirk"),
    "focused": FaceFrame("focused", "o", "o", "---", "Focused"),
    "weather_hot": FaceFrame("weather_hot", "~", "~", "---", "Hot"),
    "weather_rain": FaceFrame("weather_rain", "o", "o", "~~~", "Rain"),
    "ai_offline": FaceFrame("ai_offline", "x", "x", "___", "AI offline"),
    "system_warning": FaceFrame("system_warning", "!", "!", "---", "System warning"),
}


def validate_face_state(state: str) -> str:
    if state not in FACE_STATES:
        raise ValueError(f"Unknown face state: {state}")
    return state


def face_frame_for_state(state: str, focus_snapshot: dict[str, object] | None = None) -> FaceFrame:
    validated = validate_face_state(state)
    if focus_snapshot and focus_snapshot.get("active"):
        remaining = str(focus_snapshot.get("remaining_text") or "00:00")
        left, right = focus_eyes(remaining)
        base = FACE_FRAMES.get(validated, FACE_FRAMES["idle"])
        return FaceFrame(validated, left, right, base.mouth, base.label)
    return FACE_FRAMES.get(validated, FACE_FRAMES["idle"])


def focus_eyes(remaining_text: str) -> tuple[str, str]:
    clean = remaining_text.replace(":", "")
    if len(clean) >= 4:
        return clean[:2], clean[2:4]
    if len(clean) >= 2:
        return clean[:1], clean[1:2]
    return "0", "0"


def is_critical_face_state(state: str) -> bool:
    return state in CRITICAL_FACE_STATES
