# -*- coding: utf-8 -*-
"""
骨骼朝向规范化(Unity / VRM 应用兼容)
=====================================

解决的问题
----------
MMD 完整装备骨(センター / グルーブ / 腰 / 上半身1 / 上半身2 ...)里,
某些骨骼的**静止朝向**不是竖直的, 例如 lothe 的「腰」骨骼本身前倾 42.7°,
靠「上半身」的 -42.7° 局部旋转把它掰回竖直。

很多 Unity 侧的 VRM 应用(如 MATE ENGINE 的 AvatarMouseTracking)会假定
"spine 的局部初始旋转≈0、父骨骼坐标轴朝上", 于是会**直接覆盖** spine 的局部旋转,
结果躯干连带头部前倾 —— 表现为「头一直朝下」。

本脚本把"夹在人形骨骼之间的 helper 骨骼"的静止朝向改成与其人形子骨骼一致,
使每个人形骨骼相对父级的局部旋转≈0。这样应用即使覆盖也不会跑偏。

安全性
------
只改 helper 骨骼(非人形骨骼)的**朝向**, 不动骨骼头部位置、不动人形骨骼的朝向。
静止姿势下网格形变矩阵恒为单位阵, 所以**模型外观完全不变**;
子骨骼的静止世界坐标由 Blender 独立保存, 也不会移动。
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

VRM_MODULE_CANDIDATES = [
    "VRM_Addon_for_Blender-release",
    "VRM_Addon_for_Blender",
    "io_scene_vrm",
]


def get_vrm_extension_module():
    import importlib

    for name in VRM_MODULE_CANDIDATES:
        try:
            return importlib.import_module(f"{name}.editor.extension")
        except Exception:
            continue
    return None


def find_armature():
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        return None
    return max(armatures, key=lambda o: len(o.data.bones))


def get_humanoid_bone_names(armature_obj):
    """返回 {人形骨骼名(hips/spine/...): Blender 里的骨骼名}"""
    ext_mod = get_vrm_extension_module()
    if ext_mod is None:
        return {}
    try:
        ext = ext_mod.get_armature_extension(armature_obj.data)
        human_bones = ext.vrm1.humanoid.human_bones
        out = {}
        for field_name in dir(human_bones):
            if field_name.startswith("_"):
                continue
            entry = getattr(human_bones, field_name, None)
            node = getattr(entry, "node", None)
            if node is None:
                continue
            bone_name = getattr(node, "bone_name", "")
            if bone_name:
                out[field_name] = bone_name
        return out
    except Exception as exc:
        print(f"[rig] 读取人形骨骼映射失败: {exc}")
        return {}


def rel_rotation_angle(bone_name, parent_name, armature_obj):
    """bone 相对 parent 的静止旋转角度(度)。应用覆盖 bone 局部旋转时会跑偏这么多。"""
    bones = armature_obj.data.bones
    if bone_name not in bones or parent_name not in bones:
        return None
    b = bones[bone_name].matrix_local
    p = bones[parent_name].matrix_local
    rel = p.inverted() @ b
    return math.degrees(rel.to_quaternion().angle)


def scan(armature_obj, humanoid_names, verbose=True):
    """找出"父级不是人形骨骼"的人形骨骼, 以及该父级造成的偏差角度。"""
    bones = armature_obj.data.bones
    humanoid_set = set(humanoid_names.values())
    problems = []
    for field, bone_name in sorted(humanoid_names.items()):
        bone = bones.get(bone_name)
        if bone is None or bone.parent is None:
            continue
        parent = bone.parent
        if parent.name in humanoid_set:
            continue  # 父级本身就是人形骨骼, 应用里的假定成立
        angle = rel_rotation_angle(bone_name, parent.name, armature_obj)
        if angle is None:
            continue
        if verbose:
            print(f"[rig] {field:<16} {bone_name:<12} 的父级 {parent.name:<10}"
                  f" 不是人形骨骼, 局部静止旋转 = {angle:6.2f}°")
        if angle > 1.0:
            problems.append({
                "humanoid": field,
                "bone": bone_name,
                "parent": parent.name,
                "angle": angle,
            })
    return problems


def normalize(armature_obj, problems, report=None):
    """把 helper 父骨骼的静止朝向改成与其人形子骨骼一致(保持头部位置与长度不变)。"""
    if not problems:
        return []

    changed = []
    prev_active = bpy.context.view_layer.objects.active
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = armature_obj.data.edit_bones
        for item in problems:
            parent_eb = edit_bones.get(item["parent"])
            child_eb = edit_bones.get(item["bone"])
            if parent_eb is None or child_eb is None:
                continue

            child_m = child_eb.matrix.to_3x3()
            child_y = child_m.col[1].normalized()   # 子骨骼朝向(也就是父骨骼该指向的方向)
            child_z = child_m.col[2].normalized()   # 子骨骼滚转参考

            head = parent_eb.head.copy()
            length = parent_eb.length
            parent_eb.tail = head + child_y * length
            parent_eb.align_roll(child_z)
            changed.append(item["parent"])
            if report is not None:
                report.append(f"  {item['parent']} 朝向已对齐 {item['bone']} "
                              f"(原来偏差 {item['angle']:.2f}°)")
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            bpy.context.view_layer.objects.active = prev_active
        except Exception:
            pass

    # 复核
    if report is not None:
        report.append("  --- 复核 ---")
        for item in problems:
            left = rel_rotation_angle(item["bone"], item["parent"], armature_obj)
            report.append(f"  {item['bone']} 相对 {item['parent']} 的静止旋转: "
                          f"{item['angle']:.2f}° -> {left:.2f}°" if left is not None
                          else f"  {item['bone']}: 复核失败")
    return changed


# ---------------- 命令行入口 ----------------
def parse_args():
    argv = sys.argv
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1:]


def main():
    args = parse_args()
    if len(args) < 2:
        raise SystemExit("用法: blender --background --python normalize_rig_frames.py -- "
                         "<输入.blend> <输出.vrm> [--dry-run]")
    blend_path, out_vrm = args[0], args[1]
    dry_run = "--dry-run" in args

    print(f"[rig] 打开 {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    for mod in VRM_MODULE_CANDIDATES:
        try:
            bpy.ops.preferences.addon_enable(module=mod)
            print(f"[rig] 已启用 {mod}")
            break
        except Exception:
            continue

    armature_obj = find_armature()
    if armature_obj is None:
        raise SystemExit("[rig] 没找到骨骼")
    print(f"[rig] 骨骼对象: {armature_obj.name}")

    humanoid_names = get_humanoid_bone_names(armature_obj)
    print(f"[rig] 人形骨骼映射数: {len(humanoid_names)}")
    if not humanoid_names:
        raise SystemExit("[rig] 没读到 VRM 人形骨骼映射, 请确认该 .blend 是 VRM1 模型")

    problems = scan(armature_obj, humanoid_names)
    if not problems:
        print("[rig] 没有需要规范的骨骼(人形骨骼的父级都是人形骨骼)")
        return

    report = []
    if dry_run:
        print("[rig] dry-run, 不修改")
        for p in problems:
            print(f"  将修正 {p['parent']} -> 对齐 {p['bone']} (偏差 {p['angle']:.2f}°)")
        return

    normalize(armature_obj, problems, report)
    for line in report:
        print("[rig] " + line)

    print(f"[rig] 导出 {out_vrm}")
    bpy.ops.export_scene.vrm(
        filepath=out_vrm,
        armature_object_name=armature_obj.name,
        check_existing=False,
    )
    print("[rig] 完成")


if __name__ == "__main__":
    main()
