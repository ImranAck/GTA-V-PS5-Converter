#!/usr/bin/env python3
"""Detect and apply every bone-free exporter-quirk repair a PC vehicle fixture needs.

Picking --repair flags by hand from the refusing gate costs one failed conversion per quirk, and a
flag for a quirk the mod does not have refuses too (the Skyline's parts have no zero triangle counts).
This tool runs eight repairs that need no bone list, in a fixed order; each detects its own quirk and
is applied only when found, so a clean fixture passes through unchanged:
  1. select-model         repair_pc_select_model.py         (several vehicles in the data files)
  2. texture-stride       repair_pc_texture_stride.py       (strides, mip chains, render-target placeholders)
  3. texture-names        repair_pc_texture_names.py        (spaces/hyphens in texture names, .ytd and .yft)
  4. nonfinite-texcoords  repair_pc_nonfinite_texcoords.py  (NaN texture coordinates; before any mesh reader)
  5. duplicate-bones      repair_pc_duplicate_bones.py      (misc_a twice)
  6. triangle-counts      repair_pc_triangle_counts.py      (TrianglesCount 0 on triangle lists)
  7. pose-precision       repair_pc_pose_precision.py       (--rejected: bone matrices ~1e-5 off the pose)
  8. fragment-quirks      repair_pc_fragment_quirks.py      (empty octant items, sentinel words,
                                                             FragMatrices; last: its walk needs a clean
                                                             skeleton and pose to reach every fragment)
The detecting walks stop at the converter's first refusal, so a quirk behind another one is only seen
once that one is repaired (the gmt400's physics-child triangle counts sat behind its pose rejection):
the sequence is repeated until a whole round applies nothing (at most ROUNDS). A repair "finds
nothing" when its tool ends with its own no-op message (NOTHING below); any other
refusal stops the run with that tool's message (a quirk it cannot repair safely). The tools run exactly
as convert_vehicle.py runs them; before each one a fresh material report of the current fixture is
written with the members of the given report (the converter walks pin it). Bone repairs that need a
judgement are not guessed: seat-mirror (a mirrored seat) and inverse-precision (inverse translations
only) go before auto (--repair seat-mirror=... --repair auto); pose-precision takes the gate's own
rejected bones and still refuses anything above its 1e-4 bound. The bytes the tools change do not
overlap (metas, .ytd, texture names, texcoords, bone names, triangle counts, bone matrices, fragment words), so the
result equals the same repairs given one by one (checked on the GT-R: identical fixture bytes).

  repair_pc_auto.py --fixture build/assets/convert-<id>/fixtures/gtr-import \\
      --material-report <its material report> --output <new fixture>   (convert_vehicle.py --repair auto)

Intermediate fixtures and reports go to <output>-steps/ beside the output (reports: --reports-dir, or
build/auto-reports/ when the work dir resolves outside <repo>/build, see default_reports).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import runpy
import traceback
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from gtavmenu_tools.host_paths import build_dir  # noqa: E402
from gtavmenu_tools.vehicle_repair_inputs import FixtureError, copy_fixture, validate_fixture  # noqa: E402

STEPS = (  # name, tool, walks the converter (takes --templates)
    ("select-model", "repair_pc_select_model.py", False),
    ("texture-stride", "repair_pc_texture_stride.py", False),
    ("texture-names", "repair_pc_texture_names.py", False),
    ("nonfinite-texcoords", "repair_pc_nonfinite_texcoords.py", True),
    ("duplicate-bones", "repair_pc_duplicate_bones.py", False),
    ("pose-precision", "repair_pc_pose_precision.py", False),  # with --rejected
    ("triangle-counts", "repair_pc_triangle_counts.py", True),
    ("fragment-quirks", "repair_pc_fragment_quirks.py", True),
)
ROUNDS = 4  # the walks stop at the first refusal, so a later repair can uncover an earlier quirk
NOTHING = {
    "select-model": "nothing to select",
    "texture-stride": "no texture stride to repair",
    "texture-names": "no texture names to repair",
    "nonfinite-texcoords": "no non-finite texture coordinates found",
    "duplicate-bones": "no duplicate bones to repair",
    "triangle-counts": "no triangle-count rejections found",
    "pose-precision": "no pose rejections to repair",
    "fragment-quirks": "no quirks found",
}


def report_members(report: Path) -> tuple[list[str], str]:
    """(fragment members, texture member) a material report was made for."""
    rows = json.loads(report.read_bytes())["sources"]["resources"]
    fragments = [row["member"] for row in rows if row["kind"] == "fragment"]
    textures = [row["member"] for row in rows if row["kind"] == "textureDictionary"]
    if not fragments or len(textures) != 1:
        raise SystemExit(f"{report}: expected fragment members and one texture dictionary")
    return fragments, textures[0]


def material_report(fixture: Path, fragments: list[str], texture: str, templates: Path | None, output: Path) -> None:
    """Public material observation command for the current fixture."""
    command = [sys.executable, str(TOOLS / "inspect_pc_vehicle_materials.py"), "--pc-fixture", str(fixture)]
    for member in fragments:
        command += ["--resource-member", member]
    command += ["--texture-member", texture, "--templates", str(templates or build_dir(ROOT) / "retail-templates")]
    command += ["--stock-dictionary-name", "vehshare", "--output", str(output)]
    run(command, "material report")


def default_reports(steps_dir: Path) -> Path:
    """Keep fresh material reports beside this invocation's intermediate fixtures."""
    return steps_dir



