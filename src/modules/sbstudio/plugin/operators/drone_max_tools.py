import csv
import io
import json
import math
import os
import zipfile

import bmesh
import bpy
import numpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup
from bpy_extras.io_utils import ImportHelper

from sbstudio.plugin.actions import (
    ensure_animation_data_exists_for_object,
    ensure_f_curve_exists_for_data_path_and_index,
    iter_all_f_curves,
)
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.utils.evaluator import create_position_evaluator
from sbstudio.plugin.utils.landing_estimate import (
    RTL_MODE_SWITCH_DELAY,
    estimate_real_landing_duration,
    get_localized_marker_name,
    place_landed_time_marker,
)

__all__ = (
    "DroneMaxImageFormationProperties",
    "DroneMaxNamedEmptyProperties",
    "DroneMaxSkycImportProperties",
    "DroneMaxUIState",
    "DroneMaxVertsToEmptiesProperties",
    "DroneMaxLandingProperties",
    "DroneMaxSelectImageOperator",
    "DroneMaxGeneratePointsOperator",
    "DroneMaxGenerateEmptiesOperator",
    "DroneMaxCreateNamedEmptyOperator",
    "DroneMaxVertsToEmptiesOperator",
    "DroneMaxSkycConvertAndImportOperator",
    "DroneMaxLandingDescendOperator",
    "DroneMaxReadCurrentFrameToPropOperator",
    "register_drone_max_scene_properties",
    "unregister_drone_max_scene_properties",
)

LANDING_GROUP_LANDED_MARKER_MSGID = "All Drones Landed Time"


class DroneMaxUIState(PropertyGroup):
    show_section_1: BoolProperty(name="1. 参考图片转队形", default=False)
    show_section_2: BoolProperty(name="2. 以选中物体的位置创建空物体", default=False)
    show_section_3: BoolProperty(name="3. 顶点模型转空物体纯轴", default=False)
    show_section_4: BoolProperty(name="4. SKYC 导入工具", default=False)
    show_section_9: BoolProperty(name="9. 降落设置", default=False)


class DroneMaxImageFormationProperties(PropertyGroup):
    image_path: StringProperty(name="参考图片", description="参考图片路径", default="", subtype="FILE_PATH")
    min_distance: FloatProperty(name="最小间距", description="无人机最小间距（Blender当前单位）", default=2.5, min=0.0001)
    empty_collection_name: StringProperty(name="基础名称", description="用于集合与空物体命名", default="输入参考模型名称")


class DroneMaxNamedEmptyProperties(PropertyGroup):
    base_name: StringProperty(name="重命名为", description="输入纯轴空物体名称", default="Enter empty name")


class DroneMaxVertsToEmptiesProperties(PropertyGroup):
    collection_name: StringProperty(name="集合名称", default="VertexEmpties")
    empty_size: FloatProperty(name="空物体尺寸", default=1.0, min=0.001, soft_min=0.01, soft_max=100.0)
    clear_before: BoolProperty(name="生成前清空集合", default=True)
    only_selected_objects: BoolProperty(name="仅对选中对象", default=True)


class DroneMaxSkycImportProperties(PropertyGroup):
    skyc_file: StringProperty(name="SKYC 文件", subtype="FILE_PATH", description="选择 .skyc 文件")
    import_fps: FloatProperty(name="导入帧率 (FPS)", default=24.0, min=1.0, max=120.0)
    start_frame: IntProperty(name="起始帧", default=1)
    empty_size: FloatProperty(name="空物体尺寸", default=0.2)
    coord_mode: EnumProperty(
        name="坐标系",
        items=(
            ("Z_UP", "Z轴向上 (默认)", ""),
            ("Y_UP", "Y轴转Z轴", ""),
        ),
        default="Z_UP",
    )
    per_frame: BoolProperty(name="逐帧导入", default=True)
    keyframe_step: IntProperty(name="关键帧步长", default=1, min=1, max=100)
    sample_dt: FloatProperty(name="CSV 采样间隔 (秒)", default=0.25)
    use_linear: BoolProperty(name="忽略贝塞尔手柄", default=False)
    force_linear_keys: BoolProperty(name="强制线性关键帧", default=True)
    global_time_offset: FloatProperty(name="手动时间偏移 (秒)", default=0.0)
    enable_debug: BoolProperty(name="启用调试信息", default=False)
    save_csv: BoolProperty(name="同时导出 CSV", default=False)
    show_advanced: BoolProperty(name="高级选项", default=False)


