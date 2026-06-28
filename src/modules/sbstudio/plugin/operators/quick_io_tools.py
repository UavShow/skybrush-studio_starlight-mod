# -*- coding: utf-8 -*-
"""Quick import/export of action keyframes (快速互导).

Merged from the standalone "Quick import and export of action keyframes"
plugin. Exposes operators and scene-property (un)registration helpers; the UI
is drawn by the DroneMax animation assistance panel.
"""

import bpy
import os
import json
import bmesh
from bpy.types import Operator
from bpy.props import (
    PointerProperty,
    BoolProperty,
    StringProperty,
    IntProperty,
    FloatProperty,
    EnumProperty,
)
from mathutils import Matrix

__all__ = (
    "QuickIOExportKeyframesOperator",
    "QuickIOPreviewOperator",
    "QuickIOImportKeyframesOperator",
    "QuickIOCreateAndBakeProxiesOperator",
    "QuickIOBatchRenameOperator",
    "register_quick_io_scene_properties",
    "unregister_quick_io_scene_properties",
)

EXT = ".brta"


# ---------- 通用工具 ----------

def ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def decompose_world_trs(obj):
    mw: Matrix = obj.matrix_world
    loc, rot, scale = mw.decompose()
    e = rot.to_euler("XYZ")
    return [loc.x, loc.y, loc.z], [e.x, e.y, e.z], [scale.x, scale.y, scale.z]


def ensure_collection(name: str) -> bpy.types.Collection:
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def _numeric_suffix(name: str):
    import re

    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def get_action_fcurves(act, anim_data=None):
    """兼容 Blender 2.x–5.x 获取 Action 的 fcurves。"""
    try:
        return list(act.fcurves)
    except AttributeError:
        pass

    result = []
    layers = getattr(act, "layers", None)
    if not layers:
        return result

    for layer in layers:
        strips = getattr(layer, "strips", None) or []
        for strip in strips:
            slot = getattr(anim_data, "action_slot", None) if anim_data is not None else None
            if slot is not None:
                try:
                    cb = strip.channelbag(slot)
                    if cb is not None:
                        result.extend(cb.fcurves)
                    continue
                except Exception:
                    pass

            channelbags = getattr(strip, "channelbags", None)
            if channelbags:
                for cb in channelbags:
                    fcs = getattr(cb, "fcurves", None)
                    if fcs:
                        result.extend(fcs)

    return result


# ---------- 集合路径工具 ----------

def find_collection_paths_for_object(obj, root):
    paths = []

    def dfs(coll, path):
        if coll is None:
            return
        found_here = False
        try:
            for o in coll.objects:
                if o == obj or getattr(o, "name", None) == getattr(obj, "name", None):
                    found_here = True
                    break
        except Exception:
            pass
        if found_here:
            paths.append([c.name for c in (path + [coll])])
        try:
            for child in coll.children:
                dfs(child, path + [coll])
        except Exception:
            pass

    dfs(root, [])
    return paths


def choose_collection_path_for_object(obj, target_root=None):
    scn_root = bpy.context.scene.collection
    root = target_root or scn_root
    paths = find_collection_paths_for_object(obj, root)
    if paths:
        return "/".join(paths[0])
    if obj.users_collection:
        return obj.users_collection[0].name
    return ""


# ---------- 导出目标收集（支持替身 MESH） ----------

def collect_target_objects(context, scn):
    mode = getattr(scn, "brt_export_source", "EMPTY_ONLY")
    use_sel = bool(getattr(scn, "brt_use_selection", False))
    coll = getattr(scn, "brt_target_collection", None)

    def in_scope(ob):
        if coll is not None and ob.name not in {o.name for o in getattr(coll, "all_objects", [])}:
            return False
        return True

    if use_sel:
        pool = list(getattr(context, "selected_objects", []) or [])
    else:
        if coll is not None:
            pool = list(getattr(coll, "all_objects", []) or [])
        else:
            pool = list(bpy.data.objects)

    if mode == "EMPTY_ONLY":
        chosen = [o for o in pool if getattr(o, "type", None) == "EMPTY" and in_scope(o)]
    elif mode == "PROXY_ONLY":
        chosen = [o for o in pool if bool(o.get("dlsl_is_drone", False)) and in_scope(o)]
    else:  # BOTH
        chosen = [
            o
            for o in pool
            if (getattr(o, "type", None) == "EMPTY" or bool(o.get("dlsl_is_drone", False))) and in_scope(o)
        ]

    return chosen


