#!/usr/bin/env python3
"""Parse second_sight_script.txt into a pipeline-ready plan.json."""
import json
import re

text = open("second_sight_script.txt").read()
lines = text.splitlines()

SCENES = []
cur_scene = None
cur_shot = None


def flush_shot():
    global cur_shot
    if cur_shot and cur_shot.get("action_beat"):
        cur_scene[2].append(cur_shot)
    cur_shot = None


def flush_scene():
    global cur_scene
    flush_shot()
    if cur_scene:
        SCENES.append(cur_scene)
    cur_scene = None


DUR_RE = re.compile(r'Duration:\s*(\d+)\s*sec')
SHOT_RE = re.compile(r'^SHOT\s+(\d+)\s*[—-]?\s*(.*)$')
SCENE_RE = re.compile(r'^SCENE\s+(\d+)\s*[—-]\s*(.+?)\s*\|')
CAM_RE = re.compile(r'(\d+)\s*mm')
DLG_RE = re.compile(r'Dialogue:\s*"([^"]+)"')

SCENE_LOCATIONS = {
    "scene_01": "rooftop of a tall city building overlooking a bridge and river",
    "scene_02": "rooftop of a tall city building / a second sniper's building across the city",
    "scene_03": "rooftop of a tall city building, stairwell access door",
    "scene_04": "adjacent city rooftops with a large gap between them",
    "scene_05": "city rooftops with water tanks and HVAC units",
    "scene_06": "unfinished construction building interior",
    "scene_07": "construction site scaffolding high above the street",
    "scene_08": "construction site scaffolding platform",
    "scene_09": "city rooftops near the bridge",
    "scene_10": "rooftop overlooking the bridge at golden hour",
}

CHAR_BANK = {
    "sniper": {"name": "The Sniper", "locked_look": (
        "male sniper in dark grey tactical clothing, black tactical vest, "
        "black gloves, black backpack, black earpiece, short dark hair, "
        "stubble, athletic build, carrying a scoped bolt-action sniper "
        "rifle with black stock")},
    "second_sniper": {"name": "Second Sniper", "locked_look": (
        "male counter-sniper in black tactical clothing, black balaclava, "
        "black gloves, athletic build, carrying a scoped sniper rifle, "
        "mostly seen as a silhouette")},
    "security": {"name": "Security Operative", "locked_look": (
        "male security agent in a black suit with earpiece, sunglasses, "
        "athletic build, carrying a concealed sidearm")},
    "target": {"name": "The Target", "locked_look": (
        "distinguished middle-aged man in a dark tailored suit, partially "
        "obscured by security, mysterious appearance")},
}

for line in lines:
    line = line.strip()
    if not line:
        continue
    m = SCENE_RE.match(line)
    if m:
        flush_scene()
        cur_scene = (f"scene_{int(m.group(1)):02d}", m.group(2).strip(), [])
        continue
    m = SHOT_RE.match(line)
    if m:
        flush_shot()
        num = int(m.group(1))
        title = m.group(2).strip(" —-")
        if title.isdigit() or title == "":
            title = ""
        cur_shot = {
            "shot_id": f"shot_{num:03d}",
            "shot_title": title,
            "shot_size": "", "camera_angle": "", "camera_movement": "",
            "lens": "", "action_beat": "", "characters": [],
            "dialogue": "", "duration_sec": 3, "slow_motion": False,
        }
        continue
    if cur_shot is None:
        continue
    dm = DUR_RE.search(line)
    if dm:
        cur_shot["duration_sec"] = int(dm.group(1))
    if "SLOW MOTION" in line.upper() and "no slow motion" not in line.lower():
        cur_shot["slow_motion"] = True
    if cur_shot["action_beat"]:
        cur_shot["action_beat"] += " " + line
    else:
        cur_shot["action_beat"] = line

flush_scene()

for sid, title, shots in SCENES:
    for s in shots:
        ab = s["action_beat"]
        low = ab.lower()
        mm = CAM_RE.search(ab)
        if mm:
            s["lens"] = mm.group(1) + "mm"
        if "extreme close-up" in low or "macro" in low:
            s["shot_size"] = "extreme close-up"
        elif "close-up" in low:
            s["shot_size"] = "close-up"
        elif "wide" in low or "pov" in low or "establishing" in low:
            s["shot_size"] = "wide establishing"
        else:
            s["shot_size"] = "medium"
        if "low angle" in low:
            s["camera_angle"] = "low angle"
        elif "pov" in low:
            s["camera_angle"] = "pov"
        elif "high angle" in low:
            s["camera_angle"] = "high angle"
        elif "over" in low and "shoulder" in low:
            s["camera_angle"] = "over-the-shoulder"
        else:
            s["camera_angle"] = "eye level"
        if "handheld" in low:
            s["camera_movement"] = "handheld follow"
        elif "push-in" in low or "dolly" in low:
            s["camera_movement"] = "slow push in"
        elif "tracking" in low or "follows" in low or "follow" in low or "crane" in low or "lateral" in low or "pan" in low:
            s["camera_movement"] = "pan left"
        else:
            s["camera_movement"] = "static"
        chars = []
        if "second sniper" in low:
            chars.append("second_sniper")
        if "sniper" in low:
            chars.append("sniper")
        if "security" in low or "operative" in low or "guard" in low:
            chars.append("security")
        if "target" in low:
            chars.append("target")
        s["characters"] = chars or ["sniper"]
        dm2 = DLG_RE.search(ab)
        if dm2:
            s["dialogue"] = dm2.group(1)
        elif '"Drop it."' in ab:
            s["dialogue"] = "Drop it."
        elif '"YOU PROTECTED THE WRONG MAN."' in ab:
            s["dialogue"] = "YOU PROTECTED THE WRONG MAN."

scenes_out = []
for sid, title, shots in SCENES:
    scenes_out.append({
        "scene_id": sid,
        "location": SCENE_LOCATIONS.get(sid, "city rooftop"),
        "time_of_day": "late afternoon, gradually becoming warmer golden hour",
        "characters": sorted({c for s in shots for c in s["characters"]}),
        "shot_purpose_summary": title,
        "shots": shots,
    })

plan = {
    "title": "SECOND SIGHT",
    "visual_style": (
        "Photorealistic live-action Hollywood thriller, late afternoon to "
        "golden hour, 2.39:1 cinematic frame, grounded physical imperfect "
        "action, 24/35/50/85/135mm lens language"),
    "character_bank": CHAR_BANK,
    "acts": [{"act_id": "act_1", "title": "SECOND SIGHT", "scenes": scenes_out}],
}

json.dump(plan, open("second_sight_plan.json", "w"), indent=2)

n = sum(len(sc["shots"]) for sc in scenes_out)
print("Scenes:", len(scenes_out), "| Shots:", n)
for sc in scenes_out:
    print(f"  {sc['scene_id']} {sc['shot_purpose_summary']}: "
          f"{len(sc['shots'])} shots ({sc['shots'][0]['shot_id']}–{sc['shots'][-1]['shot_id']})")
