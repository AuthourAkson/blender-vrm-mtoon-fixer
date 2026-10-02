# -*- coding: utf-8 -*-
"""
VRM MToon Material Fixer
=======================

Blender 一键修复: 把 MMD/PMX 模型的 mmd_shader / MBTs-NG 卡渲材质转换为 VRM MToon1,
并导出 VRM。适合 Blender 3.6 / 4.x。

使用方式:
     3D 视图右侧 N 面板 -> "VRM Fixer" 标签页:
        1. 确认输出路径
        2. 先点「转换材质」按钮(只改当前场景, 不导出)
        3. 再点「一键修复并导出 VRM」按钮(转换 + 导出)
"""
import importlib
import math
import os
import traceback
import unicodedata
import bmesh

import bpy
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel

bl_info = {
    "name": "VRM MToon Material Fixer",
    "author": "AI assistant (custom tool)",
    "version": (1, 5, 0),
    "blender": (3, 6, 0),
    "location": "3D Viewport > Sidebar > VRM Fixer",
    "description": "把 mmd_shader / MMDShaderDev / MBTs-NG 卡渲材质转换为 VRM MToon1 并导出 VRM",
    "category": "Import-Export",
}

ADDON_MODULE_CANDIDATES = [
    "VRM_Addon_for_Blender-release",
    "VRM_Addon_for_Blender",
    "io_scene_vrm",
]


VRM_FIXER_MODE_ITEMS = [
    ("SIMPLE", "直接导出(基础贴图)", "不映射 MBTs 参数, 只转 MToon1 并接回 mmd_base_tex, 像最初插件一样"),
    ("MBTS_MAP", "MBTs参数映射", "把 MBTs-R2Y 的阴影/参数映射到 MToon1, 保留一定卡渲感"),
    ("BAKE", "MBTs烘焙导出(Cycles)", "先把 MBTs 卡渲材质烘成贴图, 再导出 VRM; 最接近 Blender 渲染效果"),
]


VRM1_EXPRESSION_SHAPE_KEY_CANDIDATES = {
    "aa": ["あ", "aa", "a"],
    "ih": ["い", "ih", "i"],
    "ou": ["う", "ou", "u"],
    "ee": ["え", "ee", "e"],
    "oh": ["お", "oh", "o"],
    "blink": ["まばたき", "blink", "閉じる"],
    "blink_left": ["ウィンク", "ウィンク２", "wink", "blinkleft", "blink_left"],
    "blink_right": ["ウィンク右", "ウィンク２右", "winkright", "blinkright", "blink_right"],
    "happy": ["にこり", "笑い", "happy", "smile"],
    "angry": ["怒り", "angry", "怒"],
    "sad": ["悲しい", "sad", "困る"],
    "relaxed": ["笑い", "relaxed", "にこり"],
    "neutral": ["真面目", "neutral", "まじめ"],
    "surprised": ["びっくり", "surprised", "驚き"],
}


def _normalize_shape_key_name(name):
    try:
        return unicodedata.normalize("NFKC", name or "").strip().lower().replace(" ", "").replace("_", "")
    except Exception:
        return (name or "").strip().lower()


def auto_bind_vrm1_expressions(context):
    """自动把 VRM1 表情预设绑定到当前模型的形状键。返回 (是否成功, 信息列表)。"""
    ext_mod = get_vrm_extension_module()
    if not ext_mod:
        return False, ["找不到 VRM Addon, 请先启用 VRM_Addon_for_Blender"]

    armature_obj, body_obj = find_model_objects()
    if not armature_obj or not body_obj:
        return False, ["当前场景没有找到骨骼或网格体"]

    get_armature_extension = ext_mod.get_armature_extension
    ext = get_armature_extension(armature_obj.data)
    if not ext.is_vrm1():
        return False, ["当前模型不是 VRM1, 无需绑定 VRM1 表情"]

    # 收集所有网格物体的形状键名
    shape_key_to_mesh = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data or not obj.data.shape_keys:
            continue
        for kb in obj.data.shape_keys.key_blocks:
            if kb.name not in shape_key_to_mesh:
                shape_key_to_mesh[kb.name] = obj.name

    if not shape_key_to_mesh:
        return False, ["当前模型没有形状键(BlendShape)"]

    preset = ext.vrm1.expressions.preset
    bound = 0
    infos = []

    for preset_name, candidates in VRM1_EXPRESSION_SHAPE_KEY_CANDIDATES.items():
        expr = getattr(preset, preset_name, None)
        if expr is None:
            continue

        # 精确匹配优先
        selected_name = None
        for cand in candidates:
            cand_n = _normalize_shape_key_name(cand)
            for shape_name in shape_key_to_mesh:
                if _normalize_shape_key_name(shape_name) == cand_n:
                    selected_name = shape_name
                    break
            if selected_name:
                break

        # 包含匹配其次
        if selected_name is None:
            for cand in candidates:
                cand_n = _normalize_shape_key_name(cand)
                for shape_name in shape_key_to_mesh:
                    sn = _normalize_shape_key_name(shape_name)
                    if cand_n and (cand_n in sn or sn in cand_n):
                        selected_name = shape_name
                        break
                if selected_name:
                    break

        if selected_name is None:
            infos.append(f"{preset_name}: 未找到形状键, 跳过")
            continue

        expr.morph_target_binds.clear()
        bind = expr.morph_target_binds.add()
        bind.node.mesh_object_name = shape_key_to_mesh[selected_name]
        bind.index = selected_name
        bind.weight = 1.0
        bound += 1
        infos.append(f"{preset_name} -> {selected_name}")

    return bound > 0, infos



def get_vrm_extension_module():
    for module_name in ADDON_MODULE_CANDIDATES:
        try:
            return importlib.import_module(f"{module_name}.editor.extension")
        except Exception:
            continue
    return None


def find_model_objects():
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    meshes = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.data and obj.data.materials
    ]
    if not armatures or not meshes:
        return None, None
    armature_obj = armatures[0]
    body_obj = max(meshes, key=lambda o: len(o.data.materials))
    return armature_obj, body_obj


