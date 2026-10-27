"""Render the app's original 3D artwork with Blender (bpy).

    pip install bpy          # Blender as a Python module (Python 3.11+)
    python packaging/blender/render_assets.py

Outputs into assets/: logo.png (transparent fish emblem), app_icon.png (icon tile)
and hero.png (dashboard banner). Everything is procedural - no external assets.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

OUT = Path(__file__).resolve().parents[2] / "assets"
OUT.mkdir(exist_ok=True)


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 64
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"


def mat(name, color, metallic=0.0, rough=0.3, emission=None, strength=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    if coat:
        b.inputs["Coat Weight"].default_value = coat
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def gradient_mat(name, c1, c2, axis="X", lo=-1.2, hi=1.2, metallic=0.35, rough=0.25):
    """Glossy material blending two colours along an axis (object space)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = lo
    mr.inputs["From Max"].default_value = hi
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*c1, 1)
    ramp.color_ramp.elements[1].color = (*c2, 1)
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    nt.links.new(sep.outputs[axis], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = 0.6
    return m


def smooth(obj, levels=2):
    mod = obj.modifiers.new("sub", "SUBSURF")
    mod.levels = levels
    mod.render_levels = levels
    bpy.ops.object.shade_smooth()


def build_fish(location=(0, 0, 0), scale=1.0, rot_z=0.0):
    """A stylised fish: ellipsoid body, forked tail, fins, eye. Returns the parent empty."""
    parent = bpy.data.objects.new("Fish", None)
    bpy.context.collection.objects.link(parent)
    body_mat = gradient_mat("FishBody", (0.42, 0.04, 1.0), (0.0, 0.70, 0.90), lo=-0.9, hi=0.9)
    fin_mat = mat("Fin", (0.05, 0.70, 0.90), metallic=0.1, rough=0.25, emission=(0.05, 0.70, 0.90), strength=0.25)
    eye_white = mat("EyeW", (0.95, 0.95, 1.0), rough=0.15)
    eye_black = mat("EyeB", (0.02, 0.02, 0.04), rough=0.05, coat=1.0)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    body = bpy.context.object
    body.scale = (1.75, 0.62, 0.92)
    body.data.materials.append(body_mat)
    taper = body.modifiers.new("taper", "SIMPLE_DEFORM")
    taper.deform_method = "TAPER"
    taper.deform_axis = "X"
    taper.factor = 0.32
    smooth(body, 1)

    # forked tail from a flattened, bent cone pair
    for sign in (1, -1):
        bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.62, depth=1.25)
        t = bpy.context.object
        t.scale = (1.0, 0.22, 1.0)
        t.rotation_euler = (0, math.radians(-90 + 38 * sign), 0)
        t.location = (-1.95, 0, 0.36 * sign)
        t.data.materials.append(fin_mat)
        smooth(t, 1)
        t.parent = parent
    # dorsal fin
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.5, depth=0.8)
    d = bpy.context.object
    d.scale = (1.1, 0.12, 1.0)
    d.rotation_euler = (0, math.radians(-18), 0)
    d.location = (-0.1, 0, 1.05)
    d.data.materials.append(fin_mat)
    smooth(d, 1)
    d.parent = parent
    # pectoral fin
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.35)
    pf = bpy.context.object
    pf.scale = (1.2, 0.15, 0.55)
    pf.rotation_euler = (math.radians(15), math.radians(25), 0)
    pf.location = (0.2, -0.58, -0.35)
    pf.data.materials.append(fin_mat)
    smooth(pf, 1)
    pf.parent = parent
    # eye
    for obj_r, m, loc in ((0.22, eye_white, (1.05, -0.47, 0.22)), (0.12, eye_black, (1.10, -0.64, 0.24))):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=obj_r, segments=32, ring_count=16)
        e = bpy.context.object
        e.location = loc
        e.data.materials.append(m)
        bpy.ops.object.shade_smooth()
        e.parent = parent
    body.parent = parent
    parent.location = location
    parent.scale = (scale, scale, scale)
    parent.rotation_euler = (0, 0, rot_z)
    return parent


