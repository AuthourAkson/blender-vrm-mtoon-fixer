# -*- coding: utf-8 -*-
"""
Blender 4.x MMD材质 -> VRM MToon1 修复脚本
用法（命令行）:
    blender.exe --background --python vrm_material_fixer.py -- <输入.blend|.blend1> [输出.vrm]

会做这些事:
    1. 打开混合文件（如果是 .blend1 会先复制为 _recovered.blend）
    2. 找到第一个骨骼和材质槽最多的身体网格
    3. 把每个槽的 mmd_shader / MMDShaderDev 材质转换为 VRM MToon1
    4. 重新接上原来的 mmd_base_tex 贴图
    5. 保留双面与透明(Aozame/Tere/Kurozame)设置
    6. 如果 VRM1 名称为空，补上文件名
    7. 保存 *_MToonFixed.blend 并导出 *_MToonFixed.vrm
"""
import bpy
import sys
import os
import shutil
import pathlib
import traceback

IS_HEADLESS = bpy.app.background


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def log(msg):
    print(f"[Fixer] {msg}", flush=True)


def _addon_enabled(module_name):
    for addon in bpy.context.preferences.addons:
        if getattr(addon, "module", None) == module_name:
            return True
    return False


def enable_vrm_addon_if_needed():
    for module in ["VRM_Addon_for_Blender-release", "VRM_Addon_for_Blender"]:
        if _addon_enabled(module):
            return module
    # 没启用则尝试启用
    for module in ["VRM_Addon_for_Blender-release", "VRM_Addon_for_Blender"]:
        try:
            bpy.ops.preferences.addon_enable(module=module)
            if _addon_enabled(module):
                return module
        except Exception:
            pass
    return None


def import_addon_extensions(module_name):
    import importlib

    try:
        ext_mod = importlib.import_module(
            f"{module_name}.editor.extension"
        )
        return ext_mod
    except Exception:
        pass
    # Fallback: 老版本 addon 的包名
    try:
        ext_mod = importlib.import_module("io_scene_vrm.editor.extension")
        return ext_mod
    except Exception:
        pass
    raise RuntimeError("找不到 VRM 插件扩展模块，请确认 VRM Addon 已安装并启用")


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
            is_mbts = tree_name.startswith("MBTs") or tree_name == "群组" and "MColor" in node.inputs
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


def convert_material(ext_mod, mat):
    get_material_extension = ext_mod.get_material_extension
    info = collect_legacy_material_values(mat)

    ext = get_material_extension(mat)
    ext.mtoon1.enabled = True

    result = {"alpha": ext.mtoon1.alpha_mode, "tex": None, "kind": info["kind"]}
    if info["base_img"] is not None:
        ext.mtoon1.pbr_metallic_roughness.base_color_texture.index.source = info["base_img"]
        result["tex"] = info["base_img"].name

    if not info["found"]:
        return result

    if info["kind"] == "mmd":
        try:
            ext.mtoon1.double_sided = info["double_sided"] > 0.5
        except Exception:
            pass
        try:
            if info["alpha"] < 0.001:
                ext.mtoon1.alpha_mode = "BLEND"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                    1.0,
                    1.0,
                    1.0,
                    0.0,
                )
                result["alpha"] = "BLEND"
            else:
                ext.mtoon1.alpha_mode = "OPAQUE"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                )
        except Exception:
            pass
    elif info["kind"] == "mbts":
        try:
            mbts = info["mbts"]
            # MBTs 材质默认不透明; 只有原材质 Alpha < 1 或没有贴图的阴影件才走 BLEND
            alpha = _clamp(info["alpha"])
            if alpha < 0.999 or info["base_img"] is None:
                ext.mtoon1.alpha_mode = "BLEND"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                    1.0,
                    1.0,
                    1.0,
                    alpha,
                )
                result["alpha"] = "BLEND"
            else:
                ext.mtoon1.alpha_mode = "OPAQUE"
                ext.mtoon1.pbr_metallic_roughness.base_color_factor = (
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                )
                result["alpha"] = "OPAQUE"

            # 阴影颜色 -> MToon shadeColor
            mtoon = ext.mtoon1.extensions.vrmc_materials_mtoon
            shade_color = _to_rgb3(mbts.get("阴影颜色"))
            mtoon.shade_color_factor = shade_color

            # 阴影强度: 粗略映射到 MToon 的卡通边界硬度/偏移
            shadow_strength = mbts.get("阴影强度", 0.6)
            toony = _clamp(1.0 - shadow_strength * 0.5, 0.0, 1.0)
            shift = -0.2 + shadow_strength * 0.1
            mtoon.shading_toony_factor = toony
            mtoon.shading_shift_factor = shift

            # MBTs 边缘光先不映射到 MToon rim, 避免整片橙色/过亮
            # 以后需要可以单独针对某些材质开启
            mtoon.parametric_rim_color_factor = (0.0, 0.0, 0.0)
            mtoon.parametric_rim_fresnel_power_factor = 1.0
            mtoon.parametric_rim_lift_factor = 0.0
            mtoon.rim_lighting_mix_factor = 0.0
        except Exception:
            pass
    return result