def collect_legacy_material_values(mat):
    """读取 mmd_shader 或 MBTs 卡渲节点的旧参数。返回 dict。"""
    info = {
        "found": False,
        "kind": None,
        "base_img": None,
        "alpha": 1.0,
        "double_sided": 0.0,
        "mbts": {},
    }
    if not (mat.use_nodes and mat.node_tree):
        return info

    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.name == "mmd_base_tex":
            info["base_img"] = node.image
        elif node.type == "GROUP" and node.node_tree:
            tree_name = node.node_tree.name or ""
            is_mmd = (
                node.name == "mmd_shader"
                or tree_name.startswith("MMDShaderDev")
                or tree_name.startswith("MMDShader")
            )
            is_mbts = tree_name.startswith("MBTs") or (tree_name == "群组" and "MColor" in node.inputs)
            if is_mmd:
                info["found"] = True
                info["kind"] = "mmd"
                try:
                    if "Alpha" in node.inputs:
                        info["alpha"] = node.inputs["Alpha"].default_value
                except Exception:
                    pass
                try:
                    if "Double Sided" in node.inputs:
                        info["double_sided"] = node.inputs["Double Sided"].default_value
                except Exception:
                    pass
            elif is_mbts:
                info["found"] = True
                info["kind"] = "mbts"
                info["alpha"] = 1.0
                info["base_alpha_linked"] = False
                for inp in node.inputs:
                    if inp.name == "Alpha":
                        try:
                            info["alpha"] = inp.default_value
                        except Exception:
                            pass
                    elif inp.name == "Base Alpha" and inp.is_linked:
                        info["base_alpha_linked"] = True
                    elif not inp.is_linked and hasattr(inp, "default_value"):
                        val = inp.default_value
                        if hasattr(val, "__len__"):
                            info["mbts"][inp.name] = tuple(val)
                        else:
                            info["mbts"][inp.name] = float(val)
    return info


def _to_rgb3(value, default=(1.0, 1.0, 1.0)):
    if value is None:
        return list(default)
    try:
        v = list(value)
        if len(v) >= 3:
            return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        pass
    return list(default)


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def set_vrm1_meta(ext_mod, armature_obj, fallback_name):
    try:
        get_armature_extension = ext_mod.get_armature_extension
        ext = get_armature_extension(armature_obj.data)
        if ext.is_vrm0():
            return
        meta = ext.vrm1.meta
        if not getattr(meta, "vrm_name", ""):
            meta.vrm_name = fallback_name
        if not getattr(meta, "version", ""):
            meta.version = "1.0"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 骨骼朝向规范化(Unity / VRM 应用兼容)
# ---------------------------------------------------------------------------
# 背景: MMD 完整装备骨(センター / グルーブ / 腰 / 上半身1 / 上半身2 / 肩P / 肩C / 捩骨)
# 里, 人形骨骼的"直接父级"常是这种 helper 骨骼, 而且它们的静止朝向不一定竖直。
# 于是「人形骨骼相对父级的静止旋转」可能很大(实测 lothe 的 上半身 相对 腰 偏 42.72°)。
#
# 一些 Unity 侧 VRM 应用(例如 MATE ENGINE 的 AvatarMouseTracking.DoSpine/DoHead)
# 假定这个局部初始旋转≈0, 而且会直接覆盖它 —— 结果躯干连带头部整体前倾("头一直朝下")。
#
# 这里把 helper 父骨骼的静止朝向对齐到它的人形子骨骼上, 让局部旋转≈0。
# 只动 helper(非人形)骨骼的朝向: 不动骨骼头部位置、不动人形骨骼自身朝向;
# 静止姿势下网格形变矩阵恒为单位阵, 所以模型外观与 Unity 的人形重定向都不受影响。


def get_humanoid_bone_map(armature_obj):
    """返回 {人形骨骼字段名(hips/spine/...): Blender 骨骼名}"""
    ext_mod = get_vrm_extension_module()
    if not ext_mod:
        return {}
    try:
        ext = ext_mod.get_armature_extension(armature_obj.data)
        if ext.is_vrm0():
            out = {}
            for entry in ext.vrm0.humanoid.human_bones:
                node = getattr(entry, "node", None)
                bone_name = getattr(node, "bone_name", "")
                field = getattr(entry, "bone", "")
                if field and bone_name:
                    out[field] = bone_name
            return out
        out = {}
        human_bones = ext.vrm1.humanoid.human_bones
        for field in dir(human_bones):
            if field.startswith("_"):
                continue
            node = getattr(getattr(human_bones, field, None), "node", None)
            bone_name = getattr(node, "bone_name", "")
            if bone_name:
                out[field] = bone_name
        return out
    except Exception:
        traceback.print_exc()
        return {}


def _relative_rest_angle(armature_obj, bone_name, parent_name):
    """bone 相对 parent 的静止旋转角度(度)。应用覆盖该骨骼局部旋转时会跑偏这么多。"""
    bones = armature_obj.data.bones
    if bone_name not in bones or parent_name not in bones:
        return None
    bone_m = bones[bone_name].matrix_local
    parent_m = bones[parent_name].matrix_local
    rel = parent_m.inverted() @ bone_m
    return math.degrees(rel.to_quaternion().angle)


def scan_helper_frame_issues(armature_obj, tolerance=1.0):
    """找出父级不是人形骨骼的人形骨骼, 以及其局部静止旋转偏差。"""
    humanoid_map = get_humanoid_bone_map(armature_obj)
    if not humanoid_map:
        return [], humanoid_map
    humanoid_bone_names = set(humanoid_map.values())
    bones = armature_obj.data.bones
    issues = []
    for field, bone_name in sorted(humanoid_map.items()):
        bone = bones.get(bone_name)
        if bone is None or bone.parent is None:
            continue
        parent = bone.parent
        if parent.name in humanoid_bone_names:
            continue
        angle = _relative_rest_angle(armature_obj, bone_name, parent.name)
        if angle is None or angle <= tolerance:
            continue
        issues.append({
            "humanoid": field,
            "bone": bone_name,
            "parent": parent.name,
            "angle": angle,
        })
    return issues, humanoid_map