# ---------- 导出操作符（帧并集采样） ----------

class QuickIOExportKeyframesOperator(Operator):
    bl_idname = "brt.export_empty"
    bl_label = "导出关键帧 (.brta)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scn = context.scene

        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({"ERROR"}, "请先保存当前 .blend 文件后再导出")
            return {"CANCELLED"}
        base_dir = os.path.dirname(blend_path)
        base_name = os.path.splitext(os.path.basename(blend_path))[0]
        out_path = os.path.join(base_dir, base_name + EXT)
        ensure_dir(out_path)

        frame_start = int(getattr(scn, "frame_start", 1))
        frame_end = int(getattr(scn, "frame_end", 250))
        fps = int(round(scn.render.fps / max(1e-6, scn.render.fps_base))) if hasattr(scn.render, "fps") else 24

        targets = collect_target_objects(context, scn)
        if not targets:
            self.report({"WARNING"}, "未找到可导出的对象（请检查导出源与选择/集合设置）")

        per_obj_frames = {}
        union_frames = set()
        fs = frame_start
        fe = frame_end
        skip_no_kf = bool(getattr(scn, "brt_skip_no_kf", True))
        for obj in targets:
            frames = set()
            ad = getattr(obj, "animation_data", None)
            act = getattr(ad, "action", None)
            if act:
                for fc in get_action_fcurves(act, ad):
                    if fc.data_path in ("location", "rotation_euler", "scale"):
                        for kp in fc.keyframe_points:
                            f = int(round(kp.co.x))
                            if fs <= f <= fe:
                                frames.add(f)
            per_obj_frames[obj.name] = frames
            union_frames.update(frames)
        if skip_no_kf:
            targets = [o for o in targets if per_obj_frames.get(o.name)]

        want_loc = bool(getattr(scn, "brt_export_loc", True))
        want_rot = bool(getattr(scn, "brt_export_rot", True))
        want_scl = bool(getattr(scn, "brt_export_scl", True))

        root_for_path = getattr(scn, "brt_target_collection", None) or bpy.context.scene.collection

        manifest = {
            "version": 3,
            "source": bpy.app.version_string,
            "frame_start": frame_start,
            "frame_end": frame_end,
            "fps": fps,
            "export_source": getattr(scn, "brt_export_source", "EMPTY_ONLY"),
            "objects": [],
        }
        entries = {}
        for obj in targets:
            coll_path = choose_collection_path_for_object(obj, target_root=root_for_path)
            e = {
                "name": obj.name,
                "collection_path": coll_path,
                "type": getattr(obj, "type", "OBJECT"),
                "is_proxy": bool(obj.get("dlsl_is_drone", False)),
                "keyframes": [],
            }
            manifest["objects"].append(e)
            entries[obj.name] = e

        prev_frame = scn.frame_current
        try:
            for f in sorted(union_frames):
                scn.frame_set(f)
                for obj in targets:
                    if f not in per_obj_frames.get(obj.name, set()):
                        continue
                    loc, rot, scale = decompose_world_trs(obj)
                    k = {"frame": int(f)}
                    if want_loc:
                        k["location"] = loc
                    if want_rot:
                        k["rotation_euler"] = rot
                    if want_scl:
                        k["scale"] = scale
                    entries[obj.name]["keyframes"].append(k)
        finally:
            scn.frame_set(prev_frame)

        with open(out_path, "w", encoding="utf-8") as fw:
            json.dump(manifest, fw, ensure_ascii=False, indent=2)

        names_preview = ", ".join([o.get("name", "") for o in manifest["objects"][:5]])
        if names_preview:
            self.report(
                {"INFO"},
                f"已导出 {len(manifest['objects'])} 个对象，帧并集 {len(union_frames)} 帧 -> {out_path}。示例：{names_preview}...",
            )
        else:
            self.report({"INFO"}, f"已导出 {len(manifest['objects'])} 个对象，帧并集 {len(union_frames)} 帧 -> {out_path}")
        return {"FINISHED"}