def build_emblem(with_tile: bool) -> None:
    """Bobber + gold hook inside a neon ring - the app emblem."""
    red = mat("BobberRed", (0.85, 0.06, 0.10), rough=0.18, coat=1.0)
    white = mat("BobberWhite", (0.92, 0.92, 0.95), rough=0.2, coat=1.0)
    gold = mat("Gold", (1.0, 0.66, 0.18), metallic=0.85, rough=0.28, emission=(1.0, 0.55, 0.12), strength=0.35)
    tip = mat("Tip", (1.0, 0.85, 0.3), emission=(1.0, 0.8, 0.25), strength=6.0)
    ring = gradient_mat("Ring", (0.42, 0.06, 1.0), (0.0, 0.75, 1.0), axis="X", lo=-2.2, hi=2.2, metallic=0.2)
    ring_glow = ring.node_tree.nodes["Principled BSDF"]
    ring_glow.inputs["Emission Strength"].default_value = 0.9
    ramp = next(n for n in ring.node_tree.nodes if n.type == "VALTORGB")
    ring.node_tree.links.new(ramp.outputs["Color"], ring_glow.inputs["Emission Color"])
    ripple = mat("Ripple", (0.1, 0.8, 1.0), emission=(0.1, 0.8, 1.0), strength=3.0)

    # bobber: two hemispheres
    for z_sign, m in ((1, red), (-1, white)):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=0.9, location=(0, 0, 0.35))
        b = bpy.context.object
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for v in b.data.vertices:
            v.select = (v.co.z * z_sign) < -0.02
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        b.data.materials.append(m)
        bpy.ops.object.shade_smooth()
    # white band
    bpy.ops.mesh.primitive_torus_add(major_radius=0.9, minor_radius=0.07, location=(0, 0, 0.35))
    bpy.context.object.data.materials.append(white)
    bpy.ops.object.shade_smooth()
    # antenna + glowing tip
    bpy.ops.mesh.primitive_cylinder_add(radius=0.07, depth=0.9, location=(0, 0, 1.6))
    bpy.context.object.data.materials.append(red)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 0, 2.1))
    bpy.context.object.data.materials.append(tip)
    bpy.ops.object.shade_smooth()
    # gold hook: a J curve with a bevel, hanging under the bobber
    curve = bpy.data.curves.new("Hook", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.075
    curve.bevel_resolution = 6
    sp = curve.splines.new("BEZIER")
    pts = [(0, 0, -0.55), (0, 0, -1.6), (-0.15, 0, -2.25), (-0.65, 0, -2.2), (-0.8, 0, -1.75)]
    sp.bezier_points.add(len(pts) - 1)
    for bp, co in zip(sp.bezier_points, pts):
        bp.co = co
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    hook = bpy.data.objects.new("Hook", curve)
    bpy.context.collection.objects.link(hook)
    hook.data.materials.append(gold)
    bpy.ops.mesh.primitive_cone_add(radius1=0.16, depth=0.35, location=(-0.82, 0, -1.6), rotation=(0, math.radians(-15), 0))
    bpy.context.object.data.materials.append(gold)
    # neon ring + water ripple
    bpy.ops.mesh.primitive_torus_add(major_radius=2.25, minor_radius=0.15, rotation=(math.radians(90), 0, 0),
                                     location=(0, 0.3, 0.0))
    bpy.context.object.data.materials.append(ring)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_torus_add(major_radius=1.35, minor_radius=0.035, location=(0, 0, -0.45))
    bpy.context.object.scale = (1, 0.45, 1)
    bpy.context.object.data.materials.append(ripple)
    if with_tile:
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 1.3, 0))
        tile = bpy.context.object
        tile.scale = (3.05, 0.2, 3.05)
        bev = tile.modifiers.new("bev", "BEVEL")
        bev.width = 0.7
        bev.segments = 14
        tile.data.materials.append(gradient_mat("Tile", (0.05, 0.05, 0.09), (0.16, 0.09, 0.34), axis="Z", lo=-2.7,
                                                hi=2.7, metallic=0.0, rough=0.45))


def emblem(with_tile: bool) -> None:
    reset()
    world((0.01, 0.01, 0.02), 0.25)
    build_emblem(with_tile)
    area_light((3, -5, 4), 420, (1.0, 0.96, 0.95), 3, target=(0, 0, 0))
    area_light((-4, -3, 1), 260, (0.35, 0.8, 1.0), 2, target=(0, 0, 0))
    area_light((0, 3, 5), 300, (0.7, 0.4, 1.0), 2, target=(0, 0, 0))
    camera((0, -13.6 if with_tile else -11.5, 0.6), (0, 0, -0.05), lens=60)
    render(OUT / ("app_icon.png" if with_tile else "logo.png"), 512, 512, transparent=True)


def camera(loc, target, lens=50, ortho=None):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = lens
    if ortho:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = loc
    direction = Vector(target) - Vector(loc)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def area_light(loc, energy, color=(1, 1, 1), size=4.0, target=(0, 0, 0)):
    data = bpy.data.lights.new("L", "AREA")
    data.energy = energy
    data.color = color
    data.size = size
    obj = bpy.data.objects.new("L", data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return obj


def world(color, strength):
    w = bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*color, 1)
    bg.inputs["Strength"].default_value = strength