def normalize_helper_frames(context, tolerance=1.0):
    """把 helper 父骨骼的静止朝向对齐到其人形子骨骼。返回 (修改数, 日志)。"""
    armature_obj, _body_obj = find_model_objects()
    if armature_obj is None:
        return 0, ["找不到骨骼对象"]
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    issues, _ = scan_helper_frame_issues(armature_obj, tolerance=tolerance)
    if not issues:
        return 0, ["骨骼朝向已规范(人形骨骼的父级都是人形骨骼), 无需处理"]

    infos = [f"  {i['humanoid']:<16} {i['bone']} <- {i['parent']} "
             f"静止偏差 {i['angle']:6.2f}°" for i in issues]

    prev_active = context.view_layer.objects.active
    changed = 0
    try:
        bpy.ops.object.select_all(action="DESELECT")
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature_obj.data.edit_bones
        for item in issues:
            parent_eb = edit_bones.get(item["parent"])
            child_eb = edit_bones.get(item["bone"])
            if parent_eb is None or child_eb is None:
                continue
            child_m = child_eb.matrix.to_3x3()
            child_dir = child_m.col[1].normalized()
            child_roll_ref = child_m.col[2].normalized()
            head = parent_eb.head.copy()
            length = parent_eb.length
            parent_eb.tail = head + child_dir * length
            parent_eb.align_roll(child_roll_ref)
            changed += 1
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as exc:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        infos.append(f"  规范化失败: {exc}")
        traceback.print_exc()
    finally:
        try:
            context.view_layer.objects.active = prev_active
        except Exception:
            pass

    for item in issues:
        left = _relative_rest_angle(armature_obj, item["bone"], item["parent"])
        if left is not None:
            infos.append(f"  {item['bone']} 相对 {item['parent']}: "
                         f"{item['angle']:.2f}° -> {left:.2f}°")
    return changed, infos


# ---------------------------------------------------------------------------
# 烘焙 MMD 付与(约束驱动)骨骼 -> 真实父子层级
# ---------------------------------------------------------------------------
# MMD 模型里大量使用「付与」(bone inherit) 与 IK: 例如腿部皮肤实际绑在
# 足D.L / ひざD.L 上, 而它们是靠 Blender 约束 (TRANSFORM) 跟随 足.L / ひざ.L 的。
#
# VRM/glTF 格式**没有约束**, 导出去之后这些骨骼就永远停在绑定姿势:
# 表现就是「腿部/下半身绷直不动」, 而在 Blender 里怎么看都正常。
#
# 修法: 把"约束驱动"改成"真实父子关系"—— 让 足D.L 直接挂在 足.L 下面,
# 并删掉那条约束(否则 Blender 里会双重变换)。静止世界坐标保持不变,
# 所以模型外观不变; 但导出后 VRM 里的骨骼会跟着人形骨骼一起动。

DRIVER_CONSTRAINT_TYPES = (
    "TRANSFORM",
    "COPY_TRANSFORMS",
    "COPY_ROTATION",
    "COPY_LOCATION",
    "CHILD_OF",
)


def _driver_target(pbone):
    """返回该骨骼上第一条"驱动型"约束的目标骨骼名。"""
    for c in pbone.constraints:
        if c.type in DRIVER_CONSTRAINT_TYPES:
            name = getattr(c, "subtarget", "") or ""
            if name:
                return name, c
    return None, None


def _resolve_inherit_driver(armature_obj, bone_name, seen=None):
    """顺着约束链找到真正驱动 bone_name 的骨骼。"""
    seen = seen or set()
    if bone_name in seen:
        return None
    seen.add(bone_name)
    pbone = armature_obj.pose.bones.get(bone_name)
    if pbone is None:
        return None
    target, _ = _driver_target(pbone)
    if not target:
        return bone_name
    if target not in armature_obj.data.bones:
        return bone_name
    return _resolve_inherit_driver(armature_obj, target, seen) or bone_name


def _nearest_humanoid_ancestor(bones, bone_name, humanoid_names):
    node = bones.get(bone_name)
    while node is not None:
        if node.name in humanoid_names:
            return node.name
        node = node.parent
    return None


def _is_descendant(bones, maybe_child, ancestor):
    node = bones.get(maybe_child)
    while node is not None:
        if node.name == ancestor:
            return True
        node = node.parent
    return False


def _subtree_has_humanoid(bones, root_name, humanoid_names):
    """子树里是否含人形骨骼。含的话不能重挂, 否则会破坏 VRM 人形层级。"""
    stack = [bones.get(root_name)]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if node.name in humanoid_names:
            return True
        for child in node.children:
            stack.append(child)
    return False


def scan_inherit_bones(armature_obj):
    """找出所有"靠约束跟随人形骨骼"的骨骼, 返回计划列表。"""
    humanoid_map = get_humanoid_bone_map(armature_obj)
    humanoid_names = set(humanoid_map.values())
    bones = armature_obj.data.bones
    plan = []
    for pb in armature_obj.pose.bones:
        target, constraint = _driver_target(pb)
        if not target:
            continue
        driver = _resolve_inherit_driver(armature_obj, pb.name)
        if not driver:
            continue
        humanoid = _nearest_humanoid_ancestor(bones, driver, humanoid_names)
        if not humanoid or humanoid == pb.name:
            continue
        if _is_descendant(bones, humanoid, pb.name):
            continue  # 会形成环
        if pb.bone.parent is not None and pb.bone.parent.name == humanoid:
            continue  # 已经是对的了
        if pb.name.startswith("_"):
            continue  # mmd_tools 内部骨骼, 不导出, 跳过
        if _subtree_has_humanoid(bones, pb.name, humanoid_names):
            continue  # 子树含人形骨骼(如 肩C.L -> 腕.L), 重挂会破坏 VRM 人形层级
        plan.append({
            "bone": pb.name,
            "new_parent": humanoid,
            "driver": driver,
            "constraint": constraint.name if constraint else "",
        })
    return plan


def bake_mmd_inherit_bones(context):
    """把付与驱动的骨骼重挂到人形骨骼下, 并删除对应约束。返回 (修改数, 日志)。"""
    armature_obj, _body_obj = find_model_objects()
    if armature_obj is None:
        return 0, ["找不到骨骼对象"]
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    plan = scan_inherit_bones(armature_obj)
    if not plan:
        return 0, ["没有发现靠约束跟随的骨骼, 无需烘焙"]

    infos = [f"  {i['bone']} <- {i['new_parent']} (原跟随 {i['driver']}, 约束 {i['constraint']})"
             for i in plan]

    prev_active = context.view_layer.objects.active
    changed = 0
    try:
        bpy.ops.object.select_all(action="DESELECT")
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature_obj.data.edit_bones
        for item in plan:
            cb = edit_bones.get(item["bone"])
            nb = edit_bones.get(item["new_parent"])
            if cb is None or nb is None:
                continue
            head = cb.head.copy()
            tail = cb.tail.copy()
            roll = cb.roll
            cb.parent = nb
            cb.use_connect = False
            cb.head = head
            cb.tail = tail
            cb.roll = roll
            changed += 1
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as exc:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        infos.append(f"  烘焙失败: {exc}")
        traceback.print_exc()
        return 0, infos
    finally:
        try:
            context.view_layer.objects.active = prev_active
        except Exception:
            pass

    # 删掉驱动约束, 避免 Blender 里双重变换
    removed = 0
    for item in plan:
        pb = armature_obj.pose.bones.get(item["bone"])
        if pb is None:
            continue
        for c in list(pb.constraints):
            if c.type in DRIVER_CONSTRAINT_TYPES and (getattr(c, "subtarget", "") or ""):
                pb.constraints.remove(c)
                removed += 1
    infos.append(f"  重挂 {changed} 根骨骼, 删除 {removed} 条驱动约束")
    return changed, infos