class QuickIOPreviewOperator(Operator):
    bl_idname = "brt.preview_empty"
    bl_label = "预览（对象与帧并集）"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scn = context.scene
        targets = collect_target_objects(context, scn)
        frame_start = int(getattr(scn, "frame_start", 1))
        frame_end = int(getattr(scn, "frame_end", 250))
        union_frames = set()
        for obj in targets:
            ad = getattr(obj, "animation_data", None)
            act = getattr(ad, "action", None)
            if act:
                for fc in get_action_fcurves(act, ad):
                    if fc.data_path in ("location", "rotation_euler", "scale"):
                        for kp in fc.keyframe_points:
                            f = int(round(kp.co.x))
                            if frame_start <= f <= frame_end:
                                union_frames.add(f)
        names = ", ".join([o.name for o in targets[:10]])
        self.report({"INFO"}, f"对象数 {len(targets)}，帧并集 {len(union_frames)}。示例对象：{names}...")
        return {"FINISHED"}


# ---------- 生成菱角球对象（2.92 兼容） ----------

def _create_icosphere_compat(bm, subdivisions, radius):
    r = max(1e-6, float(radius))
    subs = max(0, int(subdivisions))
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subs, radius=r)
        return True
    except TypeError:
        pass
    except Exception:
        pass
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subs, diameter=2.0 * r)
        return True
    except Exception:
        pass
    try:
        u = max(8, 6 + subs * 4)
        v = max(6, 4 + subs * 2)
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
        except TypeError:
            bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, diameter=2.0 * r)
        return True
    except Exception:
        return False


def create_icosphere_object(name: str, radius: float, subdivisions: int, collection: bpy.types.Collection) -> bpy.types.Object:
    me = bpy.data.meshes.new(f"{name}_Mesh")
    bm = bmesh.new()
    ok = _create_icosphere_compat(bm, subdivisions, radius)
    if not ok:
        bmesh.ops.create_cube(bm, size=max(1e-6, float(radius)))
    bm.to_mesh(me)
    bm.free()
    try:
        me.update()
    except Exception:
        pass
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


# ---------- 导入操作符（可导入为菱角球替身） ----------

