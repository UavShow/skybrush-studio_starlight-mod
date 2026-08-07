import os

import bpy
from bpy.types import Context, Panel

from sbstudio.plugin.operators import (
    DroneMaxCreateNamedEmptyOperator,
    DroneMaxGenerateEmptiesOperator,
    DroneMaxGeneratePointsOperator,
    DroneMaxLandingDescendOperator,
    DroneMaxReadCurrentFrameToPropOperator,
    DroneMaxSelectImageOperator,
    DroneMaxSkycConvertAndImportOperator,
    DroneMaxVertsToEmptiesOperator,
    QuickIOBatchRenameOperator,
    QuickIOCreateAndBakeProxiesOperator,
    QuickIOExportKeyframesOperator,
    QuickIOImportKeyframesOperator,
    QuickIOPreviewOperator,
)

__all__ = ("DroneMaxAnimationAssistancePanel",)


class DroneMaxAnimationAssistancePanel(Panel):
    bl_idname = "OBJECT_PT_dronemax_animation_assistance_panel"
    bl_label = "DroneMax动画辅助v4.3.6"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DroneMax动画辅助"

    def draw(self, context: Context):
        layout = self.layout
        tr = bpy.app.translations.pgettext_iface
        ui_state = context.scene.dronemax_ui_state

        def draw_section_header(prop_name, label_key):
            box = layout.box()
            row = box.row(align=True)
            expanded = getattr(ui_state, prop_name)
            icon = "TRIA_DOWN" if expanded else "TRIA_RIGHT"
            row.prop(ui_state, prop_name, text="", emboss=False, icon=icon)
            row.label(text=tr(label_key))
            return box if expanded else None

        box = draw_section_header("show_section_1", "1. 参考图片转队形")
        if box:
            props = context.scene.dronemax_image_props
            row = box.row()
            row.prop(props, "image_path", text=tr("参考图片"))
            row.operator(DroneMaxSelectImageOperator.bl_idname, text="", icon="FILEBROWSER")
            box.prop(props, "min_distance", text=tr("最小间距"))
            box.prop(props, "empty_collection_name", text=tr("基础名称"))
            row = box.row()
            row.operator(DroneMaxGeneratePointsOperator.bl_idname, text=tr("生成顶点模型"))
            row.operator(DroneMaxGenerateEmptiesOperator.bl_idname, text=tr("生成空物体纯轴"))

        box = draw_section_header("show_section_2", "2. 以选中物体的位置创建空物体")
        if box:
            props = context.scene.dronemax_named_empty_props
            box.prop(props, "base_name", text=tr("重命名为"))
            box.operator(DroneMaxCreateNamedEmptyOperator.bl_idname, text=tr("确定"))

        box = draw_section_header("show_section_3", "3. 顶点模型转空物体纯轴")
        if box:
            props = context.scene.dronemax_v2e_props
            box.prop(props, "collection_name", text=tr("集合名称"))
            box.prop(props, "empty_size", text=tr("空物体尺寸"))
            box.prop(props, "clear_before", text=tr("生成前清空集合"))
            box.prop(props, "only_selected_objects", text=tr("仅对选中对象"))
            box.operator(DroneMaxVertsToEmptiesOperator.bl_idname, text=tr("顶点模型转空物体纯轴"), icon="EMPTY_AXIS")

        box = draw_section_header("show_section_4", "4. SKYC 导入工具")
        if box:
            props = context.scene.dronemax_skyc_props
            box.prop(props, "skyc_file", text=tr("SKYC 文件"))
            sub = box.box()
            sub.label(text=tr("导入设置"))
            sub.prop(props, "import_fps", text=tr("导入帧率 (FPS)"))
            sub.prop(props, "start_frame", text=tr("起始帧"))
            row = sub.row(align=True)
            row.prop(props, "show_advanced", text=tr("高级选项"))
            if props.show_advanced:
                sub.prop(props, "coord_mode", text=tr("坐标系"))
                sub.prop(props, "global_time_offset", text=tr("手动时间偏移 (秒)"))
                sub2 = sub.box()
                sub2.label(text=tr("精度与调试"))
                sub2.prop(props, "per_frame", text=tr("逐帧导入"))
                if props.per_frame:
                    sub2.prop(props, "keyframe_step", text=tr("关键帧步长"))
                else:
                    sub2.prop(props, "sample_dt", text=tr("CSV 采样间隔 (秒)"))
                sub.prop(props, "use_linear", text=tr("忽略贝塞尔手柄"))
                sub.prop(props, "enable_debug", icon="CONSOLE", text=tr("启用调试信息"))
                sub.prop(props, "save_csv", text=tr("同时导出 CSV"))
            box.operator(DroneMaxSkycConvertAndImportOperator.bl_idname, icon="IMPORT", text=tr("导入.skyc文件"))

        self._draw_quick_io(context, layout, tr)

        box = draw_section_header("show_section_9", "9. 降落设置")
        if box:
            box.prop(
                context.scene,
                "dronemax_landing_target_collection",
                text=tr("降落集合"),
            )
            row = box.row(align=True)
            row.prop(context.scene.dronemax_landing_props, "start_frame")
            op = row.operator(
                DroneMaxReadCurrentFrameToPropOperator.bl_idname,
                icon="TIME",
                text="",
            )
            op.target_prop = "dronemax_landing_props.start_frame"
            row.prop(context.scene.dronemax_landing_props, "velocity_z")
            row.prop(context.scene.dronemax_landing_props, "rth_altitude")
            row.prop(context.scene.dronemax_landing_props, "ramp_duration")
            box.prop(
                context.scene.dronemax_landing_props,
                "scale_down_drones",
                text=tr("无人机缩小"),
            )
            box.operator(
                DroneMaxLandingDescendOperator.bl_idname,
                icon="TRIA_DOWN_BAR",
                text=tr("开始降落"),
            )

    def _draw_quick_io(self, context: Context, layout, tr):
        scn = context.scene

        def fold_header(parent, prop_name, label):
            box = parent.box()
            header = box.row(align=True)
            expanded = getattr(scn, prop_name)
            header.prop(
                scn,
                prop_name,
                text="",
                emboss=False,
                icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            )
            header.label(text=tr(label))
            return box if expanded else None

        # 5. 创建替身并镜像烘焙
        box = fold_header(layout, "ui_fold_sky", "5. 创建替身并镜像烘焙")
        if box:
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(scn, "sky_drones_collection", text=tr("无人机"))
            row.prop(scn, "sky_proxies_collection", text=tr("替身集合名"))
            row = col.row(align=True)
            row.prop(scn, "sky_mirror_from_frame", text=tr("镜像起始帧"))
            op = row.operator(
                DroneMaxReadCurrentFrameToPropOperator.bl_idname,
                icon="TIME",
                text="",
            )
            op.target_prop = "sky_mirror_from_frame"
            row.prop(scn, "sky_mirror_to_frame", text=tr("镜像结束帧"))
            op = row.operator(
                DroneMaxReadCurrentFrameToPropOperator.bl_idname,
                icon="TIME",
                text="",
            )
            op.target_prop = "sky_mirror_to_frame"
            row.prop(scn, "sky_mirror_step", text=tr("步长(帧)"))
            col.separator()
            col.prop(scn, "sky_mirror_adaptive", text=tr("自适应镜像采样"))
            if scn.sky_mirror_adaptive:
                row = col.row(align=True)
                row.prop(scn, "sky_mirror_max_gap", text=tr("自适应最大位移(米)"))
                row.prop(scn, "sky_mirror_max_angle", text=tr("自适应最大转角(度)"))
            col.separator()
            sub = col.box()
            sub.label(text=tr("替身类型（创建阶段）"))
            sub.prop(scn, "sky_proxy_type", text=tr("类型"))
            if scn.sky_proxy_type == "EMPTY":
                sub.prop(scn, "sky_proxy_empty_size", text=tr("空物体显示尺寸"))
            else:
                row = sub.row(align=True)
                row.prop(scn, "sky_proxy_ico_radius", text=tr("菱角球半径"))
                row.prop(scn, "sky_proxy_ico_subdiv", text=tr("细分"))
            col.separator()
            col.operator(
                QuickIOCreateAndBakeProxiesOperator.bl_idname,
                icon="MOD_MIRROR",
                text=tr("创建替身并镜像到返航开始帧（烘焙）"),
            )
            col.label(text=tr("提示：将当前帧视为返航开始帧（默认），镜像结束帧可留空(=当前)"))

        # 6. 导出关键帧设置
        box = fold_header(layout, "ui_fold_export", "6. 导出关键帧设置")
        if box:
            col = box.column(align=True)
            col.prop(scn, "brt_target_collection", text=tr("目标集合"))
            col.prop(scn, "brt_use_selection", text=tr("仅导出所选"))
            col.prop(scn, "brt_export_source", text=tr("导出源"))
            row = col.row(align=True)
            row.prop(scn, "brt_export_loc", text=tr("位置"), toggle=True)
            row.prop(scn, "brt_export_rot", text=tr("旋转"), toggle=True)
            row.prop(scn, "brt_export_scl", text=tr("缩放"), toggle=True)
            col.prop(scn, "brt_skip_no_kf", text=tr("跳过无关键帧对象"))
            blend_name = (
                os.path.splitext(os.path.basename(bpy.data.filepath))[0]
                if bpy.data.filepath
                else tr("未保存")
            )
            info = col.box()
            info.label(text=tr("导出文件：") + f"{blend_name}.brta")
            from_f = scn.sky_mirror_from_frame if scn.sky_mirror_from_frame > 0 else 1
            to_f = scn.sky_mirror_to_frame if scn.sky_mirror_to_frame > 0 else scn.frame_current
            info.label(text=tr("镜像帧范围：") + f"{from_f} - {to_f}")
            row = col.row(align=True)
            row.operator(QuickIOPreviewOperator.bl_idname, icon="VIEWZOOM", text=tr("预览（对象与帧并集）"))
            row.operator(QuickIOExportKeyframesOperator.bl_idname, icon="EXPORT", text=tr("导出关键帧 (.brta)"))

        # 7. 导入关键帧设置
        box = fold_header(layout, "ui_fold_import", "7. 导入关键帧设置")
        if box:
            col = box.column(align=True)
            col.prop(scn, "brt_import_path", text=tr("导入路径"))
            col.separator()
            sub = col.box()
            sub.label(text=tr("导入对象类型"))
            sub.prop(scn, "brt_import_proxy_type", text=tr("类型"))
            if scn.brt_import_proxy_type == "EMPTY":
                sub.prop(scn, "brt_import_empty_size", text=tr("空物体显示尺寸"))
            else:
                row = sub.row(align=True)
                row.prop(scn, "brt_import_ico_radius", text=tr("菱角球半径"))
                row.prop(scn, "brt_import_ico_subdiv", text=tr("细分"))
            col.separator()
            col.operator(QuickIOImportKeyframesOperator.bl_idname, icon="IMPORT", text=tr("导入关键帧 (.brta)"))

        # 8. 选中物体批量重命名
        box = fold_header(layout, "ui_fold_tools", "8. 选中物体批量重命名")
        if box:
            col = box.column(align=True)
            col.prop(scn, "brt_batch_base_name", text=tr("基础名称（可留空）"))
            op = col.operator(
                QuickIOBatchRenameOperator.bl_idname,
                icon="OUTLINER_DATA_EMPTY",
                text=tr("批量重命名（使用上方名称/留空为数字）"),
            )
            op.base_name = scn.brt_batch_base_name