def set_meta_name(ext_mod, armature_obj, fallback_name):
    get_armature_extension = ext_mod.get_armature_extension
    ext = get_armature_extension(armature_obj.data)
    if ext.is_vrm0():
        return
    meta = ext.vrm1.meta
    if not getattr(meta, "vrm_name", ""):
        meta.vrm_name = fallback_name
    if not getattr(meta, "version", ""):
        meta.version = "1.0"


def main():
    args = parse_args()
    if len(args) < 1:
        log("未提供输入文件")
        log("用法: blender.exe --background --python vrm_material_fixer.py -- <input.blend/.blend1> [output.vrm]")
        raise SystemExit(1)

    raw_input = pathlib.Path(args[0]).expanduser()
    log(f"输入文件: {raw_input}")

    if raw_input.suffix.lower() == ".blend1":
        recovered = raw_input.with_name(raw_input.stem + "_recovered.blend")
        if not recovered.exists():
            try:
                shutil.copyfile(raw_input, recovered)
                log(f"已从 .blend1 恢复: {recovered}")
            except Exception as e:
                log(f"恢复 .blend1 失败: {e}")
                raise SystemExit(1)
        else:
            log(f"恢复文件已存在，使用: {recovered}")
        work_path = recovered
    else:
        work_path = raw_input

    if not work_path.exists():
        log(f"文件不存在: {work_path}")
        raise SystemExit(1)

    out_vrm = (
        pathlib.Path(args[1]).expanduser()
        if len(args) >= 2
        else work_path.with_name(work_path.stem + "_MToonFixed.vrm")
    )
    log(f"输出 VRM: {out_vrm}")

    module_name = enable_vrm_addon_if_needed()
    log(f"VRM 插件模块: {module_name}")
    if not module_name:
        log("VRM 插件未启用，无法继续")
        raise SystemExit(1)

    import importlib

    ext_mod = importlib.import_module(f"{module_name}.editor.extension")

    bpy.ops.wm.open_mainfile(filepath=str(work_path))
    log("混合文件已打开")

    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [
        o for o in bpy.data.objects
        if o.type == "MESH" and o.data and o.data.materials
    ]
    if not armatures:
        log("没有找到骨骼 Armature，可能不是 VRM/MMD 模型")
        raise SystemExit(1)
    if not meshes:
        log("没有找到带材质槽的网格体")
        raise SystemExit(1)

    armature_obj = armatures[0]
    body_obj = max(meshes, key=lambda o: len(o.data.materials))
    log(f"使用骨骼: {armature_obj.name}")
    log(f"使用网格: {body_obj.name}（材质槽 {len(body_obj.material_slots)}）")

    converted = 0
    for idx, slot in enumerate(body_obj.material_slots):
        mat = slot.material
        if not mat:
            log(f"  [{idx}] 空材质槽，跳过")
            continue
        try:
            res = convert_material(ext_mod, mat)
            log(
                f"  [{idx}] {mat.name}: kind={res['kind']}, MToon1 已启用, 贴图={res['tex']}, alpha={res['alpha']}"
            )
            converted += 1
        except Exception as e:
            log(f"  [{idx}] {mat.name}: 转换失败 -> {e}")
            traceback.print_exc()
    log(f"材质转换完成: {converted}/{len(body_obj.material_slots)}")

    set_meta_name(ext_mod, armature_obj, work_path.stem)
    log("VRM1 元信息名称已检查")

    blend_out = work_path.with_name(work_path.stem + "_MToonFixed.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_out))
    log(f"已保存混合文件: {blend_out}")

    out_vrm.parent.mkdir(parents=True, exist_ok=True)
    log("开始导出 VRM ...")
    bpy.ops.export_scene.vrm(
        filepath=str(out_vrm),
        armature_object_name=armature_obj.name,
        check_existing=False,
    )
    log(f"导出完成: {out_vrm}")
    log("RESULT_OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("FAIL:", traceback.format_exc(), flush=True)
        raise
