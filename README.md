# blender-vrm-mtoon-fixer

修复 Blender 导入 MMD/PMX 模型后导出 VRM 变成灰色、材质贴图丢失的问题,兼容 `mmd_shader` 与 MBTs-NG 卡渲(MBTs-R2Y)材质。

本仓库既可以作为智能体技能(Skill)使用,也附带可直接安装的 Blender 插件。

## 下载安装插件(推荐)

到 [Releases](https://github.com/AuthourAkson/blender-vrm-mtoon-fixer/releases/latest) 下载最新的 `vrm_mtoon_fixer-x.y.z.zip`:

1. Blender 菜单 `编辑 -> 偏好设置 -> 插件 -> 从磁盘安装`,选择该 zip。
   **不要解压,zip 本身就是要安装的包。**
2. 在插件列表搜索 `VRM MToon Material Fixer` 并勾选启用。
3. 确保同时启用了 `VRM_Addon_for_Blender-release`(本插件调用它的转换接口)。
4. 3D 视图按 `N` 键,侧边栏切到 `VRM Fixer` 标签页即可一键操作。

也可以把 `addon/vrm_mtoon_fixer/` 整个文件夹手动复制到 Blender 用户插件目录。

## 目录内容

- `SKILL.md`:技能说明和工作流程(给智能体读)
- `addon/vrm_mtoon_fixer/`:Blender 插件源码,装上后 3D 视图 N 面板有「VRM Fixer」一键按钮
- `scripts/vrm_material_fixer.py`:Blender Python 命令行批量脚本
- `scripts/run_fix.bat`:Windows 拖拽一键运行入口
- `scripts/build_addon_zip.py`:把插件打包成可安装 zip(出 Release 用)
- `scripts/gen_spring_bones.py`:从 MMD 物理自动生成 VRM 弹簧骨(头发/披风/尾巴), 已集成进插件
- `scripts/normalize_rig_frames.py`:把 MMD 装备骨的 helper 骨骼朝向规范化(修 Unity 侧应用里「头部一直朝下」), 已集成进插件面板

## 安装到其他智能体

1. 将整个 `blender-vrm-mtoon-fixer` 文件夹复制到智能体的 skills 目录下。
2. 智能体通过读取 `SKILL.md` 的 frontmatter(`name` / `description`)注册并触发本技能。
3. 需要实际修复时,用技能里的工作流程手动操作,或调用 `scripts/vrm_material_fixer.py`。

## 环境要求

- Blender 3.6 / 4.x(已在 4.5.7 验证)
- [VRM Addon for Blender](https://github.com/saturday06/VRM-Addon-for-Blender)(已在 v3.14.0 验证)
- 输入模型已具备 VRM1 骨骼扩展;本技能只修材质,不修人体骨骼映射

## 打包插件 zip

改了 `addon/vrm_mtoon_fixer/` 之后重新出包:

```bash
python scripts/build_addon_zip.py
```

会在 `dist/` 生成 `vrm_mtoon_fixer-<版本>.zip`,版本号取自插件里的 `bl_info["version"]`。

## 骨骼朝向规范化(Unity 应用兼容)

MMD 完整装备骨(`腰` / `上半身1` / `肩P` / `肩C` / 捩骨 …)会让某些人形骨骼的
「相对父级的局部静止旋转」很大(实测某模型 `上半身` 相对 `腰` 偏 42.72°)。
MATE ENGINE 等 Unity 侧应用会假定这个值是 0 并直接覆盖它, 结果躯干连带头部前倾
—— 表现就是「头部一直朝下」。

另有一个更常见的坑: MMD 的「付与」(骨骼继承)在 VRM 里不存在, 腿部皮肤绑定的 `足D.L`/`ひざD.L` 导出后会僵在绑定姿势(Blender 里正常、引擎里腿不动)。插件新增 `导出前烘焙 MMD 付与骨(修下半身僵住)`(默认开), 把它们改成真实父子关系。

插件面板勾选 `导出前规范化骨骼朝向`(默认开)即可在导出前自动对齐;
也可以点 `规范化骨骼朝向(Unity 应用兼容)` 单独执行。只动 helper 骨骼朝向,
模型外观与 Unity 人形重定向完全不变(实测世界位置差 0.001mm、朝向差 0.08°)。

## 弹簧骨(头发/披风/尾巴摆动)

MMD 靠刚体物理驱动头发/披风/尾巴, VRM 没有这个机制, 需要写成 `VRMC_springBone`。
插件读取 mmd_tools 的刚体数据自动生成: 动态刚体按骨骼层级连成链(分叉处切开,
每根骨骼只属于一条弹簧), 静态刚体变成球形碰撞体并按 MMD 碰撞组/掩码分配;
参数按部位给(尾巴/头发/帽子/披风/鞋带...), 并**沿链逐节递减硬度**, 长链才会一节节弯
而不是整根甩。实测某模型: 33 条弹簧 / 222 关节 / 32 碰撞体。