# ---------------------------------------------------------------------------
# 从 MMD 刚体自动生成 VRM 弹簧骨
# ---------------------------------------------------------------------------
# MMD 里头发 / 披风 / 尾巴 / 鞋带这些是靠物理刚体驱动的, 但 VRM 没有 MMD 物理,
# 需要写成 VRMC_springBone(弹簧骨) 才会在 Unity / MATE ENGINE 里摆动。
#
# 做法:
#   1. 收集 mmd_tools 的刚体数据(obj["mmd_rigid"]):
#        type 1 = 静态(只做碰撞体)  type 2/3 = 动态(需要弹簧骨)
#   2. 动态刚体的骨骼按层级连成链; 遇到分叉就切开, 保证每根骨骼只属于一条弹簧
#   3. 静态刚体 -> VRM 球形碰撞体(VRM 1.0 的弹簧骨碰撞体只有球),
#      按 MMD 的碰撞组/掩码分配给对应的弹簧
#   4. 半径取刚体网格包围盒(MMD 刚体对象本身就是按尺寸生成的网格)
#
# 参数: MMD 刚体被转换工具精简过, 往往没有质量/阻尼/重力数据,
# 所以按部位给经验值, 并且**沿链逐节递减硬度**(根硬、梢软), 这样长链(尾巴/长发)
# 会一节一节地弯, 而不是整根当刚体甩。

# (关键字, 根硬度, 梢硬度, 阻尼, 重力, 命中半径缩放, 单链最大关节数)
SPRING_PROFILES = (
    ("tail", 1.0, 0.25, 0.60, 0.0, 0.6, 24),
    ("hair", 1.2, 0.50, 0.40, 0.0, 1.0, 12),
    ("hat_", 1.2, 0.70, 0.40, 0.0, 1.0, 8),
    ("ear_", 1.2, 0.70, 0.40, 0.0, 1.0, 8),
    ("cloak", 1.0, 0.40, 0.50, 0.0, 1.0, 12),
    ("cape", 1.0, 0.40, 0.50, 0.0, 1.0, 12),
    ("sleeve", 1.0, 0.40, 0.50, 0.0, 1.0, 12),
    ("skirt", 1.0, 0.40, 0.50, 0.0, 1.0, 12),
    ("shoelace", 1.2, 0.80, 0.50, 0.0, 1.0, 8),
    ("paw_", 0.8, 0.40, 0.50, 0.0, 1.0, 8),
    ("gs_", 1.0, 0.40, 0.50, 0.0, 1.0, 12),
)
SPRING_PROFILE_DEFAULT = (1.0, 0.50, 0.45, 0.0, 1.0, 12)
SPRING_GRAVITY_DIR = (0.0, -1.0, 0.0)
SPRING_COLLIDER_MIN = 0.01
SPRING_COLLIDER_MAX = 0.5
SPRING_HIT_MIN = 0.005
SPRING_HIT_MAX = 0.1


def spring_profile(root_bone_name):
    """按链根骨骼名挑参数。"""
    lowered = (root_bone_name or "").lower()
    for keywords, root_s, tip_s, drag, grav, hit_scale, max_j in SPRING_PROFILES:
        for kw in keywords.split("|"):
            if kw in lowered:
                return root_s, tip_s, drag, grav, hit_scale, max_j
    return SPRING_PROFILE_DEFAULT


def collect_mmd_rigid_bodies():
    """收集 mmd_tools 刚体 -> {骨骼名: {...}}。同名取半径最大的那个。"""
    by_bone = {}
    for obj in bpy.data.objects:
        if "mmd_rigid" not in obj.keys():
            continue
        rb = obj["mmd_rigid"]
        try:
            bone_name = rb.get("bone", "") or ""
        except Exception:
            bone_name = ""
        if not bone_name:
            continue
        radius = 0.0
        try:
            if obj.type == "MESH" and obj.data and len(obj.data.vertices):
                xs = [float(v[0]) for v in obj.bound_box]
                ys = [float(v[1]) for v in obj.bound_box]
                zs = [float(v[2]) for v in obj.bound_box]
                radius = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) / 2.0
        except Exception:
            radius = 0.0
        try:
            mask = [bool(b) for b in rb["collision_group_mask"]]
        except Exception:
            mask = []
        info = {
            "type": int(rb.get("type", 1)),
            "shape": int(rb.get("shape", 0)),
            "radius": radius,
            "group": int(rb.get("collision_group_number", 0)),
            "mask": mask,
        }
        prev = by_bone.get(bone_name)
        if prev is None or radius > prev["radius"]:
            by_bone[bone_name] = info
    return by_bone


def build_spring_chains(armature_obj, dynamic_bones):
    """动态刚体骨骼按层级连成链; 分叉处切开, 保证每根骨骼只属于一条弹簧。"""
    bones = armature_obj.data.bones
    children = {}
    for name in dynamic_bones:
        b = bones.get(name)
        if b is None:
            continue
        children[name] = [c.name for c in b.children if c.name in dynamic_bones]
    roots = []
    for name in dynamic_bones:
        b = bones.get(name)
        if b is None:
            continue
        if b.parent is None or b.parent.name not in dynamic_bones:
            roots.append(name)

    chains = []

    def walk(name, chain):
        chain = chain + [name]
        kids = children.get(name, [])
        if len(kids) == 1:
            walk(kids[0], chain)
            return
        chains.append(chain)
        for k in kids:
            walk(k, [])

    for r in sorted(roots):
        walk(r, [])
    return [c for c in chains if len(c) >= 2]


