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
