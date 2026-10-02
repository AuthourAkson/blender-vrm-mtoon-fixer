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

## 烘焙 MMD 付与骨(修复「下半身/腿部僵住不动」)

MMD 模型大量使用「付与」(bone inherit): 例如腿部皮肤实际绑在 `足D.L` / `ひざD.L` 上,
而它们是靠约束跟随 `足.L` / `ひざ.L`。VRM/glTF **没有约束**,
导出后这些骨骼就永远停在绑定姿势 —— 表现就是「腿部/下半身绷直不动」,
**而在 Blender 里怎么看都正常**(Blender 会求值约束)。

判定方法: 在 Blender 里看 pose 骨骼的约束, 或看导出的 VRM 里骨骼的父子关系。
lothe / 洛茜 模型的实测:

```
足.L    parent=下半身  约束=[无]                 ← Unity 会驱动的人形骨骼
足D.L   parent=下半身  约束=[TRANSFORM->足.L]     ← 腿部皮肤绑的是这个
ひざD.L parent=足D.L   约束=[TRANSFORM->ひざ.L]
```

修法: 把它改成真实父子关系(`足D.L` 挂到 `足.L` 下、`ひざD.L` 挂到 `ひざ.L` 下),
并删掉那条约束(否则 Blender 里会双重变换)。静止世界坐标保持不变, 外观不变。

规则(避免破坏 VRM 人形层级):

- 跳过 `_` 开头的 mmd_tools 内部骨骼(本来就不导出)
- **跳过子树里含人形骨骼的骨骼**(例如 `肩C.L` 是 `腕.L` 的父级, 重挂会让
  VRM 插件报 `Couldn't assign "肩.L" bone to VRM Human Bone "Left Shoulder"` 而拒绝导出)
- 会形成环的不动

实测(PET_POSE_1 剪辑, Unity 6000.2.6f2):

| | 修复前 | 修复后 |
|---|---|---|
| `足D.L` 的父级 | `下半身` | **`足.L`** |
| 人形骨 `足.L` 转动幅度 | 3.9° | 3.9° |
| 蒙皮骨 `足D.L` 转动幅度 | 2.8°(只跟髋部, 腿自己的动作丢了) | **3.9°(与人形骨完全同步)** |
| 人形骨骼世界位置差 | — | 0.0000 mm |
| helper 骨静止世界位置差 | — | 0.0003 mm |

面板开关: `导出前烘焙 MMD 付与骨(修下半身僵住)`, 默认开。

## 骨骼朝向规范化(修复 Unity 应用里「头一直朝下」)

MMD 完整装备骨(`センター` / `グルーブ` / `腰` / `上半身1` / `上半身2` / `肩P` / `肩C` / 捩骨)里,
人形骨骼的**直接父级**常常是这种 helper 骨骼, 而且 helper 的静止朝向不一定竖直。
于是「人形骨骼相对父级的局部静止旋转」可能很大
(实测 lothe / Endmin 模型: `上半身` 相对 `腰` 偏 **42.72°**, `上半身2` 相对 `上半身1` 偏 12.93°)。

MATE ENGINE 这类 Unity 侧应用(见 `AvatarMouseTracking.DoSpine()`)会假定这个局部旋转≈0,
并且直接用 `Euler(0, yaw, 0)` **覆盖** spine 的局部旋转 —— 结果躯干连带头部整体前倾 42.7°,
表现为「**头一直朝下, 像盯着地面**」。SakurabaEma 那种"干净绑定"的模型
(spine 相对父级只偏 3°)看不出问题, 所以这个坑只在 MMD 完整装备骨模型上暴露。

插件用法:

- 面板勾选 `导出前规范化骨骼朝向`(默认开), 导出时自动处理;
- 面板按钮 `规范化骨骼朝向(Unity 应用兼容)`, 单独执行并在控制台打印每根骨骼的日志。

原理: 把 helper 父骨骼的静止朝向对齐到它的人形子骨骼, 让局部旋转≈0。
只动 helper(非人形)骨骼的**朝向**: 不动骨骼头部位置、不动人形骨骼自身朝向;
静止姿势下网格形变矩阵恒为单位阵, 所以**模型外观与 Unity 的人形重定向都不受影响**。

实测(lothe / Endmin):

| 检查项 | 处理前 | 处理后 |
|---|---|---|
| `spine` 相对 `腰` 的局部静止旋转 | 42.72° | **0.00°** |
| `chest` 相对 `上半身1` | 12.93° | **0.00°** |
| `hips` 相对 `全ての親` | 180.00° | **0.00°** |
| 人形骨骼世界位置最大差 | — | 0.001 mm |
| 人形骨骼世界朝向最大差 | — | 0.08° |
| 同一段应用代码造成的头部俯仰 | **-76.9°(盯着地面)** | **0.0°** |

命令行等价脚本: `scripts/normalize_rig_frames.py`

```bash
blender --background --python scripts/normalize_rig_frames.py -- "输入.blend" "输出.vrm"
```

## 常见坑

- `.blend` 是空的但 `.blend1` 有大文件 → 用 `.blend1`,不要用空 `.blend` 重新导出。
- `mmd_sphere_tex` 的 `Sphere Tex Fac` 为 0 时表示球面贴图不生效,不要强行接进 MToon。
- 导出后 VRM 名称为 `undefined` → 是 `meta.vrm_name` 为空,补名后再导出。
- 使用旧版 VRM Addon 时,模块名可能是 `VRM_Addon_for_Blender` 或 `io_scene_vrm`,脚本里已做兼容。