def run_repair_worker(command: list[str]) -> subprocess.CompletedProcess:
    """Run only known local repair scripts in this private conversion worker.

    No overlap between calls, no execution of mod-provided code. Each script
    retains its full reader, input validation, CLI and output checks. A process
    fallback is available for diagnosing frozen-runtime issues.
    """
    path=Path(command[1]).resolve()
    allowed={tool for _,tool,_ in STEPS}|{"inspect_pc_vehicle_materials.py"}
    if os.environ.get("GTAV_REPAIR_SUBPROCESS")=="1" or path.parent!=TOOLS.resolve() or path.name not in allowed:
        return subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=False)
    stdout,stderr=io.StringIO(),io.StringIO()
    old_argv,old_path,old_cwd=sys.argv[:],sys.path[:],Path.cwd()
    code=0
    try:
        sys.argv=[str(path),*command[2:]]
        sys.path.insert(0,str(TOOLS));os.chdir(ROOT)
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            try: runpy.run_path(str(path),run_name="__main__")
            except SystemExit as exc:
                if exc.code is None:code=0
                elif isinstance(exc.code,int):code=exc.code
                else:code=1;print(exc.code,file=sys.stderr)
            except Exception:
                code=1;traceback.print_exc()
    finally:
        sys.argv=old_argv;sys.path[:]=old_path;os.chdir(old_cwd)
    return subprocess.CompletedProcess(command,code,stdout.getvalue(),stderr.getvalue())

def run(command: list[str], label: str) -> subprocess.CompletedProcess:
    result = run_repair_worker(command)
    if result.returncode:
        sys.stdout.write(result.stdout)
        raise SystemExit(f"auto: {label} failed: {(result.stderr or result.stdout).strip().splitlines()[-1:]}")
    return result


def ps4_name_materials(payload: bytes, header: dict, limits=None) -> dict:
    """Admit name repair only when every explicit drawable inherits the main shader group.

    Legacy FragType/EnvironmentCloth/FragPhysicsLOD/FragPhysTypeChild slots follow
    the pinned CodeWalker structure layouts (the bounded walk is
    gtavmenu_tools.ps4_resource_checks.fragment_drawables). No mesh pointers or
    arbitrary words are scanned. Independent groups need a separate repair.
    """
    from gtavmenu_tools import vehicle_materials
    from gtavmenu_tools.asset_formats import AssetError, Limits
    from gtavmenu_tools.ps4_resource_checks import LegacyWalk, fragment_drawables

    limits = limits or Limits()
    if header["version"] != 162 or header["graphicsBytes"]:
        raise AssetError("PS4 name repair requires system-only Legacy version-162 fragments")
    walk = LegacyWalk(payload, header, limits, "PS4 texture-name")
    drawables = fragment_drawables(walk)
    main_group = walk.u64(walk.at(walk.u64(0x30), 336) + 16)
    for pointer in set(drawables) - {0}:
        group = walk.u64(walk.at(pointer, 336) + 16)
        if group not in (0, main_group):
            raise AssetError(
                "PS4 texture-name repair does not support independent child/cloth shader bindings; "
                "rename their dictionaries and all drawable bindings together before conversion"
            )
    return vehicle_materials.inspect_legacy_yft(payload, header, vehicle_materials.material_contract(), limits)


