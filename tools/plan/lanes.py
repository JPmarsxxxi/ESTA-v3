"""What a shot is made of, and the production lane that can make it (SPEC.md Part 12, goal B).

The plan copies each ref's `material` into `visual.material` and routes the shot to a `visual.lane` by it, not by
the ref's kind: every non-photo ref used to become MOTION_GRAPHICS, and HyperFrames can only draw flat vector and
type. The validator rejects a lane that can't make the ref's material unless the shot carries `lane_fallback`.
"""

MATERIALS = ("flat_vector", "kinetic_type", "data_ui", "photo_collage", "illustration", "render_3d",
             "cel_animation", "live_action", "screen_capture")
FINISHES = ("grain", "halftone", "paper_texture", "blur", "chromatic_aberration", "glow", "gradient", "hard_shadow")
SUBJECT_MOTION = ("none", "low", "high")
LANES = ("hyperframes", "collage", "genimage", "footage", "image", "ai_video")

# The materials each lane can produce. ai_video renders whatever its preset and prompt ask for, except flat
# designed graphics, which come out mushy.
CAN_MAKE = {
    "hyperframes": {"flat_vector", "kinetic_type", "data_ui"},
    "collage": {"photo_collage"},
    "genimage": {"illustration", "render_3d"},
    "footage": {"live_action", "screen_capture", "cel_animation"},
    "image": {"live_action", "screen_capture"},
    "ai_video": {"illustration", "render_3d", "cel_animation", "live_action"},
}
# The plan types each lane is delivered as: genimage is a generated still animated in HyperFrames, or by i2v.
LANE_TYPES = {"hyperframes": {"MOTION_GRAPHICS"}, "collage": {"MOTION_GRAPHICS"}, "genimage": {"MOTION_GRAPHICS", "AI_VIDEO"},
              "footage": {"REAL_FOOTAGE"}, "image": {"REAL_IMAGE"}, "ai_video": {"AI_VIDEO"}}
TYPE_LANE = {"MOTION_GRAPHICS": "hyperframes", "REAL_FOOTAGE": "footage", "REAL_IMAGE": "image", "AI_VIDEO": "ai_video"}
# A ref described before materials existed: its kind is the only evidence.
KIND_MATERIAL = {"footage": "live_action", "still": "live_action", "graphic": "flat_vector", "meme": "live_action",
                 "talking_head": "live_action", "screen": "screen_capture", "ai": "live_action"}


def ref_material(ref: dict) -> str:
    m = ref.get("material")
    return m if m in MATERIALS else KIND_MATERIAL.get(ref.get("kind", ""), "live_action")


def looks_generated(ref: dict) -> bool:
    return bool(ref.get("ai_look")) or (ref.get("likely_sources") or [""])[0] == "ai_video"


def route(ref: dict, licensing: str = "fair_use_ok") -> dict:
    """{type, lane, material, subject_motion} for a shot copying `ref`."""
    material = ref_material(ref)
    motion = ref.get("subject_motion") if ref.get("subject_motion") in SUBJECT_MOTION else "none"
    out = {"material": material, "subject_motion": motion}
    if looks_generated(ref) and material not in CAN_MAKE["hyperframes"]:
        return out | {"lane": "ai_video", "type": "AI_VIDEO"}
    if material in CAN_MAKE["hyperframes"]:
        return out | {"lane": "hyperframes", "type": "MOTION_GRAPHICS"}
    if material == "photo_collage":
        return out | {"lane": "collage", "type": "MOTION_GRAPHICS"}
    if material in CAN_MAKE["genimage"]:
        # A generated keyframe, animated by i2v only where the ref really moves (decision 4).
        return out | {"lane": "genimage", "type": "AI_VIDEO" if motion == "high" else "MOTION_GRAPHICS"}
    if material == "cel_animation":
        found = licensing == "fair_use_ok"
        return out | {"lane": "footage" if found else "ai_video", "type": "REAL_FOOTAGE" if found else "AI_VIDEO"}
    still = ref.get("kind") == "still" and motion != "high"
    return out | {"lane": "image" if still else "footage", "type": "REAL_IMAGE" if still else "REAL_FOOTAGE"}


def lane_problem(visual: dict) -> str:
    """Why this shot's lane can't make its material ("" when it can, or when either is unknown)."""
    lane, material = visual.get("lane"), visual.get("material")
    if not lane or not material or lane not in CAN_MAKE or material in CAN_MAKE[lane]:
        return ""
    return f"lane {lane} can't make {material}"