class DroneMaxLandingProperties(PropertyGroup):
    start_frame: IntProperty(
        name="在此帧",
        description="下降动画开始的关键帧",
        default=1,
        min=0,
    )
    velocity_z: FloatProperty(
        name="下降速度",
        description="降落集合中的空物体下降到返航高度时的平均垂直速度",
        default=2.0,
        min=0.1,
        soft_min=0.1,
        soft_max=10.0,
        unit="VELOCITY",
    )
    rth_altitude: FloatProperty(
        name="返航高度",
        description=(
            "下降动画结束时的最低高度；动画到此结束，剩余的真实降落交由无人机"
            "自身飞控在 RTL 模式下完成"
        ),
        default=5.0,
        min=0.1,
        soft_max=20.0,
        unit="LENGTH",
    )
    scale_down_drones: BoolProperty(
        name="无人机缩小",
        description="降落结束时将无人机缩回 0.15 米，避免落地后穿模",
        default=True,
    )


def flood_fill_points(pixels, x, y, background):
    w = pixels.shape[1]
    h = pixels.shape[0]
    stack = [(x, y)]
    points = []
    while stack:
        cx, cy = stack.pop()
        if cx < 0 or cy < 0 or cx >= w or cy >= h:
            continue
        if pixels[cy, cx] == background:
            continue
        pixels[cy, cx] = background
        points.append((cx, cy))
        stack += [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]
    return points


class DroneMaxSelectImageOperator(Operator, ImportHelper):
    bl_idname = "dronemax.select_image"
    bl_label = "选择参考图片"
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tiff;*.bmp;*.tga", options={"HIDDEN"})

    def execute(self, context):
        context.scene.dronemax_image_props.image_path = self.filepath
        self.report({"INFO"}, f"Selected image: {self.filepath}")
        return {"FINISHED"}


class DroneMaxGeneratePointsOperator(Operator):
    bl_idname = "dronemax.generate_points"
    bl_label = "生成顶点模型"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.dronemax_image_props
        if not props.image_path:
            self.report({"ERROR"}, "未选择参考图片")
            return {"CANCELLED"}
        try:
            image = bpy.data.images.load(props.image_path)
        except RuntimeError:
            self.report({"ERROR"}, f"加载参考图片失败: {props.image_path}")
            return {"CANCELLED"}
        width, height = image.size
        pixels = numpy.array(image.pixels).reshape((width * height, 4))
        gray = numpy.apply_along_axis(lambda c: (c[0] + c[1] + c[2]) / 3.0, 1, pixels)
        threshold = 0.5 * (numpy.min(gray) + numpy.max(gray))
        binary = (gray < threshold).reshape((height, width))
        background = numpy.sum(binary) * 2 > len(binary.reshape(-1))
        points = []
        for y in range(height):
            for x in range(width):
                if binary[y, x] != background:
                    region = numpy.array(flood_fill_points(binary, x, y, background))
                    points.append(numpy.average(region, axis=0))
        if len(points) < 2:
            scale = 1.0
        else:
            arr = numpy.array(points)
            diffs = []
            for i in range(len(arr)):
                for j in range(i + 1, len(arr)):
                    diffs.append(arr[i] - arr[j])
            min_distance = numpy.sqrt(numpy.min(numpy.sum(numpy.array(diffs) ** 2, axis=1)))
            scale = props.min_distance / min_distance if min_distance else 1.0
        name, _ = os.path.splitext(os.path.basename(props.image_path))
        mesh = bpy.data.meshes.new("mesh_" + name)
        bm = bmesh.new()
        for cx, cy in points:
            bm.verts.new((cx * scale, 0, cy * scale))
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        context.scene.collection.objects.link(obj)
        for item in context.view_layer.objects:
            item.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.origin_set(type="GEOMETRY_ORIGIN", center="MEDIAN")
        self.report({"INFO"}, f"正在创建 '{name}' ，缩放系数: {scale}")
        return {"FINISHED"}