def generate_spring_bones(context):
    """生成 VRMC_springBone。返回 (弹簧数, 日志)。"""
    armature_obj, _body_obj = find_model_objects()
    if armature_obj is None:
        return 0, ["找不到骨骼对象"]
    ext_mod = get_vrm_extension_module()
    if ext_mod is None:
        return 0, ["找不到 VRM Addon"]

    rigid = collect_mmd_rigid_bodies()
    if not rigid:
        return 0, ["没有找到 MMD 刚体数据(mmd_rigid), 跳过弹簧骨生成"]

    static = {b: i for b, i in rigid.items() if i["type"] == 1}
    dynamic = {b: i for b, i in rigid.items() if i["type"] != 1}
    chains = build_spring_chains(armature_obj, set(dynamic))
    try:
        ext = ext_mod.get_armature_extension(armature_obj.data)
        sb = ext.spring_bone1
    except Exception as exc:
        return 0, [f"VRM 弹簧骨扩展不可用: {exc}"]

    sb.springs.clear()
    sb.collider_groups.clear()
    sb.colliders.clear()

    infos = [f"  刚体骨骼 {len(rigid)} 根 (静态 {len(static)} / 动态 {len(dynamic)}), "
             f"切出 {len(chains)} 条链"]

    # ---- 静态刚体 -> 球形碰撞体 + 碰撞组 ----
    collider_of_bone = {}
    for bone_name, info in sorted(static.items()):
        if bone_name not in armature_obj.data.bones:
            continue
        radius = info["radius"] or 0.05
        c = sb.colliders.add()
        try:
            c.node.bone_name = bone_name
            c.offset = Vector((0.0, 0.0, 0.0))
            c.radius = float(min(max(radius, SPRING_COLLIDER_MIN), SPRING_COLLIDER_MAX))
        except Exception:
            continue
        collider_of_bone[bone_name] = c

    group_of_bone = {}
    for bone_name, collider in collider_of_bone.items():
        g = sb.collider_groups.add()
        try:
            g.vrm_name = ("CG_" + bone_name)[:60]
            g.colliders.add().collider = collider
        except Exception:
            pass
        group_of_bone[bone_name] = g

    # ---- 动态骨骼链 -> 弹簧 ----
    made = 0
    for chain in chains:
        root_s, tip_s, drag, gravity, hit_scale, max_joints = spring_profile(chain[0])
        joints = chain[:max_joints]
        sp = sb.springs.add()
        try:
            sp.vrm_name = ("SP_" + chain[0])[:60]
        except Exception:
            pass
        span = max(1, len(joints) - 1)
        for idx, bone_name in enumerate(joints):
            info = dynamic[bone_name]
            j = sp.joints.add()
            try:
                j.node.bone_name = bone_name
            except Exception:
                continue
            t = idx / span
            radius = (info["radius"] or 0.02) * 0.5 * hit_scale
            j.hit_radius = float(min(max(radius, SPRING_HIT_MIN), SPRING_HIT_MAX))
            j.stiffness = float(root_s + (tip_s - root_s) * t)
            j.drag_force = float(drag)
            j.gravity_power = float(gravity)
            j.gravity_dir = Vector(SPRING_GRAVITY_DIR)
        mask = dynamic[chain[0]]["mask"]
        for bone_name, group in group_of_bone.items():
            gnum = static[bone_name]["group"]
            if mask and 0 <= gnum < len(mask) and not mask[gnum]:
                continue
            try:
                sp.collider_groups.add().collider_group = group
            except Exception:
                pass
        made += 1

    infos.append(f"  已写入 springs={len(sb.springs)} 碰撞体={len(sb.colliders)} "
                 f"碰撞组={len(sb.collider_groups)} 关节={sum(len(s.joints) for s in sb.springs)}")
    for chain in chains[:8]:
        r_s, t_s, _d, _g, _h, _m = spring_profile(chain[0])
        infos.append(f"    {chain[0]:<30} {len(chain):2d} 节  硬度 {r_s:.2f}->{t_s:.2f}")
    return made, infos


def maybe_normalize_rig(context):
    """按场景开关执行骨骼朝向规范化, 返回日志行。"""
    lines = []
    try:
        if not bool(getattr(context.scene, "vrm_fixer_normalize_rig", True)):
            return lines
    except Exception:
        return lines
    try:
        if bool(getattr(context.scene, "vrm_fixer_bake_inherit", True)):
            baked, bake_report = bake_mmd_inherit_bones(context)
            lines.append(f"MMD 付与骨烘焙: 处理 {baked} 根骨骼")
            lines.extend(bake_report)
    except Exception:
        traceback.print_exc()
        lines.append("MMD 付与骨烘焙: 失败, 详见控制台")

    changed, report = normalize_helper_frames(context)
    lines.append(f"骨骼朝向规范化: 处理 {changed} 根 helper 骨骼")
    lines.extend(report)

    try:
        if bool(getattr(context.scene, "vrm_fixer_gen_spring_bones", True)):
            made, spring_report = generate_spring_bones(context)
            lines.append(f"生成 VRM 弹簧骨: {made} 条弹簧")
            lines.extend(spring_report)
    except Exception:
        traceback.print_exc()
        lines.append("生成 VRM 弹簧骨: 失败, 详见控制台")
    return lines


