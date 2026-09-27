---
name: blender-vrm-mtoon-fixer
description: 修复 Blender 导入 PMX/MMD 模型后导出 VRM 变灰色、材质贴图丢失的问题,兼容 mmd_shader 与 MBTs-NG 卡渲(MBTs-R2Y)材质。Use this skill whenever the user says Blender 导出 VRM 后模型是灰色/没材质/贴图不显示, or when a .blend file has materials wired to mmd_shader / MMDShaderDev and needs converting to VRM MToon1 before export. Also use for recovering model data from .blend1 when the current .blend is empty, and for batch-converting MMD materials to VRM MToon1 via Blender Python API.
---

# Blender MMD 材质 → VRM MToon1 修复

## 这个 skill 解决什么问题

Blender 里的模型从 PMX/MMD 导入后,材质节点连的是 `mmd_shader`(节点组 `MMDShaderDev`)。
VRM Addon 导出时只认三种材质:
- VRM MToon1(`VRMC_materials_mtoon`)
- Principled BSDF
- GLTF / TRANSPARENT_ZWRITE

`mmd_shader` 不在其中,所以导出后模型变成灰色、贴图丢失。本 skill 把这条修复链路固化下来。

## 工作流程

### 1. 先找模型文件

- 优先看有没有 `.blend1` 备份。**如果 `.blend` 打开后只有灯光/摄像机、没有模型,模型大概率在同目录的 `.blend1` 里。**
- 不要覆盖 `.blend1`。先复制成 `*_recovered.blend`。
- 贴图一般在模型同目录 `textures/` 下,常见文件名约定:`mmd_base_tex` 节点对应漫反射贴图。

### 2. 诊断材质

用 Blender 后台 Python 打开 `.blend`,遍历 `Body` 网格的材质槽:

- `search` / `legacy_shader_node` 检查 Surface 连的是什么节点组
- 如果是 `mmd_shader`,记录它的输入:
  - `mmd_base_tex` → baseColorTexture
  - `Alpha` → 是否 BLEND(旧值 0 的透明度)
  - `Double Sided` → 是否双面

### 3. 转换材质(核心)

Blender Python 代码模板:

```python
import bpy, importlib
ext_mod = importlib.import_module('VRM_Addon_for_Blender-release.editor.extension')
get_material_extension = ext_mod.get_material_extension

mat = bpy.data.materials["材质名"]
ext = get_material_extension(mat)
ext.mtoon1.enabled = True                    # MMDShaderDev 节点树会被替换成 MToon1
ext.mtoon1.pbr_metallic_roughness.base_color_texture.index.source = image
```

关键细节:
- `ext.mtoon1.enabled = True` 内部会调用 `vrm.convert_material_to_mtoon1`,对 `mmd_shader` 会触发 `reset_shader_node_group` 装载 MToon1 节点树。
- 必须在启用前保存旧的 `mmd_base_tex` image,否则转换后旧节点树会被替换、贴图引用要用新接口接回。
- 透明材质:旧 `Alpha < 0.001` 时,设置 `alpha_mode = 'BLEND'`,并把 `base_color_factor` 的 alpha 设为 0.0;否则设为 `OPAQUE`。
- `Body` 通常 `Double Sided = 1`,设置 `ext.mtoon1.double_sided = True`。

### 4. 补 VRM1 元信息

```python
arm = bpy.data.objects.get('Armature')  # 或第一个 ARMATURE
arm_ext = get_armature_extension(arm.data)
meta = arm_ext.vrm1.meta
if not meta.vrm_name:
    meta.vrm_name = '模型文件名'
meta.version = meta.version or '1.0'
```

### 5. 保存并导出

```python
bpy.ops.wm.save_as_mainfile(filepath=混合文件路径)
bpy.ops.export_scene.vrm(
    filepath=输出路径,
    armature_object_name=arm.name,
    check_existing=False,
)
```

### 6. 验证

- 重新用 Blender 导入导出的 VRM,确认每个材质节点树里有 TEX_IMAGE。
- 或解析 GLB JSON,确认 `materials[].pbrMetallicRoughness.baseColorTexture.index` 已经指向图片,且 `extensionsUsed` 里包含 `VRMC_materials_mtoon`。

## Blender 内置面板(一键使用)

插件目录: `addon/vrm_mtoon_fixer/`