class QuickIOImportKeyframesOperator(Operator):
    bl_idname = "brt.import_empty"
    bl_label = "导入关键帧 (.brta)"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(name="文件路径", subtype="FILE_PATH", default="")

    def invoke(self, context, event):
        self.filepath = context.scene.brt_import_path or ""
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        in_path = self.filepath or context.scene.brt_import_path
        if not in_path or not os.path.exists(in_path):
            self.report({"ERROR"}, "请选择有效的 .brta 文件")
            return {"CANCELLED"}

        try:
            with open(in_path, "r", encoding="utf-8") as fr:
                data = json.load(fr)
        except Exception as e:
            self.report({"ERROR"}, f"读取失败: {e}")
            return {"CANCELLED"}

        scn = context.scene
        frame_start = int(data.get("frame_start", getattr(scn, "frame_start", 1)))
        frame_end = int(data.get("frame_end", getattr(scn, "frame_end", 250)))
        fps = int(data.get("fps", 24))

        try:
            scn.frame_start = frame_start
            scn.frame_end = frame_end
            if hasattr(scn.render, "fps"):
                scn.render.fps = fps
                scn.render.fps_base = 1.0
        except Exception:
            pass

        def ensure_collection_path(path_str: str) -> bpy.types.Collection:
            scene_root = bpy.context.scene.collection
            if not path_str:
                return scene_root
            parts = [p for p in path_str.split("/") if p]
            if not parts:
                return scene_root
            if parts and parts[0] == scene_root.name:
                parts = parts[1:]
            parent = scene_root
            for name in parts:
                child = None
                for c in parent.children:
                    if c.name == name:
                        child = c
                        break
                if child is None:
                    child = bpy.data.collections.new(name)
                    parent.children.link(child)
                parent = child
            return parent

        created = 0
        imp_type = getattr(scn, "brt_import_proxy_type", "EMPTY")
        ico_radius = float(getattr(scn, "brt_import_ico_radius", 0.1))
        ico_subdiv = int(getattr(scn, "brt_import_ico_subdiv", 1))
        empty_size = float(getattr(scn, "brt_import_empty_size", 1.0))

        for ent in data.get("objects", []):
            name = ent.get("name", "Empty")
            coll_path = ent.get("collection_path", "")

            target_coll = ensure_collection_path(coll_path)

            base_name = name
            final_name = base_name
            if final_name in bpy.data.objects:
                i = 1
                while f"{base_name}.{i:03d}" in bpy.data.objects:
                    i += 1
                final_name = f"{base_name}.{i:03d}"

            if imp_type == "ICOSPHERE":
                ob = create_icosphere_object(final_name, ico_radius, ico_subdiv, target_coll)
                ob["dlsl_is_drone"] = True
            else:
                ob = bpy.data.objects.new(final_name, None)
                try:
                    ob.empty_display_type = "PLAIN_AXES"
                except Exception:
                    pass
                ob.empty_display_size = max(1e-6, empty_size)
                target_coll.objects.link(ob)

            for kf in ent.get("keyframes", []):
                f = int(kf.get("frame", scn.frame_current))
                loc = kf.get("location")
                rot = kf.get("rotation_euler")
                scale = kf.get("scale")

                scn.frame_set(f)
                if loc is not None:
                    ob.location = tuple(loc)
                    ob.keyframe_insert(data_path="location")
                if rot is not None:
                    ob.rotation_mode = "XYZ"
                    ob.rotation_euler = tuple(rot)
                    ob.keyframe_insert(data_path="rotation_euler")
                if scale is not None:
                    ob.scale = tuple(scale)
                    ob.keyframe_insert(data_path="scale")

            created += 1

        context.scene.brt_import_path = in_path
        self.report({"INFO"}, f"导入完成：{created} 个对象，帧范围 {frame_start}-{frame_end}")
        return {"FINISHED"}


# ---------- Skybrush：创建替身并镜像烘焙 ----------

