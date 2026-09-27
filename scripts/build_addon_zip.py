# -*- coding: utf-8 -*-
"""
打包 Blender 插件 zip
=====================

把 addon/vrm_mtoon_fixer/ 打成可以直接在 Blender 里
「编辑 -> 偏好设置 -> 插件 -> 从磁盘安装」的 zip。

用法:
    python scripts/build_addon_zip.py [输出目录]

默认输出到 dist/vrm_mtoon_fixer-<版本>.zip, 版本号从插件 bl_info 里读取。
"""
import os
import re
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(REPO_ROOT, "addon", "vrm_mtoon_fixer")
ADDON_NAME = "vrm_mtoon_fixer"


def read_version():
    init_py = os.path.join(ADDON_DIR, "__init__.py")
    with open(init_py, encoding="utf-8") as fh:
        source = fh.read()
    match = re.search(r'"version"\s*:\s*\(([^)]*)\)', source)
    if not match:
        return "0.0.0"
    parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
    return ".".join(parts)


def build(output_dir=None):
    version = read_version()
    output_dir = output_dir or os.path.join(REPO_ROOT, "dist")
    os.makedirs(output_dir, exist_ok=True)
    zip_path = os.path.join(output_dir, f"{ADDON_NAME}-{version}.zip")

    written = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if name.endswith((".pyc", ".pyo")):
                    continue
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, os.path.dirname(ADDON_DIR))
                # zip 内保留顶层目录名, Blender 才会正确安装成 vrm_mtoon_fixer 插件
                zf.write(abs_path, rel_path.replace(os.sep, "/"))
                written.append(rel_path.replace(os.sep, "/"))

    print(f"已生成 {zip_path} (版本 {version})")
    for name in written:
        print(f"  + {name}")
    return zip_path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    build(target)