def ps4_embedded_name_preflight(fixture: Path, manifest: dict) -> None:
    """Refuse invalid embedded names before producing any partially repaired fixture."""
    from gtavmenu_tools.asset_formats import AssetError
    from gtavmenu_tools.texture_names import SOURCE_NAME_POLICY, texture_name_issue
    from gtavmenu_tools.vehicle_repair_inputs import resource_path
    from repair_pc_embedded_textures import EmbeddedError, embedded_textures, has_graphics

    paths = [
        resource_path(fixture, row["member"]) for row in manifest["resources"] if row["member"].lower().endswith(".yft")
    ]
    paths += sorted((fixture / "embedded-textures").rglob("*.yft"))
    for path in paths:
        blob = path.read_bytes()
        if not has_graphics(blob):
            continue
        try:
            textures = embedded_textures(blob)
        except EmbeddedError:
            # The extraction step diagnoses malformed main fragments or omits
            # unsupported optional parts; this preflight only addresses names.
            continue
        for texture in textures:
            if issue := texture_name_issue(texture["name"], SOURCE_NAME_POLICY):
                raise AssetError(
                    f"PS4 embedded texture name {texture['name']!r} in {path.relative_to(fixture)}: {issue}; "
                    "automatic embedded-name repair is unsupported; rename the embedded dictionary "
                    "and all drawable bindings together before conversion"
                )