class QuickIOCreateAndBakeProxiesOperator(Operator):
    bl_idname = "brt.create_and_bake_proxies"
    bl_label = "创建替身并镜像到返航开始帧（烘焙）"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scn = context.scene
        drones_col_name = (getattr(scn, "sky_drones_collection", "Drones") or "Drones").strip() or "Drones"
        user_prefix = (getattr(scn, "sky_proxies_collection", "RTH_Proxies") or "RTH_Proxies").strip()
        proxies_col_name = user_prefix or "RTH_Proxies"

        from_f = int(getattr(scn, "sky_mirror_from_frame", 0))
        to_f = int(getattr(scn, "sky_mirror_to_frame", 0))
        step = max(1, int(getattr(scn, "sky_mirror_step", 1)))
        adaptive = bool(getattr(scn, "sky_mirror_adaptive", True))
        gap_thresh = float(getattr(scn, "sky_mirror_max_gap", 0.50))
        angle_thresh_rad = float(getattr(scn, "sky_mirror_max_angle", 12.0))
        angle_thresh_rad = __import__("math").radians(angle_thresh_rad)

        scene = context.scene
        if from_f <= 0:
            from_f = scene.frame_start
        home_frame = from_f
        if to_f <= 0:
            to_f = scene.frame_current
        if to_f < from_f:
            self.report({"ERROR"}, f"镜像结束帧({to_f}) 不能小于开始帧({from_f})")
            return {"CANCELLED"}

        col = bpy.data.collections.get(drones_col_name)
        if not col:
            self.report({"ERROR"}, f"集合不存在: {drones_col_name}")
            return {"CANCELLED"}
        drones = [o for o in col.objects if o.type in {"MESH", "EMPTY"}]
        if not drones:
            self.report({"ERROR"}, f"集合 {drones_col_name} 中未找到对象")
            return {"CANCELLED"}
        drones.sort(key=lambda o: (_numeric_suffix(o.name) or 10**9))

        proxies_col = ensure_collection(proxies_col_name)
        proxies = []
        prefix = user_prefix

        proxy_type = getattr(scn, "sky_proxy_type", "EMPTY")
        empty_size = float(getattr(scn, "sky_proxy_empty_size", 1.0))
        ico_radius = float(getattr(scn, "sky_proxy_ico_radius", 0.1))
        ico_subdiv = int(getattr(scn, "sky_proxy_ico_subdiv", 1))

        for idx, _ in enumerate(drones, start=1):
            base = f"{prefix}_{idx}" if prefix else f"{idx}"
            name = base
            ob = bpy.data.objects.get(name)
            if ob is None:
                if proxy_type == "ICOSPHERE":
                    ob = create_icosphere_object(name, ico_radius, ico_subdiv, proxies_col)
                else:
                    ob = bpy.data.objects.new(name, None)
                    ob.empty_display_size = max(1e-6, empty_size)
                    try:
                        ob.empty_display_type = "PLAIN_AXES"
                    except Exception:
                        pass
                    proxies_col.objects.link(ob)
            else:
                if ob not in proxies_col.objects:
                    proxies_col.objects.link(ob)
            ob["dlsl_is_drone"] = True
            proxies.append(ob)

        cur = scene.frame_current
        scene.frame_set(home_frame)
        for i, dr in enumerate(drones):
            proxies[i].location = dr.matrix_world.translation.copy()
            proxies[i].keyframe_insert(data_path="location", frame=home_frame)

        count_frames = 0
        last_keyed = None
        last_key_pos = [None] * len(drones)
        last_key_frame = [None] * len(drones)
        last_dir = [None] * len(drones)

        scene.frame_set(home_frame)
        for i, dr in enumerate(drones):
            last_key_pos[i] = dr.matrix_world.translation.copy()
            last_key_frame[i] = home_frame
            last_dir[i] = None

        for f in range(from_f, to_f + 1, step):
            scene.frame_set(f)
            any_keyed_at_f = False
            for i, dr in enumerate(drones):
                pos = dr.matrix_world.translation.copy()
                force_key = f == from_f
                do_key = True
                if adaptive and not force_key:
                    prev_pos = last_key_pos[i]
                    if prev_pos is None:
                        do_key = True
                    else:
                        delta = pos - prev_pos
                        dist = delta.length
                        do_key = dist >= gap_thresh
                        if not do_key and dist > 1e-12:
                            cur_dir = delta.normalized()
                            if last_dir[i] is not None:
                                import math

                                dotv = max(-1.0, min(1.0, last_dir[i].dot(cur_dir)))
                                ang = math.acos(dotv)
                                if ang >= angle_thresh_rad:
                                    do_key = True
                if do_key:
                    proxies[i].location = pos
                    proxies[i].keyframe_insert(data_path="location", frame=f)
                    any_keyed_at_f = True
                    if last_key_pos[i] is not None:
                        seg = pos - last_key_pos[i]
                        if seg.length > 1e-12:
                            last_dir[i] = seg.normalized()
                    last_key_pos[i] = pos
                    last_key_frame[i] = f
            if any_keyed_at_f:
                count_frames += 1
                last_keyed = f

        if last_keyed is None or last_keyed != to_f:
            scene.frame_set(to_f)
            for i, dr in enumerate(drones):
                proxies[i].location = dr.matrix_world.translation.copy()
                proxies[i].keyframe_insert(data_path="location", frame=to_f)
            count_frames += 1
        scene.frame_set(cur)
        self.report(
            {"INFO"},
            f"替身已镜像烘焙：{len(proxies)} 个对象，帧区间 {from_f}–{to_f}（共 {count_frames} 帧）",
        )
        return {"FINISHED"}