def bake_mbts_and_export(context, output_path):
    """B 方案: 用 Cycles 把 MBTs 卡渲材质烘成贴图, 再转换 MToon 并导出 VRM。"""
    ext_mod = get_vrm_extension_module()
    if not ext_mod:
        return False, ["找不到 VRM Addon, 请先在插件面板启用 VRM_Addon_for_Blender"]

    armature_obj, body_obj = find_model_objects()
    if not armature_obj or not body_obj:
        return False, ["当前场景没有找到骨骼或带材质槽的网格体"]

    get_material_extension = ext_mod.get_material_extension
    get_armature_extension = ext_mod.get_armature_extension

    # 记录每个材质槽的原始信息(贴图、alpha 等)
    slot_infos = []
    groups = {}
    for idx, slot in enumerate(body_obj.material_slots):
        mat = slot.material
        info = collect_legacy_material_values(mat) if mat else None
        slot_infos.append(info)
        if info and info["base_img"]:
            key = info["base_img"].name
            groups.setdefault(key, {"image": info["base_img"], "indices": []})
            groups[key]["indices"].append(idx)

    if not groups:
        return False, ["没有找到带 mmd_base_tex 的材质, 不需要烘焙"]

    scene = context.scene
    old_engine = scene.render.engine
    old_samples = scene.cycles.samples if hasattr(scene, "cycles") else 8
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8

    baked_images = {}
    bake_objs = []

    # 暂时隐藏原模型和场景中的其它对象, 只保留烘焙临时对象
    for obj in bpy.data.objects:
        obj.hide_set(True)
        obj.hide_render = True

    try:
        for key, group in groups.items():
            indices = set(group["indices"])
            rep_mat = None
            for idx in group["indices"]:
                if body_obj.material_slots[idx].material:
                    rep_mat = body_obj.material_slots[idx].material
                    break
            if not rep_mat:
                continue

            # 生成只包含该组材质面的临时网格
            bm = bmesh.new()
            bm.from_mesh(body_obj.data)
            for face in list(bm.faces):
                if face.material_index not in indices:
                    bm.faces.remove(face)
            for face in bm.faces:
                face.material_index = 0
            bake_mesh = body_obj.data.copy()
            bake_mesh.materials.clear()
            bake_mesh.materials.append(rep_mat)
            bm.to_mesh(bake_mesh)
            bm.free()
            bake_mesh.update()

            bake_obj = bpy.data.objects.new("VRMFixer_BakeTemp", bake_mesh)
            context.collection.objects.link(bake_obj)
            bake_obj.hide_set(False)
            bake_obj.hide_render = False
            bake_objs.append(bake_obj)

            # 生成烘焙目标贴图
            src_img = group["image"]
            w = min(int(src_img.size[0]) if src_img.size else 1024, 1024)
            h = min(int(src_img.size[1]) if src_img.size else 1024, 1024)
            img_name = "VRMFixer_Baked_" + key
            if img_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[img_name])
            bake_img = bpy.data.images.new(img_name, width=w, height=h, alpha=True)
            baked_images[key] = bake_img

            # 给材质添加一个未连接的激活 Image Texture 作为烘焙目标
            rep_mat.use_nodes = True
            nt = rep_mat.node_tree
            for n in list(nt.nodes):
                if n.name.startswith("VRMFixer_BakeTarget"):
                    nt.nodes.remove(n)
            target_node = nt.nodes.new("ShaderNodeTexImage")
            target_node.name = "VRMFixer_BakeTarget"
            target_node.image = bake_img
            nt.nodes.active = target_node

            bpy.ops.object.select_all(action="DESELECT")
            bake_obj.select_set(True)
            context.view_layer.objects.active = bake_obj
            bpy.ops.object.bake(type="EMIT", margin=4)

        # 把所有临时烘焙对象隐藏, 避免导出时混入
        for obj in bake_objs:
            obj.hide_set(True)
            obj.hide_render = True

        # 恢复原模型可见
        for name in [armature_obj.name, body_obj.name]:
            obj = bpy.data.objects.get(name)
            if obj:
                obj.hide_set(False)
                obj.hide_render = False

        # 将材质转换为 MToon, 并替换成烘焙贴图
        infos = []
        converted = 0
        for idx, slot in enumerate(body_obj.material_slots):
            mat = slot.material
            if not mat:
                continue
            info = slot_infos[idx] or {}
            ext = get_material_extension(mat)
            ext.mtoon1.enabled = True

            src_img = info.get("base_img") if info else None
            baked_img = None
            if src_img is not None:
                baked_img = baked_images.get(src_img.name)
            if baked_img is not None:
                ext.mtoon1.pbr_metallic_roughness.base_color_texture.index.source = baked_img

            alpha = _clamp(info.get("alpha", 1.0))
            if alpha < 0.999 or baked_img is None:
                ext.mtoon1.alpha_mode = "BLEND"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, alpha)
            else:
                ext.mtoon1.alpha_mode = "OPAQUE"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)

            infos.append(
                f"[{idx}] {mat.name}: 使用烘焙贴图 {baked_img.name if baked_img else '无'}, "
                f"alpha={ext.mtoon1.alpha_mode}"
            )
            converted += 1

        set_vrm1_meta(ext_mod, armature_obj, os.path.splitext(os.path.basename(output_path))[0] or "VRM_Model")

        for _rig_line in maybe_normalize_rig(context):
            print(f"[VRM Fixer] {_rig_line}")

        _export_result = bpy.ops.export_scene.vrm(
            filepath=output_path,
            armature_object_name=armature_obj.name,
            check_existing=False,
        )
        if "FINISHED" not in _export_result:
            print(f"[VRM Fixer] 导出被 VRM 插件拒绝(通常是人形骨骼层级校验失败): {_export_result}")
            return False, ["VRM 导出被拒绝, 请看控制台的 Validation error"]
        if not os.path.exists(output_path):
            return False, ["VRM 导出后文件不存在, 请看控制台"]
        return True, infos
    finally:
        # 清理临时烘焙对象
        for obj in bake_objs:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        scene.render.engine = old_engine
        if hasattr(scene, "cycles"):
            scene.cycles.samples = old_samples