def ps4_auto(args) -> int:
    """Prepare Legacy source copies without PS5 templates or PS5 geometry repairs."""
    from gtavmenu_tools.asset_formats import AssetError, Limits, decode_resource
    from gtavmenu_tools.asset_textures import inspect_legacy_dictionary
    from gtavmenu_tools.texture_names import SOURCE_NAME_POLICY, texture_name_issue
    from gtavmenu_tools.vehicle_repair_inputs import resource_path

    fixture = args.fixture
    manifest = validate_fixture(fixture)
    try:
        ps4_embedded_name_preflight(fixture, manifest)
    except AssetError as error:
        raise SystemExit(f"auto PS4: {error}") from None
    steps = args.output.with_name(args.output.name + "-steps")
    if steps.exists() or steps.is_symlink():
        raise SystemExit(f"refusing to overwrite {steps}")
    steps.mkdir(parents=True)
    applied = []

    def apply(name: str, tool: str, nothing: str, extra: list[str] = ()) -> None:
        nonlocal fixture
        output = steps / name
        command = [sys.executable, str(TOOLS / tool), "--fixture", str(fixture), "--output", str(output), *extra]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode:
            message = (result.stderr or result.stdout).strip()
            if nothing in message and not output.exists():
                print(f"auto PS4: {name}: nothing found")
                return
            raise SystemExit(f"auto PS4: {name} refused: {message}")
        print(f"auto PS4: {name}: applied")
        applied.append(name)
        fixture = output

    apply("select-model", "repair_pc_select_model.py", "nothing to select")
    apply("embedded-textures", "repair_pc_embedded_textures.py", "no embedded textures", ["--model", manifest["model"]])
    apply("texture-stride", "repair_pc_texture_stride.py", "no texture stride to repair")
    manifest = validate_fixture(fixture)
    needs_names = False
    for row in manifest["resources"]:
        if row["member"].lower().endswith(".ytd"):
            header, payload = decode_resource(resource_path(fixture, row["member"]).read_bytes(), 256 << 20)
            names = inspect_legacy_dictionary(payload, header, Limits())["textures"]
            needs_names |= any(texture_name_issue(r["name"], SOURCE_NAME_POLICY) for r in names)
    if needs_names:
        resources = []
        for row in manifest["resources"]:
            if row["member"].lower().endswith(".yft"):
                blob = resource_path(fixture, row["member"]).read_bytes()
                header, payload = decode_resource(blob, 256 << 20)
                try:
                    materials = ps4_name_materials(payload, header)
                except AssetError as error:
                    raise SystemExit(f"auto PS4: texture-names refused for {row['member']}: {error}") from None
                resources.append(
                    materials | {"member": row["member"], "sourceSha256": hashlib.sha256(blob).hexdigest()}
                )
        report = steps / "source-materials.json"
        report.write_text(
            json.dumps({"kind": "pc-source-material-observation-for-name-repair", "resources": resources}, indent=2)
            + "\n"
        )
        apply(
            "texture-names",
            "repair_pc_texture_names.py",
            "no texture names to repair",
            ["--material-report", str(report)],
        )
    manifest = copy_fixture(fixture, args.output)
    manifest["autoRepairs"] = {"tool": "tools/repair_pc_auto.py", "target": args.target, "applied": applied}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "applied": applied}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--material-report", type=Path)
    parser.add_argument("--target", choices=("ppsa04264-01.010.002", "cusa00411-01.57"), default="ppsa04264-01.010.002")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--templates", type=Path, help="retail templates root (passed to the converter walks)")
    parser.add_argument("--reports-dir", type=Path, help="material reports (default: <output>-steps)")
    parser.add_argument("--tuning-parts", action="store_true")
    parser.add_argument("--first-pass", action="store_true",
                        help="run each repair once; the caller must validate with the strict converter")
    parser.add_argument("--skip", action="append", default=[], choices=[name for name, *_ in STEPS])
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"refusing to overwrite {args.output}")
    if args.target == "cusa00411-01.57":
        if args.skip or args.first_pass:
            parser.error("--skip and --first-pass are not supported by PS4 source preparation")
        return ps4_auto(args)
    if args.material_report is None:
        parser.error("PS5 automatic repairs require --material-report")
    from gtavmenu_tools.asset_formats import configure_decode_cache
    configure_decode_cache(192 << 20 if os.environ.get("GTAV_DISABLE_REPAIR_CACHE") != "1" else 0)
    manifest = validate_fixture(args.fixture)
    prior = manifest.get("autoRepairs", {}) if isinstance(manifest, dict) else {}
    prior_applied = prior.get("applied", []) if isinstance(prior, dict) else []
    prior_applied = prior_applied if isinstance(prior_applied, list) and all(isinstance(v, str) for v in prior_applied) else []
    prior_rounds = prior.get("rounds", 0) if isinstance(prior, dict) else 0
    prior_rounds = prior_rounds if type(prior_rounds) is int and prior_rounds >= 0 else 0
    steps_dir = args.output.parent / (args.output.name + "-steps")
    if steps_dir.exists() or steps_dir.is_symlink():
        raise SystemExit(f"refusing to overwrite {steps_dir}")
    reports = args.reports_dir or default_reports(steps_dir)
    fragments, texture = report_members(args.material_report)
    fixture, report, applied = args.fixture, args.material_report, []
    reported = fixture  # the fixture the current material report was made for
    for round_ in range(1, ROUNDS + 1):
        before = len(applied)
        for index, (name, tool, walks) in enumerate(STEPS):
            if not fragments:
                break
            if name in args.skip:
                continue
            tag = f"{round_}-{index}-{name}"
            if fixture != reported:
                reported, report = fixture, reports / f"{tag}-materials.json"
                report.parent.mkdir(parents=True, exist_ok=True)
                material_report(fixture, fragments, texture, args.templates, report)
            output = steps_dir / tag
            output.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(TOOLS / tool), "--fixture", str(fixture), "--material-report", str(report)]
            command += ["--output", str(output)]
            if walks and args.templates is not None:
                command += ["--templates", str(args.templates)]
            if name == "pose-precision":
                command.append("--rejected")
            if args.tuning_parts and name in ("duplicate-bones", "pose-precision"):
                command.append("--tuning-parts")
            started = time.perf_counter()
            result = run_repair_worker(command)
            print(f"PERF_REPAIR round={round_} seconds={time.perf_counter()-started:.3f} label={name}", flush=True)
            if result.returncode:
                message = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
                if NOTHING[name] in message[0]:
                    print(f"auto: round {round_} {name}: nothing found")
                    continue
                sys.stdout.write(result.stdout)
                raise SystemExit(f"auto: {name} refused: {message[0]}")
            print(f"auto: round {round_} {name}: applied ({result.stdout.strip().splitlines()[-1][:200]})")
            applied.append({"repair": name, "round": round_, "fixture": str(output)})
            fixture = output
            if args.tuning_parts and name in ("pose-precision", "duplicate-bones"):
                for line in result.stdout.splitlines():
                    if line.startswith(("WARNING_TUNING_EXCLUDED:", "TUNING_ROOT_REPAIR:")):
                        print(line, flush=True)
                manifest_now = validate_fixture(fixture)
                excluded = {r["member"] for key in ("excludedTuningPose", "excludedTuningSkeleton") for r in manifest_now.get(key, [])}
                fragments = [m for m in fragments if m not in excluded]
        if not fragments or args.first_pass or len(applied) == before:
            break
    else:
        raise SystemExit(f"auto: still repairing after {ROUNDS} rounds; stop and read the steps in {steps_dir}")
    copy_fixture(fixture, args.output)
    manifest_path = args.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["autoRepairs"] = {
        "tool": "tools/repair_pc_auto.py",
        "applied": [*prior_applied, *(row["repair"] for row in applied)],
        "rounds": prior_rounds + round_,
        "checked": [name for name, *_ in STEPS if name not in args.skip],
    }
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "applied": manifest["autoRepairs"]["applied"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FixtureError as error:
        raise SystemExit(f"fixture refused: {error}") from None