# ---------- 批量重命名（选中对象） ----------

class QuickIOBatchRenameOperator(Operator):
    bl_idname = "brt.batch_rename"
    bl_label = "批量重命名（选中对象）"
    bl_options = {"REGISTER", "UNDO"}

    base_name: StringProperty(
        name="基础名称",
        description="可留空。留空时将按 1, 2, 3… 命名；不为空时使用 基础名称_序号",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "selected_objects", []))

    def execute(self, context):
        selected = list(getattr(context, "selected_objects", []) or [])

        def world_xyz(o):
            try:
                t = o.matrix_world.translation
                return (float(t.x), float(t.y), float(t.z), o.name)
            except Exception:
                return (0.0, 0.0, 0.0, o.name)

        selected.sort(key=world_xyz)

        base = (self.base_name or getattr(context.scene, "brt_batch_base_name", "") or "").strip()
        for i, obj in enumerate(selected, start=1):
            if base:
                obj.name = f"{base}_{i}"
            else:
                obj.name = f"{i}"
        self.report({"INFO"}, f"已按世界X轴排序并重命名 {len(selected)} 个对象")
        return {"FINISHED"}


# ---------- 场景属性注册 ----------

def register_quick_io_scene_properties():
    bpy.types.Scene.brt_target_collection = PointerProperty(
        name="目标集合",
        type=bpy.types.Collection,
        description="限定导出/预览的对象范围；为空则遍历全局",
    )
    bpy.types.Scene.brt_use_selection = BoolProperty(
        name="仅导出所选",
        default=False,
        description="若勾选，则忽略集合设置，仅导出当前所选对象",
    )
    bpy.types.Scene.brt_export_source = EnumProperty(
        name="导出源",
        description="选择导出对象来源：空物体/替身/两者",
        items=(
            ("EMPTY_ONLY", "仅空物体", "仅导出类型为 EMPTY 的对象"),
            ("PROXY_ONLY", "仅替身", "仅导出打了 dlsl_is_drone 标记的对象(EMPTY 或 MESH)"),
            ("BOTH", "空物体+替身", "合并导出 EMPTY 与替身对象"),
        ),
        default="PROXY_ONLY",
    )
    bpy.types.Scene.brt_export_loc = BoolProperty(name="导出位置", default=True)
    bpy.types.Scene.brt_export_rot = BoolProperty(name="导出旋转", default=True)
    bpy.types.Scene.brt_export_scl = BoolProperty(name="导出缩放", default=True)
    bpy.types.Scene.brt_skip_no_kf = BoolProperty(name="跳过无关键帧对象", default=True)
    bpy.types.Scene.brt_import_path = StringProperty(name="导入路径", subtype="FILE_PATH", default="")
    bpy.types.Scene.brt_batch_base_name = StringProperty(
        name="基础名称",
        description="可留空。留空则按 1,2,3… 命名；填写则为 基础名称_序号",
        default="",
    )

    # Skybrush 创建替身属性
    bpy.types.Scene.sky_drones_collection = StringProperty(name="Drones集合名", default="Drones")
    bpy.types.Scene.sky_proxies_collection = StringProperty(name="替身集合名", default="RTH_Proxies")
    bpy.types.Scene.sky_mirror_from_frame = IntProperty(name="镜像起始帧(0=起始)", default=0, min=0)
    bpy.types.Scene.sky_mirror_to_frame = IntProperty(name="镜像结束帧(0=当前)", default=0, min=0)
    bpy.types.Scene.sky_mirror_step = IntProperty(name="步长(帧)", default=100, min=1)
    bpy.types.Scene.sky_mirror_adaptive = BoolProperty(name="自适应镜像采样", default=True)
    bpy.types.Scene.sky_mirror_max_gap = FloatProperty(name="自适应最大位移(米)", default=0.50, min=0.0)
    bpy.types.Scene.sky_mirror_max_angle = FloatProperty(name="自适应最大转角(度)", default=12.0, min=0.0, max=180.0)

    # 替身类型与参数（创建阶段）—— 默认空物体，显示尺寸默认 1
    bpy.types.Scene.sky_proxy_type = EnumProperty(
        name="替身类型",
        description="选择创建的替身对象类型",
        items=(
            ("EMPTY", "空物体", "创建空物体作为替身"),
            ("ICOSPHERE", "菱角球", "创建菱角球(Icosphere)作为替身"),
        ),
        default="EMPTY",
    )
    bpy.types.Scene.sky_proxy_empty_size = FloatProperty(name="空物体显示尺寸", default=1.0, min=0.001, soft_min=0.001)
    bpy.types.Scene.sky_proxy_ico_radius = FloatProperty(name="菱角球半径", default=0.1, min=0.001, soft_min=0.001)
    bpy.types.Scene.sky_proxy_ico_subdiv = IntProperty(name="菱角球细分", default=1, min=0, max=5)

    # 导入阶段：导入目标类型与参数 —— 默认空物体，显示尺寸默认 1
    bpy.types.Scene.brt_import_proxy_type = EnumProperty(
        name="导入对象类型",
        description="导入 .brta 时创建的对象类型",
        items=(
            ("EMPTY", "空物体", "导入为空物体"),
            ("ICOSPHERE", "菱角球", "导入为菱角球(Icosphere)替身"),
        ),
        default="EMPTY",
    )
    bpy.types.Scene.brt_import_empty_size = FloatProperty(name="空物体显示尺寸", default=1.0, min=0.001, soft_min=0.001)
    bpy.types.Scene.brt_import_ico_radius = FloatProperty(name="菱角球半径", default=0.1, min=0.001, soft_min=0.001)
    bpy.types.Scene.brt_import_ico_subdiv = IntProperty(name="菱角球细分", default=1, min=0, max=5)

    # UI 折叠状态
    bpy.types.Scene.ui_fold_sky = BoolProperty(name="展开：创建替身并镜像烘焙", default=True)
    bpy.types.Scene.ui_fold_export = BoolProperty(name="展开：导出关键帧设置", default=True)
    bpy.types.Scene.ui_fold_import = BoolProperty(name="展开：导入关键帧设置", default=True)
    bpy.types.Scene.ui_fold_tools = BoolProperty(name="展开：选中物体批量重命名", default=True)