安装方法:
1. Blender 菜单 `编辑 -> 偏好设置 -> 插件 -> 安装`,选择 `addon/vrm_mtoon_fixer/__init__.py` 所在目录打成的 zip,或直接把整个 `vrm_mtoon_fixer` 文件夹复制到 `scripts/addons/` 后在插件列表勾选 `VRM MToon Material Fixer`。
2. 3D 视图按 `N` 打开右侧边栏,切换到 `VRM Fixer` 标签页。
3. 面板上显示检测到的骨骼/网格,填写输出路径。
4. 点「转换材质为 VRM MToon1」只改材质;点「一键修复并导出 VRM」直接出 VRM。

注意:
- 操作是幂等的:如果材质已经是 MToon1,重复运行不会把透明/双面设置打回默认。
- 需要先在同一 Blender 里启用 `VRM_Addon_for_Blender-release`,插件本体只负责调用它的转换接口。

## 自动绑定 VRM1 表情(重要)

插件现在会在导出前自动执行 `vrm_fixer.auto_bind_expressions`:
- 读取当前 VRM1 模型的形状键(BlendShape)
- 自动把 `blink / aa / ih / ou / ee / oh / happy / angry / sad / relaxed / neutral / surprised` 等预设绑定到对应的形状键
- 这样导出的 VRM1 才有 `morphTargetBinds`, 否则 AI-Pet-Engine 等程序里眼睛和嘴巴不会动

面板里也有独立按钮「自动绑定 VRM1 表情」, 可手动先点一次查看绑定日志。

## Blender 插件导出模式(用户可自行选择)

插件面板 `VRM Fixer` 现在提供下拉选项:

- `直接导出(基础贴图)`: 只把 mmd_shader / MBTs 材质转成 MToon1 并接回 `mmd_base_tex`,不做额外卡渲参数映射。最接近最初插件的行为。
- `MBTs参数映射`: 把 MBTs-R2Y 的阴影颜色/阴影强度等参数映射到 MToon1,保留部分卡渲感。
- `MBTs烘焙导出(Cycles)`: 先用 Cycles 把 MBTs 卡渲效果烘焙成贴图,再导出 VRM;最接近 Blender 渲染效果。

操作方式:
1. 在右侧 N 面板选择「导出模式」。
2. 点「转换材质为 VRM MToon1」只改材质;点「一键修复并导出 VRM」转换并导出。

> 备注: 烘焙模式会调用 Cycles 渲染,耗时较长,请耐心等待。

## 一键脚本


`scripts/vrm_material_fixer.py` 是参数化脚本,支持:
- 输入 `.blend` 或 `.blend1`(自动复制恢复)
- 自动找骨骼和材质槽最多的网格
- 批量转换所有 mmd_shader 材质
- 自动补 VRM1 名称
- 自动保存固定版 `.blend` 并导出 `.vrm`

运行方式(Windows):

```bat
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --background --python "<本仓库路径>\scripts\vrm_material_fixer.py" -- "输入.blend1" "输出.vrm"
```

或者把 `.blend/.blend1` 文件拖到 `scripts\run_fix.bat` 上运行(脚本默认按 `D:\Blender Foundation\` 下的 4.5 / 3.6 找 Blender,改 `run_fix.bat` 第 4 行的 `BLENDER` 变量即可)。

## 依赖

- Blender 4.x(已验证 4.5.7;最低 3.6)
- [VRM Addon for Blender](https://github.com/saturday06/VRM-Addon-for-Blender)(v3.14.0)
- glTF 2.0 导出插件(Blender 自带)
- 输入模型已具备 VRM1 骨骼扩展;本技能只修材质,不修人体骨骼映射

## 从 Release 一键装插件

1. 下载 `vrm_mtoon_fixer-x.y.z.zip`
2. Blender `编辑 -> 偏好设置 -> 插件 -> 从磁盘安装`,选该 zip(不要解压)
3. 勾选 `VRM MToon Material Fixer`

仓库内重新出包: `python scripts/build_addon_zip.py`

## 成功案例

- 模型: SakurabaEma(厨居混客厅_by_白金制冷机)
- 症状: Blender 导出 VRM 后在 AI-Pet-Engine 里模型灰色
- 处理: 13 个材质槽全部从 `mmd_shader` 转换为 VRM MToon1,重接 `mmd_base_tex`
- 结果: 材质颜色恢复正常

## 常见坑

- `.blend` 是空的但 `.blend1` 有大文件 → 用 `.blend1`,不要用空 `.blend` 重新导出。
- `mmd_sphere_tex` 的 `Sphere Tex Fac` 为 0 时表示球面贴图不生效,不要强行接进 MToon。
- 导出后 VRM 名称为 `undefined` → 是 `meta.vrm_name` 为空,补名后再导出。
- 使用旧版 VRM Addon 时,模块名可能是 `VRM_Addon_for_Blender` 或 `io_scene_vrm`,脚本里已做兼容。
