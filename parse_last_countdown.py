#!/usr/bin/env python3
"""Parse last_countdown_script.txt into last_countdown_plan.json (pipeline-ready).

This script has full "Prompt:" blocks per shot, so the parser extracts them
directly — no AI planning needed.
"""
import json
import re

text = open("last_countdown_script.txt").read()
lines = text.splitlines()

shots = []
cur_shot = None
in_prompt = False

DUR_RE = re.compile(r'Duration:\s*(\d+)\s*sec')
SHOT_RE = re.compile(r'^SHOT\s+(\d+)([A-D]?)\s*[—-]\s*(.+)$')


def flush_shot():
    global cur_shot
    if cur_shot and cur_shot.get("prompt"):
        shots.append(cur_shot)
    cur_shot = None


for line in lines:
    line = line.strip()
    if not line:
        continue
    m = SHOT_RE.match(line)
    if m:
        flush_shot()
        num = int(m.group(1))
        sub = m.group(2) or ""
        title = m.group(3).strip(" —-")
        cur_shot = {
            "shot_id": f"shot_{num:03d}{''.join(sub.lower().split())}",
            "shot_title": title,
            "shot_size": "", "camera_angle": "", "camera_movement": "",
            "lens": "", "prompt": "", "action_beat": "", "characters": [],
            "dialogue": "", "duration_sec": 3, "slow_motion": False,
        }
        in_prompt = False
        continue
    if cur_shot is None:
        continue
    dm = DUR_RE.search(line)
    if dm:
        cur_shot["duration_sec"] = int(dm.group(1))
    if line.startswith("Prompt:"):
        cur_shot["prompt"] = line[len("Prompt:"):].strip()
        in_prompt = True
        continue
    if line.startswith("Dialogue:"):
        cur_shot["dialogue"] = line[len("Dialogue:"):].strip().strip('"')
        continue
    if in_prompt:
        cur_shot["prompt"] += " " + line
    else:
        cur_shot["action_beat"] += " " + line

flush_shot()

# camera specs from action_beat + prompt
CAM_RE = re.compile(r'(\d+)\s*mm')
for s in shots:
    ab = (s["action_beat"] + " " + s["prompt"]).lower()
    mm = CAM_RE.search(ab)
    if mm:
        s["lens"] = mm.group(1) + "mm"
    if "scope" in ab and "pov" in ab or "scope hook" in s["shot_title"].lower():
        s["shot_size"] = "wide establishing"
        s["camera_angle"] = "pov"
    elif "extreme close-up" in ab or "macro" in ab or "her eye" in ab:
        s["shot_size"] = "extreme close-up"
    elif "close-up" in ab:
        s["shot_size"] = "close-up"
    elif "wide" in ab or "aerial" in ab:
        s["shot_size"] = "wide establishing"
    else:
        s["shot_size"] = "medium"
    if "low-angle" in ab or "low camera" in ab:
        s["camera_angle"] = "low angle"
    elif "pov" in ab:
        s["camera_angle"] = "pov"
    else:
        s["camera_angle"] = "eye level"
    if "handheld" in ab:
        s["camera_movement"] = "handheld"
    elif "tracking" in ab or "tracks" in ab:
        s["camera_movement"] = "tracking follow"
    elif "dolly" in ab or "lateral" in ab or "panning" in ab or "pan " in ab:
        s["camera_movement"] = "pan left"
    else:
        s["camera_movement"] = "static"
    if "120fps" in ab or "slow motion" in ab:
        s["slow_motion"] = True
    chars = []
    if "female sniper" in ab or "sniper" in ab:
        chars.append("sniper")
    if "pilot" in ab:
        chars.append("pilot")
    if "guard" in ab or "pursuer" in ab or "attacker" in ab:
        chars.append("guard")
    s["characters"] = chars or ["sniper"]

# scene structure: single scene for the 60s sequence, but break into
# logical beats for the pipeline
SCENE_MAP = [
    ("scene_01", "SCOPE HOOK & SNIPER REVEAL", "dim industrial room seen through sniper scope / urban rooftop at dusk", ["shot_001", "shot_002", "shot_003", "shot_004", "shot_005", "shot_006"]),
    ("scene_02", "THE SECOND THREAT", "dim industrial room, opposite side", ["shot_007"]),
    ("scene_03", "AERIAL ESCALATION", "city skyline, late afternoon", ["shot_008", "shot_009", "shot_010", "shot_011a", "shot_011b", "shot_011c", "shot_011d", "shot_012"]),
    ("scene_04", "SNIPER COUNTERATTACK", "urban rooftop at dusk / industrial room scope view", ["shot_013", "shot_014"]),
    ("scene_05", "GROUND ACTION", "rooftop access stairwell, dim concrete", ["shot_015", "shot_016", "shot_017", "shot_018"]),
    ("scene_05", "GROUND ACTION", "rooftop access stairwell, dim concrete", ["shot_019", "shot_020"]),
]

scenes_out = []
for sid, title, location, shot_ids in SCENE_MAP:
    s_shots = [s for s in shots if s["shot_id"] in shot_ids]
    if not s_shots:
        continue
    scenes_out.append({
        "scene_id": sid,
        "location": location,
        "time_of_day": "dusk, natural sunset light transitioning to dark interior",
        "characters": sorted({c for s in s_shots for c in s["characters"]}),
        "shot_purpose_summary": title,
        "shots": s_shots,
    })

CHAR_BANK = {
    "sniper": {"name": "Female Sniper", "locked_look": (
        "identical woman throughout, 30 to 35 years old, athletic build, "
        "realistic human proportions, olive tactical jacket, black tactical "
        "pants, dark gloves, dark brown hair tied in a practical low "
        "ponytail, subtle natural makeup, small scar near left eyebrow")},
    "pilot": {"name": "Helicopter Pilot", "locked_look": (
        "male pilot, flight helmet with visor raised, realistic flight suit, "
        "athletic build, reaction visible through cockpit")},
    "guard": {"name": "Armed Guard", "locked_look": (
        "adult male armed guards, realistic tactical clothing, realistic "
        "firearms, athletic build, unaware industrial workers turned "
        "attackers")},
}

plan = {
    "title": "LAST COUNTDOWN",
    "visual_style": (
        "Photorealistic live-action Hollywood action thriller, dusk to dark "
        "interior, 16:9, physically believable, natural film grain, no AI look"),
    "character_bank": CHAR_BANK,
    "acts": [{"act_id": "act_1", "title": "LAST COUNTDOWN", "scenes": scenes_out}],
}

json.dump(plan, open("last_countdown_plan.json", "w"), indent=2)

n = sum(len(sc["shots"]) for sc in scenes_out)
print("Scenes:", len(scenes_out), "| Shots:", n)
for sc in scenes_out:
    print(f"  {sc['scene_id']} {sc['shot_purpose_summary']}: {len(sc['shots'])} shots ({sc['shots'][0]['shot_id']}–{sc['shots'][-1]['shot_id']})")