def render(path: Path, w: int, h: int, transparent: bool) -> None:
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.film_transparent = transparent
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print("rendered", path)


def three_point(scale=1.0):
    area_light((3 * scale, -4 * scale, 4 * scale), 380 * scale ** 2, (1.0, 0.95, 1.0), 3)
    area_light((-4 * scale, -2 * scale, 1 * scale), 260 * scale ** 2, (0.3, 0.85, 1.0), 2)
    area_light((-1 * scale, 4 * scale, 3 * scale), 420 * scale ** 2, (0.6, 0.35, 1.0), 2)


def logo() -> None:
    reset()
    world((0.02, 0.02, 0.03), 0.4)
    build_fish(rot_z=math.radians(-8))
    three_point()
    camera((0.6, -7.2, 1.2), (-0.25, 0, 0.05), lens=58)
    render(OUT / "logo.png", 512, 512, transparent=True)


def icon_tile() -> None:
    reset()
    world((0.02, 0.02, 0.03), 0.3)
    bpy.ops.mesh.primitive_cube_add(size=2)
    tile = bpy.context.object
    tile.scale = (2.25, 0.2, 2.25)
    tile.location = (-0.25, 1.2, 0.05)
    bev = tile.modifiers.new("bev", "BEVEL")
    bev.width = 0.55
    bev.segments = 12
    tile.data.materials.append(gradient_mat("Tile", (0.07, 0.07, 0.10), (0.20, 0.12, 0.42), axis="Z", lo=-2.3, hi=2.3,
                                            metallic=0.0, rough=0.5))
    build_fish(scale=0.92, rot_z=math.radians(-8))
    three_point()
    camera((0.0, -9.5, 0.6), (-0.25, 0, 0.05), lens=58)
    render(OUT / "app_icon.png", 512, 512, transparent=True)


def hero() -> None:
    reset()
    bpy.context.scene.cycles.samples = 48
    world((0.01, 0.03, 0.06), 0.6)
    # water volume for light shafts
    bpy.ops.mesh.primitive_cube_add(size=30, location=(0, 0, 0))
    vol = bpy.context.object
    vm = bpy.data.materials.new("Water")
    vm.use_nodes = True
    nt = vm.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    pv.inputs["Color"].default_value = (0.25, 0.55, 0.9, 1)
    pv.inputs["Density"].default_value = 0.035
    nt.links.new(pv.outputs[0], nt.nodes["Material Output"].inputs["Volume"])
    vol.data.materials.append(vm)
    # sea floor
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, -3.2))
    floor = bpy.context.object
    floor.data.materials.append(mat("Floor", (0.05, 0.06, 0.12), rough=0.9))
    # fish school
    build_fish((2.6, 0, 0.2), 1.0, math.radians(-12))
    build_fish((-1.5, 3.5, 1.3), 0.55, math.radians(-4))
    build_fish((-4.8, 6.0, -0.6), 0.45, math.radians(-20))
    build_fish((6.5, 7.0, 1.8), 0.4, math.radians(8))
    # bubbles
    bub = mat("Bubble", (0.8, 0.95, 1.0), rough=0.0, emission=(0.4, 0.8, 1.0), strength=1.5)
    import random
    rnd = random.Random(4)
    for _ in range(26):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=rnd.uniform(0.04, 0.13),
                                             location=(rnd.uniform(-7, 9), rnd.uniform(-2, 6), rnd.uniform(-1.5, 3.5)))
        bpy.context.object.data.materials.append(bub)
        bpy.ops.object.shade_smooth()
    # sun shafts from above + coloured rim lights
    sun = bpy.data.lights.new("Sun", "SPOT")
    sun.energy = 9000
    sun.spot_size = math.radians(55)
    sun.color = (0.75, 0.9, 1.0)
    so = bpy.data.objects.new("Sun", sun)
    bpy.context.collection.objects.link(so)
    so.location = (1, 1, 12)
    area_light((-5, -3, 1), 900, (0.55, 0.3, 1.0), 4, target=(2, 0, 0))
    area_light((8, -4, 2), 700, (0.15, 0.85, 1.0), 4, target=(2, 0, 0))
    camera((0.5, -9.5, 0.7), (1.2, 2, 0.6), lens=32)
    render(OUT / "hero.png", 1600, 420, transparent=False)


if __name__ == "__main__":
    which = sys.argv[1:] or ["logo", "icon", "hero"]
    if "logo" in which:
        emblem(with_tile=False)
    if "icon" in which:
        emblem(with_tile=True)
    if "fish" in which:  # the original fish artwork
        logo()
        icon_tile()
    if "hero" in which:
        hero()