def convert_materials(context, mode="MBTS_MAP"):
    ext_mod = get_vrm_extension_module()
    if not ext_mod:
        return 0, 0, ["找不到 VRM Addon, 请先在插件面板启用 VRM_Addon_for_Blender"]

    armature_obj, body_obj = find_model_objects()
    if not armature_obj or not body_obj:
        return 0, 0, ["当前场景没有找到骨骼或带材质槽的网格体"]

    get_material_extension = ext_mod.get_material_extension
    infos = []
    converted = 0
    total = len(body_obj.material_slots)

    for idx, slot in enumerate(body_obj.material_slots):
        mat = slot.material
        if not mat:
            infos.append(f"[{idx}] 空材质槽, 跳过")
            continue
        try:
            info = collect_legacy_material_values(mat)
            ext = get_material_extension(mat)
            ext.mtoon1.enabled = True

            if info["base_img"] is not None:
                ext.mtoon1.pbr_metallic_roughness.base_color_texture.index.source = info["base_img"]

            if info["found"]:
                if info["kind"] == "mmd":
                    ext.mtoon1.double_sided = info["double_sided"] > 0.5
                    if info["alpha"] < 0.001:
                        ext.mtoon1.alpha_mode = "BLEND"
                        ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                            1.0,
                            1.0,
                            1.0,
                            0.0,
                        )
                    else:
                        ext.mtoon1.alpha_mode = "OPAQUE"
                        ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                            1.0,
                            1.0,
                            1.0,
                            1.0,
                        )
                elif info["kind"] == "mbts":
                    mbts = info["mbts"]
                    alpha = _clamp(info["alpha"])
                    # 只有原 Alpha < 1 或无贴图的阴影件才透明; 正常材质保持 OPAQUE
                    if alpha < 0.999 or info["base_img"] is None:
                        ext.mtoon1.alpha_mode = "BLEND"
                        ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                            1.0,
                            1.0,
                            1.0,
                            alpha,
                        )
                    else:
                        ext.mtoon1.alpha_mode = "OPAQUE"
                        ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                            1.0,
                            1.0,
                            1.0,
                            1.0,
                        )

                    if mode == "MBTS_MAP":
                        # MBTs 参数映射到 MToon
                        mtoon = ext.mtoon1.extensions.vrmc_materials_mtoon
                        mtoon.shade_color_factor = _to_rgb3(mbts.get("阴影颜色"))

                        shadow_strength = mbts.get("阴影强度", 0.6)
                        mtoon.shading_toony_factor = _clamp(1.0 - shadow_strength * 0.5)
                        mtoon.shading_shift_factor = -0.2 + shadow_strength * 0.1

                        # 边缘光默认不映射, 避免整片橙色/过亮
                        mtoon.parametric_rim_color_factor = (0.0, 0.0, 0.0)
                        mtoon.parametric_rim_fresnel_power_factor = 1.0
                        mtoon.parametric_rim_lift_factor = 0.0
                        mtoon.rim_lighting_mix_factor = 0.0
                    # SIMPLE 模式: 只保留基础贴图和透明, 不映射 MBTs 参数

            tex_name = info["base_img"].name if info["base_img"] else "无"
            infos.append(
                f"[{idx}] {mat.name}: kind={info['kind']}, 完成, 贴图={tex_name}, "
                f"alpha={ext.mtoon1.alpha_mode}"
            )
            converted += 1
        except Exception as exc:
            infos.append(f"[{idx}] {mat.name}: 失败 - {exc}")
            traceback.print_exc()

    fallback = os.path.splitext(os.path.basename(context.blend_data.filepath or ""))[0]
    if not fallback:
        fallback = "VRM_Model"
    set_vrm1_meta(ext_mod, armature_obj, fallback)

    return converted, total, infos


class VRMFIXER_OT_AutoBindExpressions(Operator):
    """自动绑定当前 VRM1 模型的表情预设到形状键"""

    bl_idname = "vrm_fixer.auto_bind_expressions"
    bl_label = "自动绑定 VRM1 表情"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.objects)

    def execute(self, context):
        ok, infos = auto_bind_vrm1_expressions(context)
        for line in infos:
            print(f"[VRM Fixer] {line}")
        if not ok:
            self.report({"WARNING"}, "没有绑定到任何表情, 详情见控制台")
        else:
            self.report({"INFO"}, f"已自动绑定 {sum(1 for x in infos if '->' in x)} 个表情")
        return {"FINISHED"}


class VRMFIXER_OT_GenerateSpringBones(Operator):
    """从 MMD 物理(刚体/关节)自动生成 VRMC 弹簧骨"""

    bl_idname = "vrm_fixer.generate_spring_bones"
    bl_label = "从 MMD 物理生成弹簧骨"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.objects)

    def execute(self, context):
        made, infos = generate_spring_bones(context)
        for line in infos:
            print(f"[VRM Fixer] {line}")
        if made == 0:
            self.report({"WARNING"}, infos[0] if infos else "没有生成弹簧骨")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已生成 {made} 条弹簧骨, 详情见控制台")
        return {"FINISHED"}


class VRMFIXER_OT_NormalizeRig(Operator):
    """把 MMD 装备骨里夹在人形骨骼之间的 helper 骨骼朝向规范化"""

    bl_idname = "vrm_fixer.normalize_rig"
    bl_label = "规范化骨骼朝向(Unity 应用兼容)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.objects)

    def execute(self, context):
        changed, infos = normalize_helper_frames(context)
        for line in infos:
            print(f"[VRM Fixer] {line}")
        if changed == 0:
            self.report({"INFO"}, infos[0] if infos else "无需处理")
            return {"FINISHED"}
        self.report({"INFO"}, f"已规范化 {changed} 根 helper 骨骼, 详情见控制台")
        return {"FINISHED"}


class VRMFIXER_OT_ConvertMaterials(Operator):
    bl_idname = "vrm_fixer.convert_materials"
    bl_label = "转换材质为 VRM MToon1 (兼容 MBTs 卡渲)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.objects)

    def execute(self, context):
        mode = context.scene.vrm_fixer_mode
        if mode == "BAKE":
            self.report({"INFO"}, "烘焙模式请直接使用「一键修复并导出 VRM」, 这里不单独转换")
            return {"FINISHED"}

        converted, total, infos = convert_materials(context, mode=mode)
        if not infos:
            self.report({"WARNING"}, "没有可转换的材质")
            return {"CANCELLED"}

        for line in infos:
            print(f"[VRM Fixer] {line}")

        if converted > 0:
            self.report({"INFO"}, f"已转换 {converted}/{total} 个材质, 详情见控制台/终端")
            return {"FINISHED"}

        self.report({"ERROR"}, "没有成功转换任何材质, 请查看终端(窗口 > 切换系统控制台)")
        return {"CANCELLED"}


class VRMFIXER_OT_ConvertAndExport(Operator):
    bl_idname = "vrm_fixer.convert_and_export"
    bl_label = "一键修复并导出 VRM"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.objects)

    def execute(self, context):
        mode = context.scene.vrm_fixer_mode
        output_path = context.scene.vrm_fixer_output_path
        if not output_path:
            self.report({"ERROR"}, "请先填写 VRM 输出路径")
            return {"CANCELLED"}

        if output_path.startswith("//"):
            if not bpy.data.filepath:
                self.report({"ERROR"}, "当前文件还没保存过, 无法解析 // 相对路径, 请使用绝对路径")
                return {"CANCELLED"}
            output_path = bpy.path.abspath(output_path)

        if os.path.isdir(output_path):
            output_path = os.path.join(output_path, "MMD_MToon_Fixed.vrm")

        if context.scene.vrm_fixer_auto_bind_expressions:
            ok, bind_infos = auto_bind_vrm1_expressions(context)
            for line in bind_infos:
                print(f"[VRM Fixer] AutoBind: {line}")
            if ok:
                self.report({"INFO"}, "已自动绑定 VRM1 表情")

        if mode == "BAKE":
            ok, infos = bake_mbts_and_export(context, output_path)
            for line in infos:
                print(f"[VRM Fixer] {line}")
            if not ok:
                self.report({"ERROR"}, "烘焙导出失败: " + " / ".join(infos))
                return {"CANCELLED"}
            self.report({"INFO"}, f"烘焙 VRM 已导出: {output_path}")
            print(f"[VRM Fixer] RESULT_OK {output_path}")
            return {"FINISHED"}

        converted, total, infos = convert_materials(context, mode=mode)
        for line in infos:
            print(f"[VRM Fixer] {line}")

        if converted == 0:
            self.report({"ERROR"}, "材质转换失败, 未导出 VRM")
            return {"CANCELLED"}

        armature_obj, _ = find_model_objects()
        if not armature_obj:
            self.report({"ERROR"}, "导出失败: 找不到骨骼")
            return {"CANCELLED"}

        for _rig_line in maybe_normalize_rig(context):
            print(f"[VRM Fixer] {_rig_line}")

        bpy.ops.export_scene.vrm(
            filepath=output_path,
            armature_object_name=armature_obj.name,
            check_existing=False,
        )
        self.report({"INFO"}, f"VRM 已导出: {output_path}")
        print(f"[VRM Fixer] RESULT_OK {output_path}")
        return {"FINISHED"}