class DroneMaxGenerateEmptiesOperator(Operator):
    bl_idname = "dronemax.generate_empties"
    bl_label = "生成空物体纯轴"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.dronemax_image_props
        if not props.image_path:
            self.report({"ERROR"}, "请先选择参考图片")
            return {"CANCELLED"}
        obj = None
        try:
            previous = context.active_object
            bpy.ops.dronemax.generate_points()
            obj = context.active_object
            if not obj or obj.type != "MESH":
                raise Exception("未找到顶点模型")
            base = props.empty_collection_name
            collection = bpy.data.collections.get(base) or bpy.data.collections.new(base)
            if collection.name not in [c.name for c in context.scene.collection.children]:
                context.scene.collection.children.link(collection)
            for index, vertex in enumerate(obj.data.vertices, 1):
                empty = bpy.data.objects.new(f"{base}_{index}", None)
                empty.empty_display_type = "PLAIN_AXES"
                empty.empty_display_size = props.min_distance * 0.5
                empty.location = obj.matrix_world @ vertex.co
                collection.objects.link(empty)
            if previous:
                context.view_layer.objects.active = previous
            count = len(obj.data.vertices)
            bpy.data.objects.remove(obj, do_unlink=True)
            self.report({"INFO"}, f"已创建 {count} 个空物体纯轴")
            return {"FINISHED"}
        except Exception as exc:
            if obj and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            self.report({"ERROR"}, f"生成空物体失败: {exc}")
            return {"CANCELLED"}


class DroneMaxCreateNamedEmptyOperator(Operator):
    bl_idname = "dronemax.create_named_empty"
    bl_label = "以选中物体的位置创建空物体"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.dronemax_named_empty_props
        selected = context.selected_objects
        if not selected:
            self.report({"ERROR"}, "未选择任何物体")
            return {"CANCELLED"}
        collection = bpy.data.collections.get(props.base_name) or bpy.data.collections.new(props.base_name)
        if collection.name not in [c.name for c in context.scene.collection.children]:
            context.scene.collection.children.link(collection)
        use_index = len(selected) > 1
        for index, obj in enumerate(selected, 1):
            name = f"{props.base_name}_{index}" if use_index else props.base_name
            empty = bpy.data.objects.new(name, None)
            empty.location = obj.location
            empty.empty_display_size = 1.0
            empty.empty_display_type = "PLAIN_AXES"
            collection.objects.link(empty)
        self.report({"INFO"}, f"已创建 {len(selected)} 个命名纯轴")
        return {"FINISHED"}


class DroneMaxVertsToEmptiesOperator(Operator):
    bl_idname = "dronemax.verts_to_empties"
    bl_label = "顶点模型转空物体纯轴"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.dronemax_v2e_props
        base = props.collection_name.strip() or "VertexEmpties"
        collection = bpy.data.collections.get(base) or bpy.data.collections.new(base)
        if collection.name not in [c.name for c in context.scene.collection.children]:
            context.scene.collection.children.link(collection)
        if props.clear_before:
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            for child in list(collection.children):
                collection.children.unlink(child)
                bpy.data.collections.remove(child)
        start_index = 1
        targets = [obj for obj in (context.selected_objects if props.only_selected_objects else context.scene.objects) if obj and obj.type == "MESH"]
        if not targets:
            self.report({"WARNING"}, "未找到网格对象")
            return {"CANCELLED"}
        created = 0
        for obj in targets:
            is_edit = obj.mode == "EDIT"
            if is_edit:
                bpy.ops.object.mode_set(mode="OBJECT")
            matrix = obj.matrix_world.copy()
            for vertex in obj.data.vertices:
                empty = bpy.data.objects.new(f"{base}_{start_index}", None)
                empty.empty_display_type = "PLAIN_AXES"
                empty.empty_display_size = float(props.empty_size)
                empty.location = matrix @ vertex.co
                collection.objects.link(empty)
                created += 1
                start_index += 1
            if is_edit:
                bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, f"已创建 {created} 个空物体到集合 '{collection.name}'，命名为 {base}_N")
        return {"FINISHED"}