def unregister_quick_io_scene_properties():
    del bpy.types.Scene.ui_fold_tools
    del bpy.types.Scene.ui_fold_import
    del bpy.types.Scene.ui_fold_export
    del bpy.types.Scene.ui_fold_sky
    del bpy.types.Scene.brt_import_ico_subdiv
    del bpy.types.Scene.brt_import_ico_radius
    del bpy.types.Scene.brt_import_empty_size
    del bpy.types.Scene.brt_import_proxy_type
    del bpy.types.Scene.sky_proxy_ico_subdiv
    del bpy.types.Scene.sky_proxy_ico_radius
    del bpy.types.Scene.sky_proxy_empty_size
    del bpy.types.Scene.sky_proxy_type
    del bpy.types.Scene.sky_mirror_max_angle
    del bpy.types.Scene.sky_mirror_max_gap
    del bpy.types.Scene.sky_mirror_adaptive
    del bpy.types.Scene.sky_mirror_step
    del bpy.types.Scene.sky_mirror_to_frame
    del bpy.types.Scene.sky_mirror_from_frame
    del bpy.types.Scene.sky_proxies_collection
    del bpy.types.Scene.sky_drones_collection
    del bpy.types.Scene.brt_batch_base_name
    del bpy.types.Scene.brt_import_path
    del bpy.types.Scene.brt_skip_no_kf
    del bpy.types.Scene.brt_export_scl
    del bpy.types.Scene.brt_export_rot
    del bpy.types.Scene.brt_export_loc
    del bpy.types.Scene.brt_export_source
    del bpy.types.Scene.brt_use_selection
    del bpy.types.Scene.brt_target_collection
