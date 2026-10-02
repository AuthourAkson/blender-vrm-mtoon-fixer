# -*- coding: utf-8 -*-
"""从 MMD 物理自动生成 VRM 弹簧骨(命令行版)。

实现已经集成在插件里(addon/vrm_mtoon_fixer), 这里只是命令行包装,
两者行为完全一致(Blender 面板里是 `导出前生成弹簧骨` 开关 + `从 MMD 物理生成弹簧骨` 按钮)。

会做这些事:
  1. 读取 mmd_tools 的刚体数据(obj["mmd_rigid"]):
       type 1 = 静态(只做碰撞体), type 2/3 = 动态(需要弹簧骨)
  2. 动态刚体的骨骼按层级连成链(分叉处切开, 每根骨骼只归一条弹簧)
  3. 静态刚体 -> VRM 球形碰撞体, 按 MMD 碰撞组/掩码分配给弹簧
  4. 按部位给参数(尾巴/头发/披风/鞋带 ...), 并沿链逐节递减硬度(根硬梢软)

用法:
  blender --background --python scripts/gen_spring_bones.py -- <输入.blend> [输出.vrm] [--dry-run]
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(os.path.dirname(HERE), "addon")
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)

import vrm_mtoon_fixer as fixer  # noqa: E402


def parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if not args:
        raise SystemExit(__doc__)
    blend_path = args[0]
    out_path = args[1] if len(args) > 1 and not args[1].startswith("--") else None
    return blend_path, out_path, ("--dry-run" in args)


def main():
    blend_path, out_path, dry_run = parse_args()
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    for mod in fixer.ADDON_MODULE_CANDIDATES:
        try:
            bpy.ops.preferences.addon_enable(module=mod)
            break
        except Exception:
            continue

    armature_obj, _body = fixer.find_model_objects()
    if armature_obj is None:
        raise SystemExit("[spring] 找不到骨骼对象")

    if dry_run:
        rigid = fixer.collect_mmd_rigid_bodies()
        static = {b: i for b, i in rigid.items() if i["type"] == 1}
        dynamic = {b: i for b, i in rigid.items() if i["type"] != 1}
        chains = fixer.build_spring_chains(armature_obj, set(dynamic))
        print(f"[spring] 刚体骨骼 {len(rigid)} 根 (静态 {len(static)} / 动态 {len(dynamic)})")
        print(f"[spring] {len(chains)} 条链 / {sum(len(c) for c in chains)} 个关节")
        for c in sorted(chains, key=lambda x: (-len(x), x[0])):
            root_s, tip_s, drag, grav, hit, max_j = fixer.spring_profile(c[0])
            print(f"    [{len(c):2d}] {c[0]:<30} 硬度 {root_s:.2f}->{tip_s:.2f} "
                  f"阻尼 {drag:.2f} 取前 {max_j} 节")
            print(f"         {' -> '.join(c)}")
        return

    made, infos = fixer.generate_spring_bones(bpy.context)
    for line in infos:
        print(f"[spring] {line}")
    if out_path:
        result = bpy.ops.export_scene.vrm(filepath=out_path,
                                          armature_object_name=armature_obj.name,
                                          check_existing=False)
        print(f"[spring] 导出 {result} -> {out_path}")


if __name__ == "__main__":
    main()