class VRMFIXER_PT_Panel(Panel):
    bl_label = "VRM MToon Fixer"
    bl_idname = "VRMFIXER_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VRM Fixer"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="MMD Shader -> VRM MToon1", icon="MATERIAL")
        armature_obj, body_obj = find_model_objects()
        if armature_obj and body_obj:
            box.label(text=f"骨骼: {armature_obj.name}")
            box.label(text=f"网格: {body_obj.name}")
            box.label(text=f"材质槽: {len(body_obj.material_slots)}")
        else:
            box.label(text="未检测到骨骼/网格", icon="ERROR")

        layout.prop(scene, "vrm_fixer_mode", text="导出模式")
        layout.prop(scene, "vrm_fixer_auto_bind_expressions", text="导出前自动绑定 VRM1 表情")
        layout.operator(VRMFIXER_OT_AutoBindExpressions.bl_idname)
        layout.prop(scene, "vrm_fixer_bake_inherit", text="导出前烘焙 MMD 付与骨(修下半身僵住)")
        layout.prop(scene, "vrm_fixer_normalize_rig", text="导出前规范化骨骼朝向")
        layout.operator(VRMFIXER_OT_NormalizeRig.bl_idname)
        layout.prop(scene, "vrm_fixer_gen_spring_bones", text="导出前生成弹簧骨(头发/披风/尾巴)")
        layout.operator(VRMFIXER_OT_GenerateSpringBones.bl_idname)
        layout.prop(scene, "vrm_fixer_output_path", text="输出 VRM")
        layout.operator(VRMFIXER_OT_ConvertMaterials.bl_idname)
        layout.operator(VRMFIXER_OT_ConvertAndExport.bl_idname, icon="EXPORT")

        layout.separator()
        if scene.vrm_fixer_mode == "SIMPLE":
            layout.label(text="直接导出: 只接回基础贴图, 不映射 MBTs 参数。", icon="INFO")
        elif scene.vrm_fixer_mode == "MBTS_MAP":
            layout.label(text="MBTs映射: 把 MBTs 阴影参数映射到 MToon1。", icon="INFO")
        elif scene.vrm_fixer_mode == "BAKE":
            layout.label(text="烘焙模式: 需要 Cycles, 会把卡渲效果烘进贴图再导出。", icon="INFO")


CLASSES = (
    VRMFIXER_OT_AutoBindExpressions,
    VRMFIXER_OT_NormalizeRig,
    VRMFIXER_OT_GenerateSpringBones,
    VRMFIXER_OT_ConvertMaterials,
    VRMFIXER_OT_ConvertAndExport,
    VRMFIXER_PT_Panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vrm_fixer_mode = EnumProperty(
        name="导出模式",
        description="选择要使用的导出方法",
        items=VRM_FIXER_MODE_ITEMS,
        default="MBTS_MAP",
    )
    bpy.types.Scene.vrm_fixer_auto_bind_expressions = BoolProperty(
        name="导出前自动绑定 VRM1 表情",
        description="导出前自动把 VRM1 表情预设绑定到模型形状键",
        default=True,
    )
    bpy.types.Scene.vrm_fixer_bake_inherit = BoolProperty(
        name="导出前烘焙 MMD 付与骨",
        description="把 MMD 模型里靠约束(付与)跟随人形骨骼的骨骼改成真实父子关系, "
                    "否则导出 VRM 后这些部位(常见腿部/下半身)会僵在绑定姿势",
        default=True,
    )
    bpy.types.Scene.vrm_fixer_gen_spring_bones = BoolProperty(
        name="导出前生成弹簧骨",
        description="从 MMD 刚体自动生成 VRMC 弹簧骨, 让头发/披风/尾巴等在 Unity 里摆动",
        default=True,
    )
    bpy.types.Scene.vrm_fixer_normalize_rig = BoolProperty(
        name="导出前规范化骨骼朝向",
        description="把 MMD 装备骨里夹在人形骨骼之间的 helper 骨骼朝向对齐, "
                    "修复 Unity 侧应用里躯干/头部前倾(如 MATE ENGINE 里头部一直朝下)",
        default=True,
    )
    bpy.types.Scene.vrm_fixer_output_path = StringProperty(
        name="VRM 输出路径",
        description="导出目标, 支持 // 相对路径",
        subtype="FILE_PATH",
        default="//MMD_MToon_Fixed.vrm",
    )


def unregister():
    if hasattr(bpy.types.Scene, "vrm_fixer_auto_bind_expressions"):
        del bpy.types.Scene.vrm_fixer_auto_bind_expressions
    if hasattr(bpy.types.Scene, "vrm_fixer_mode"):
        del bpy.types.Scene.vrm_fixer_mode
    if hasattr(bpy.types.Scene, "vrm_fixer_bake_inherit"):
        del bpy.types.Scene.vrm_fixer_bake_inherit
    if hasattr(bpy.types.Scene, "vrm_fixer_gen_spring_bones"):
        del bpy.types.Scene.vrm_fixer_gen_spring_bones
    if hasattr(bpy.types.Scene, "vrm_fixer_normalize_rig"):
        del bpy.types.Scene.vrm_fixer_normalize_rig
    if hasattr(bpy.types.Scene, "vrm_fixer_output_path"):
        del bpy.types.Scene.vrm_fixer_output_path
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()