def _bezier_point(p0, c0, c1, p1, u):
    one_minus_u = 1.0 - u
    return [
        one_minus_u ** 3 * p0[0] + 3 * one_minus_u ** 2 * u * c0[0] + 3 * one_minus_u * u ** 2 * c1[0] + u ** 3 * p1[0],
        one_minus_u ** 3 * p0[1] + 3 * one_minus_u ** 2 * u * c0[1] + 3 * one_minus_u * u ** 2 * c1[1] + u ** 3 * p1[1],
        one_minus_u ** 3 * p0[2] + 3 * one_minus_u ** 2 * u * c0[2] + 3 * one_minus_u * u ** 2 * c1[2] + u ** 3 * p1[2],
    ]


def _eval_segments(points, t, use_linear=False):
    if not points:
        return [0.0, 0.0, 0.0]
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    lo = 0
    hi = len(points) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if points[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    start = points[lo]
    end = points[hi]
    t0 = start[0]
    t1 = end[0]
    if t1 == t0:
        return end[1]
    u = (t - t0) / (t1 - t0)
    control = end[2] if len(end) > 2 else None
    if not use_linear and control and len(control) == 2:
        return _bezier_point(start[1], control[0], control[1], end[1], u)
    return [
        start[1][0] + (end[1][0] - start[1][0]) * u,
        start[1][1] + (end[1][1] - start[1][1]) * u,
        start[1][2] + (end[1][2] - start[1][2]) * u,
    ]


def _transform_coords(x, y, z, mode):
    if mode == "Y_UP":
        return x, -z, y
    return x, y, z


def _read_show_and_trajectories(skyc_path, debug=False):
    drones_data = []
    with zipfile.ZipFile(skyc_path, "r") as zip_file:
        if "show.json" not in zip_file.namelist():
            raise Exception("show.json not found in .skyc")
        with zip_file.open("show.json") as handle:
            show = json.load(io.TextIOWrapper(handle, encoding="utf-8"))
        drones = show.get("swarm", {}).get("drones", [])
        for index, drone in enumerate(drones):
            settings = drone.get("settings", {})
            name = settings.get("name", f"Drone {index + 1}")
            base_offset = settings.get("timeOffset", 0.0) or settings.get("startTime", 0.0) or settings.get("delay", 0.0)
            trajectory_obj = settings.get("trajectory", {})
            trajectory_ref = trajectory_obj.get("$ref")
            if not trajectory_ref:
                if "points" in trajectory_obj:
                    drones_data.append({"name": name, "points": trajectory_obj["points"], "offset": base_offset + trajectory_obj.get("takeoffTime", 0.0)})
                continue
            ref_path = trajectory_ref.split("#", 1)[0].lstrip("./")
            if not ref_path:
                continue
            try:
                with zip_file.open(ref_path) as trajectory_handle:
                    trajectory = json.load(io.TextIOWrapper(trajectory_handle, encoding="utf-8"))
                takeoff_time = trajectory.get("takeoffTime", 0.0)
                if debug and index == 0:
                    print(f"[DEBUG] {name}: BaseOffset={base_offset}, TakeoffTime={takeoff_time}, Total={base_offset + takeoff_time}")
                drones_data.append({"name": name, "points": trajectory.get("points", []), "offset": base_offset + takeoff_time})
            except Exception as exc:
                print(f"[WARNING] Load failed {ref_path}: {exc}")
    return drones_data


def _sample_to_csv_rows(points, dt, offset=0.0, use_linear=False):
    if not points:
        return []
    total_duration = offset + points[-1][0]
    t_global = 0.0
    rows = []
    while t_global <= total_duration + 1e-6:
        t_local = t_global - offset
        x, y, z = _eval_segments(points, t_local, use_linear=use_linear)
        rows.append((int(round(t_global * 1000)), round(x, 4), round(y, 4), round(z, 4), 255, 255, 255))
        t_global += dt
    return rows


def _write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Time [msec]", "x [m]", "y [m]", "z [m]", "Red", "Green", "Blue"])
        writer.writerows(rows)


def _ensure_skyc_import_collection(context, name: str) -> bpy.types.Collection:
    """获取或创建一个用于存放 SKYC 导入空物体的集合，避免根目录凌乱。"""
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        context.scene.collection.children.link(col)
    elif name not in context.scene.collection.children.keys():
        context.scene.collection.children.link(col)
    return col


class DroneMaxSkycConvertAndImportOperator(Operator):
    bl_idname = "dronemax.skyc_convert_import"
    bl_label = "导入.skyc文件"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.dronemax_skyc_props
        skyc_path = bpy.path.abspath(props.skyc_file)
        if not os.path.isfile(skyc_path):
            self.report({"ERROR"}, "无效的 .skyc 路径")
            return {"CANCELLED"}
        if props.enable_debug:
            self.report({"INFO"}, "请查看控制台调试信息")
        try:
            drones = _read_show_and_trajectories(skyc_path, debug=props.enable_debug)
        except Exception as exc:
            self.report({"ERROR"}, f"读取失败: {exc}")
            return {"CANCELLED"}
        base_dir = os.path.dirname(skyc_path)
        skyc_basename = os.path.splitext(os.path.basename(skyc_path))[0]
        csv_dir = os.path.join(base_dir, skyc_basename + "_CSV")
        import_col = _ensure_skyc_import_collection(context, f"SKYC_{skyc_basename}")
        created_count = 0
        for drone_data in drones:
            name = drone_data["name"]
            points = drone_data["points"]
            offset = drone_data["offset"] + props.global_time_offset
            if props.save_csv:
                try:
                    _write_csv(os.path.join(csv_dir, f"{name}.csv"), _sample_to_csv_rows(points, props.sample_dt, offset=offset, use_linear=props.use_linear))
                except Exception as exc:
                    print(f"CSV 写入错误 {name}: {exc}")
            if not points:
                continue
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_type = "PLAIN_AXES"
            obj.empty_display_size = float(props.empty_size)
            import_col.objects.link(obj)
            last_frame = int(math.ceil(max(offset + points[-1][0], 0.0) * props.import_fps))
            for frame in range(0, last_frame + 1, props.keyframe_step):
                t_global = frame / props.import_fps
                x, y, z = _eval_segments(points, t_global - offset, use_linear=props.use_linear)
                obj.location = _transform_coords(x, y, z, props.coord_mode)
                obj.keyframe_insert(data_path="location", frame=props.start_frame + frame)
            if props.force_linear_keys and obj.animation_data and obj.animation_data.action:
                for fcurve in iter_all_f_curves(obj.animation_data):
                    for keyframe in fcurve.keyframe_points:
                        keyframe.interpolation = "LINEAR"
            created_count += 1
        self.report({"INFO"}, f"已导入 {created_count} 架无人机")
        return {"FINISHED"}


class DroneMaxLandingDescendOperator(Operator):
    """将降落集合中的无人机空物体（如 RTH_1、RTH_2、RTH_3 等分层集合）沿 Z 轴
    统一下降到指定的返航高度。

    下降原理与“编队悬停测试”的整体刚体下降完全一致：集合内所有空物体以相同的
    垂直速度同时下降，彼此的相对高度差保持不变，直到最低的空物体到达“返航
    高度”为止，动画到此结束，剩余的真实降落交由无人机自身飞控在 RTL 模式下
    完成。执行后会在时间轴自动放置一个本地化的“落地时间”标记，标记的估算方法
    与编队悬停测试相同：RTL 切换后的 3 秒原地悬停，加上固件两段式降落速度
    （1 米以上 1.3m/s，1 米及以下 0.4m/s）推算出的真实降落耗时。

    下降速度、返航高度由场景中的 ``dronemax_landing_props`` 直接提供，
    无需弹窗，操作符点击后立即执行。
    """

    bl_idname = "dronemax.landing_descend"
    bl_label = "开始降落"
    bl_description = (
        "对降落集合中的无人机空物体沿 Z 轴统一下降到返航高度（原理与编队悬停测试"
        "的刚体下降一致），并自动放置估算的落地时间标记"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        collection = getattr(context.scene, "dronemax_landing_target_collection", None)
        return collection is not None and len(collection.all_objects) > 0

    def execute(self, context):
        collection = context.scene.dronemax_landing_target_collection
        if collection is None:
            self.report({"ERROR"}, "请先选择降落集合")
            return {"CANCELLED"}

        empties = [o for o in collection.all_objects if o.type == "EMPTY"]
        if not empties:
            self.report({"ERROR"}, f"集合 '{collection.name}' 中未找到空物体")
            return {"CANCELLED"}

        props = context.scene.dronemax_landing_props
        fps = context.scene.render.fps
        start_frame = props.start_frame

        # 与“编队悬停测试”的下降原理一致：所有空物体以相同的垂直速度同时下降，
        # 相对高度差保持不变（刚体整体下降），直到最低的空物体到达“返航高度”。
        with create_position_evaluator(context=context) as get_positions_of:
            positions = get_positions_of(empties, frame=start_frame)

        lowest_altitude = min(p[2] for p in positions)
        descent_duration = max(0.0, lowest_altitude - props.rth_altitude) / props.velocity_z
        end_frame = round(start_frame + descent_duration * fps)

        for obj, p in zip(empties, positions, strict=True):
            ensure_animation_data_exists_for_object(obj)
            f_curve = ensure_f_curve_exists_for_data_path_and_index(
                obj, data_path="location", index=2
            )
            final_z = p[2] - lowest_altitude + props.rth_altitude
            for frame, value in ((start_frame, p[2]), (end_frame, final_z)):
                keyframe = f_curve.keyframe_points.insert(
                    frame, value, options={"FAST"}
                )
                keyframe.interpolation = "BEZIER"
                keyframe.handle_left_type = "AUTO_CLAMPED"
                keyframe.handle_right_type = "AUTO_CLAMPED"
            f_curve.update()

        if props.scale_down_drones:
            # 除了位置替身，同时把缩放关键帧映射到真实的无人机上
            targets = list(empties)
            drones = Collections.find_drones(create=False)
            if drones is not None:
                targets.extend(drones.objects)
            self._apply_drone_size_keyframes(targets, start_frame, end_frame)

        # 将工程时间范围设为 1 至下降结束后 24 帧，方便预览完整动画。
        context.scene.frame_start = 1
        context.scene.frame_end = end_frame + 24

        highest_final_altitude = (
            max(p[2] for p in positions) - lowest_altitude + props.rth_altitude
        )
        real_landing_time = (
            descent_duration
            + RTL_MODE_SWITCH_DELAY
            + estimate_real_landing_duration(highest_final_altitude)
        )
        place_landed_time_marker(
            context,
            LANDING_GROUP_LANDED_MARKER_MSGID,
            frame=round(start_frame + real_landing_time * fps),
        )

        self.report(
            {"INFO"},
            f"已对集合 '{collection.name}' 中的 {len(empties)} 个空物体执行下降"
            f"（{descent_duration:.1f}s 动画，预计 {real_landing_time:.1f}s 后全部"
            f"落地，见 '{get_localized_marker_name(LANDING_GROUP_LANDED_MARKER_MSGID)}' 标记）",
        )
        return {"FINISHED"}

    def _apply_drone_size_keyframes(self, objects, start_frame: int, end_frame: int):
        """降落期间保持当前尺寸（表演时的 0.5 米），降落结束时将无人机
        缩回 0.15 米。
        """
        for obj in objects:
            current_scale = obj.scale.x
            current_radius = max(obj.dimensions) / 2

            if current_scale > 1e-6 and current_radius > 1e-6:
                # 缩放为 1.0 时的模型半径
                base_radius = current_radius / current_scale
                large_scale = 0.5 / base_radius
                small_scale = 0.15 / base_radius
            else:
                # 空物体没有几何尺寸，按 0.5m -> 0.15m 的比例缩小
                large_scale = current_scale
                small_scale = current_scale * 0.15 / 0.5

            # 降落过程中保持大尺寸
            obj.scale = (large_scale, large_scale, large_scale)
            obj.keyframe_insert(data_path="scale", frame=start_frame)

            # 降落结束时缩回 0.15 米
            obj.scale = (small_scale, small_scale, small_scale)
            obj.keyframe_insert(data_path="scale", frame=end_frame)

            # 保持大尺寸直到最后一帧，再跳变为小尺寸
            if obj.animation_data:
                for fcurve in iter_all_f_curves(obj.animation_data):
                    if fcurve.data_path == "scale":
                        for kp in fcurve.keyframe_points:
                            kp.interpolation = "CONSTANT"


class DroneMaxReadCurrentFrameToPropOperator(Operator):
    """将 Blender 时间轴的当前帧写入到目标属性中。"""

    bl_idname = "dronemax.read_current_frame_to_prop"
    bl_label = "读取当前帧"
    bl_description = "读取时间轴当前帧并写入目标参数，保留手动输入功能"
    bl_options = {"REGISTER", "UNDO"}

    target_prop: StringProperty(
        name="目标属性路径",
        description="要写入当前帧的属性路径，例如 'dronemax_landing_props.start_frame' 或 'sky_mirror_from_frame'",
        default="",
    )

    def execute(self, context):
        scn = context.scene
        parts = self.target_prop.split(".", 1)
        target = scn
        if len(parts) == 2:
            try:
                target = getattr(scn, parts[0])
            except AttributeError:
                self.report({"ERROR"}, f"目标容器 '{parts[0]}' 不存在")
                return {"CANCELLED"}
            prop = parts[1]
        else:
            prop = parts[0]
        if not hasattr(target, prop):
            self.report({"ERROR"}, f"目标属性 '{prop}' 不存在")
            return {"CANCELLED"}
        setattr(target, prop, scn.frame_current)
        self.report({"INFO"}, f"已将当前帧 {scn.frame_current} 写入 {self.target_prop}")
        return {"FINISHED"}


def register_drone_max_scene_properties():
    bpy.types.Scene.dronemax_image_props = bpy.props.PointerProperty(type=DroneMaxImageFormationProperties)
    bpy.types.Scene.dronemax_named_empty_props = bpy.props.PointerProperty(type=DroneMaxNamedEmptyProperties)
    bpy.types.Scene.dronemax_v2e_props = bpy.props.PointerProperty(type=DroneMaxVertsToEmptiesProperties)
    bpy.types.Scene.dronemax_skyc_props = bpy.props.PointerProperty(type=DroneMaxSkycImportProperties)
    bpy.types.Scene.dronemax_ui_state = bpy.props.PointerProperty(type=DroneMaxUIState)
    bpy.types.Scene.dronemax_landing_props = bpy.props.PointerProperty(type=DroneMaxLandingProperties)
    bpy.types.Scene.dronemax_landing_target_collection = bpy.props.PointerProperty(
        name="降落集合",
        type=bpy.types.Collection,
        description="待下降的无人机空物体所在的集合（例如 RTH_1、RTH_2、RTH_3 等分层集合）",
    )


def unregister_drone_max_scene_properties():
    del bpy.types.Scene.dronemax_landing_target_collection
    del bpy.types.Scene.dronemax_landing_props
    del bpy.types.Scene.dronemax_ui_state
    del bpy.types.Scene.dronemax_skyc_props
    del bpy.types.Scene.dronemax_v2e_props
    del bpy.types.Scene.dronemax_named_empty_props
    del bpy.types.Scene.dronemax_image_props
