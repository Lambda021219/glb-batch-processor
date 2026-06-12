# ################################################################
# GLB 自动化拓扑与烘焙工具 / GLB Auto-Retopo & Bake
# ================================================================
# 批量处理高模 GLB 文件：Quad Remesher 重拓扑 → 智能 UV →
# Cycles GPU 烘焙漫射/法线贴图 → 按模型分文件夹导出。
#
# 安装：Blender → Edit → Preferences → Add-ons → Install → 选 zip
# 位置：3D Viewport → Sidebar (N键) → "GLB处理" 标签页
# 依赖：Quad Remesher 1.23+ | Blender 4.0+
# ================================================================
# ################################################################

bl_info = {
    "name": "GLB 自动化拓扑与烘焙工具 / GLB Auto-Retopo & Bake",
    "author": "GLB Batch Processor Contributors",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N键) > GLB处理",
    "description": (
        "批量处理高模GLB：Quad Remesher重拓扑、自动UV、Cycles GPU烘焙"
        "漫射/法线贴图，导出为GLB/FBX/OBJ/USD/STL多格式，按模型子文件夹整理\n"
        "Batch GLB processor: Quad Remesher retopo, auto UV, "
        "Cycles GPU bake (Diffuse + Normal), export to GLB/FBX/OBJ/USD/STL"
    ),
    "doc_url": "https://github.com/Lambda021219/glb-batch-processor",
    "tracker_url": "https://github.com/your-username/glb-batch-processor/issues",
    "category": "Object",
    "support": "COMMUNITY",
}

import bpy
import os
import sys
import glob as glob_module
import time
import datetime
import traceback
import subprocess


# ============================================================
# 日志 / Logging
# ============================================================

_log_fp = None
_log_path = ""


def log(msg: str):
    """同时输出到 Blender 控制台和日志文件"""
    global _log_fp, _log_path
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    sys.stdout.flush()
    try:
        if _log_fp is None:
            # 日志文件放在输出目录下
            scene = bpy.context.scene
            out_dir = _log_path or scene.glb_settings.input.output_folder or os.path.expanduser("~")
            os.makedirs(out_dir, exist_ok=True)
            _log_fp = open(os.path.join(out_dir, "batch_process_log.txt"), 'w', encoding='utf-8')
        _log_fp.write(line + '\n')
        _log_fp.flush()
    except Exception:
        pass


def close_log():
    global _log_fp
    if _log_fp:
        _log_fp.close()
        _log_fp = None


def popup(msg: str, title: str = "提示 / Info", icon: str = 'INFO'):
    """弹出 Blender 原生提示框"""
    def draw(menu, ctx):
        for line in msg.split('\n'):
            menu.layout.label(text=line)
    try:
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    except Exception:
        pass


# ============================================================
# 全局处理状态 / Process State (单例)
# ============================================================

class GLB_ProcessState:
    """单个批次处理的状态机。同一时间只能运行一个批次。"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.files: list = []
        self.idx: int = 0
        self.stage: str = 'idle'
        self.high_name: str = ''
        self.low_name: str = ''
        self.base: str = ''
        self.ok: list = []
        self.fail: list = []
        self.t0: float = 0.0
        self.wait_count: int = 0
        self.objs_before: set = set()
        self.timer_running: bool = False
        self.gpu_ok: bool = False
        self.saved_diffuse_path: str = ''


STATE = GLB_ProcessState()


# ============================================================
# PropertyGroup 参数组
# ============================================================

class GLB_InputProperties(bpy.types.PropertyGroup):
    """输入与输出路径"""
    input_folder: bpy.props.StringProperty(
        name="输入文件夹 / Input",
        subtype='DIR_PATH',
        description="存放高模GLB文件的文件夹"
    )  # type: ignore
    output_folder: bpy.props.StringProperty(
        name="输出文件夹 / Output",
        subtype='DIR_PATH',
        description="处理后文件输出根目录（每个模型自动创建子文件夹）"
    )  # type: ignore


class GLB_RemeshProperties(bpy.types.PropertyGroup):
    """Quad Remesher 重拓扑参数"""
    quad_count: bpy.props.IntProperty(
        name="目标面数 / Target Quads",
        default=5000, min=100, max=1000000,
        description="Quad Remesher 重拓扑的目标四边形数量"
    )  # type: ignore
    adapt_quad_count: bpy.props.BoolProperty(
        name="自适应面数 / Adapt Quads",
        default=False,
        description="让 Quad Remesher 根据模型复杂度自动调整目标面数"
    )  # type: ignore
    timeout_seconds: bpy.props.IntProperty(
        name="超时 / Timeout (s)",
        default=300, min=30, max=3600,
        description="等待 Quad Remesher 完成的最大时间（秒）"
    )  # type: ignore


class GLB_BakeProperties(bpy.types.PropertyGroup):
    """烘焙参数"""
    resolution: bpy.props.EnumProperty(
        name="贴图分辨率 / Resolution",
        items=[
            ('256',  "256×256",   ""),
            ('512',  "512×512",   ""),
            ('1024', "1024×1024", ""),
            ('2048', "2048×2048", ""),
            ('4096', "4096×4096", ""),
        ],
        default='1024',
        description="烘焙贴图的分辨率"
    )  # type: ignore
    cage_extrusion: bpy.props.FloatProperty(
        name="包裹笼挤出 / Cage Extrusion",
        default=0.1, min=0.0, max=1.0, step=0.01,
        description="烘焙时 Cage 向外挤出的距离（米）"
    )  # type: ignore
    bake_normal: bpy.props.BoolProperty(
        name="同时烘焙法线贴图 / Bake Normal Map",
        default=False,
        description="漫射烘焙完成后，额外烘焙一张法线贴图"
    )  # type: ignore
    save_textures_separate: bpy.props.BoolProperty(
        name="单独保存贴图 / Save Textures Separately",
        default=True,
        description="将烘焙贴图另存为独立图片文件到模型子文件夹中"
    )  # type: ignore
    image_format: bpy.props.EnumProperty(
        name="贴图格式 / Image Format",
        items=[
            ('PNG',  "PNG",  "无损压缩，文件较大"),
            ('JPEG', "JPEG", "有损压缩，文件较小"),
        ],
        default='PNG',
        description="保存烘焙贴图的文件格式"
    )  # type: ignore


class GLB_ExportProperties(bpy.types.PropertyGroup):
    """导出参数"""
    export_format: bpy.props.EnumProperty(
        name="导出格式 / Format",
        items=[
            ('GLB',           "GLB (Binary)",          "单个二进制文件，含几何与贴图"),
            ('GLTF_SEPARATE', "glTF Separate",         "分离 .gltf + .bin + 贴图文件"),
            ('FBX',           "FBX",                   "Autodesk FBX，广泛兼容各DCC"),
            ('OBJ',           "OBJ (+MTL)",            "Wavefront OBJ，附带 MTL 材质库"),
            ('USD',           "USD / USDA",            "Universal Scene Description"),
            ('STL',           "STL",                   "纯几何体，3D打印常用"),
        ],
        default='GLB',
        description="导出格式。FBX/OBJ/STL 无法内嵌贴图，请开启「单独保存贴图」"
    )  # type: ignore
    flat_output: bpy.props.BoolProperty(
        name="平铺输出（不建子文件夹） / Flat Output",
        default=False,
        description="所有GLB直接输出到根目录，不创建以模型名命名的子文件夹"
    )  # type: ignore
    close_when_done: bpy.props.BoolProperty(
        name="完成后自动关闭 Blender / Auto-Close",
        default=False,
        description="所有文件处理完毕后自动退出 Blender"
    )  # type: ignore


class GLB_Settings(bpy.types.PropertyGroup):
    """顶层设置容器"""
    input: bpy.props.PointerProperty(type=GLB_InputProperties)
    remesh: bpy.props.PointerProperty(type=GLB_RemeshProperties)
    bake: bpy.props.PointerProperty(type=GLB_BakeProperties)
    export: bpy.props.PointerProperty(type=GLB_ExportProperties)


# ============================================================
# 辅助函数 / Helpers
# ============================================================

def clear_all():
    """彻底清空场景（在文件之间调用，避免命名冲突和孤立数据残留）"""
    if STATE.timer_running:
        return

    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    try:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
    except Exception:
        pass

    # 重置 Cycles 烘焙状态
    try:
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.bake_type = 'COMBINED'
    except Exception:
        pass

    for _ in range(3):
        for coll in [bpy.data.meshes, bpy.data.materials, bpy.data.images,
                     bpy.data.textures, bpy.data.lights, bpy.data.cameras,
                     bpy.data.objects, bpy.data.curves, bpy.data.armatures]:
            for item in list(coll):
                if item.users == 0:
                    try:
                        coll.remove(item)
                    except Exception:
                        pass
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    except Exception:
        pass
    log("  场景已清空 / Scene cleared")


def get_mesh(name: str):
    """按名称安全获取网格对象"""
    o = bpy.data.objects.get(name)
    return o if (o and o.type == 'MESH') else None


def detect_gpu():
    """检测最佳 GPU 后端"""
    if STATE.gpu_ok:
        return
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for backend in ['OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI']:
        try:
            prefs.compute_device_type = backend
            log(f"  GPU 后端尝试: {backend}")
            break
        except Exception:
            continue
    prefs.get_devices()
    for d in prefs.devices:
        d.use = (d.type != 'CPU')
        if d.use:
            log(f"  设备: {d.name}")
    STATE.gpu_ok = True


def update_progress():
    """根据当前 STATE 更新 Scene 进度属性，触发 UI 刷新"""
    scene = bpy.context.scene
    total = len(STATE.files)
    current = STATE.idx
    stage = STATE.stage

    if total == 0:
        scene.glb_progress_pct = 0
        scene.glb_progress_text = "就绪 / Ready"
        return

    stage_weight = {
        'import': 0.10, 'remesh_wait': 0.35, 'uv_mat': 0.10,
        'baking_diffuse': 0.20, 'baking_normal': 0.15, 'export': 0.10,
    }
    per_file = 100.0 / total
    done_pct = (current / total) * 100.0
    sw = stage_weight.get(stage, 0)
    pct = min(done_pct + sw * per_file, 100.0)

    scene.glb_progress_pct = pct
    scene.glb_progress_text = (
        f"{STATE.base} ({current + 1}/{total}) · "
        f"{_stage_label(stage)}"
    )
    scene.glb_ok_count = len(STATE.ok)
    scene.glb_fail_count = len(STATE.fail)


def _stage_label(stage: str) -> str:
    labels = {
        'import': "导入中...",
        'remesh_wait': "重拓扑中...",
        'uv_mat': "UV/材质准备...",
        'baking_diffuse': "烘焙漫射...",
        'baking_normal': "烘焙法线...",
        'export': "导出中...",
        'done': "完成",
        'cancelled': "已取消",
    }
    return labels.get(stage, stage)


def _open_folder(path: str):
    """跨平台打开文件夹（Win/Mac/Linux）"""
    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
    except Exception as e:
        log(f"  ⚠ 无法打开文件夹: {e}")


def resolve_output_dir() -> str:
    """返回当前模型的输出目录（考虑平铺模式）"""
    settings = bpy.context.scene.glb_settings
    root = settings.input.output_folder or settings.input.input_folder or os.path.expanduser("~")
    if settings.export.flat_output:
        return root
    else:
        d = os.path.join(root, STATE.base)
        os.makedirs(d, exist_ok=True)
        return d


# ============================================================
# 阶段函数 / Stage Functions
# ============================================================

def do_import():
    """导入 GLB (merge_vertices=True) + 启动 Quad Remesher"""
    fp = STATE.files[STATE.idx]
    STATE.base = os.path.splitext(os.path.basename(fp))[0]
    settings = bpy.context.scene.glb_settings

    print("\n" + "─" * 50)
    log(f"📦 [{STATE.idx + 1}/{len(STATE.files)}] {STATE.base}")
    print("─" * 50)
    log("导入 GLB (merge_vertices=True) / Importing GLB")

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=fp, merge_vertices=True, loglevel=20)
    after = set(bpy.data.objects)

    meshes = [o for o in (after - before) if o.type == 'MESH']
    log(f"  导入 {len(meshes)} 个网格 / {len(meshes)} meshes imported")

    if not meshes:
        raise RuntimeError("未找到网格 / No mesh found")

    if len(meshes) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        high = bpy.context.active_object
    else:
        high = meshes[0]

    high.name = STATE.base
    STATE.high_name = high.name
    log(f"  高模: {high.name} ({len(high.data.vertices)} 顶点, {len(high.data.polygons)} 面)")

    # 补一次 merge（保险）
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = high
    high.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    v0 = len(high.data.vertices)
    try:
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
    except Exception:
        bpy.ops.mesh.merge_by_distance(threshold=0.0001)
    v1 = len(high.data.vertices)
    bpy.ops.object.mode_set(mode='OBJECT')
    if v0 != v1:
        log(f"  额外合并 {v0 - v1} 顶点 / merged vertices")

    # ── 启动 Quad Remesher ──
    log("启动 Quad Remesher...")
    qr = bpy.context.scene.qremesher
    qr.target_count = settings.remesh.quad_count
    qr.adapt_quad_count = settings.remesh.adapt_quad_count
    qr.hide_input = True
    log(f"  target_count = {qr.target_count}")

    STATE.objs_before = set(bpy.data.objects)
    STATE.wait_count = 0

    bpy.ops.object.select_all(action='DESELECT')
    high.select_set(True)
    bpy.context.view_layer.objects.active = high
    bpy.ops.qremesher.remesh()
    log("  外部引擎已启动，等待重拓扑完成... / External engine started, waiting...")

    STATE.stage = 'remesh_wait'
    update_progress()


def do_remesh_wait():
    """轮询 Quad Remesher 完成"""
    settings = bpy.context.scene.glb_settings
    STATE.wait_count += 1

    cur = set(bpy.data.objects)
    new = [o for o in (cur - STATE.objs_before)
           if o.type == 'MESH' and o.name != STATE.high_name]

    if new:
        low = new[0]
        STATE.low_name = low.name
        log(f"  ✓ 重拓扑完成! ({STATE.wait_count} 次轮询) / Remesh done")
        log(f"  低模: {low.name} ({len(low.data.vertices)} 顶点, {len(low.data.polygons)} 面)")

        low.name = f"{STATE.base}_low"
        STATE.low_name = low.name
        log(f"  命名: {low.name}")

        STATE.stage = 'uv_mat'
        update_progress()
        return

    max_wait = settings.remesh.timeout_seconds * 2  # 每 0.5 秒一次
    if STATE.wait_count > max_wait:
        raise RuntimeError(f"Quad Remesher 超时 ({settings.remesh.timeout_seconds}秒) / Timed out")

    if STATE.wait_count % 20 == 0:
        log(f"  等待中... ({STATE.wait_count // 2}秒)")
    update_progress()


def do_uv_mat():
    """UV 智能投射 + 创建烘焙材质"""
    settings = bpy.context.scene.glb_settings
    low = get_mesh(STATE.low_name)
    if low is None:
        raise RuntimeError(f"找不到低模: {STATE.low_name}")

    log("UV 智能投射 / Smart UV Project")
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = low
    low.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    res = int(settings.bake.resolution)
    log(f"创建材质 + {res}×{res} 纹理 / Creating material + texture")
    mat = bpy.data.materials.new(name=f"{low.name}_Material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # BSDF
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 300)
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (300, 300)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    # 漫射贴图节点
    tex_diffuse = nodes.new(type='ShaderNodeTexImage')
    tex_diffuse.name = "BakeTarget_Diffuse"
    tex_diffuse.label = "漫射贴图 / Diffuse"
    tex_diffuse.location = (-400, 300)
    img_diffuse = bpy.data.images.new(
        name=f"{STATE.base}_Diffuse_Img",
        width=res, height=res, alpha=False, float_buffer=False
    )
    tex_diffuse.image = img_diffuse

    # 如果开启法线，预先创建法线节点
    if settings.bake.bake_normal:
        tex_normal = nodes.new(type='ShaderNodeTexImage')
        tex_normal.name = "BakeTarget_Normal"
        tex_normal.label = "法线贴图 / Normal"
        tex_normal.location = (-400, -100)
        img_normal = bpy.data.images.new(
            name=f"{STATE.base}_Normal_Img",
            width=res, height=res, alpha=False, float_buffer=False
        )
        tex_normal.image = img_normal

    # 应用材质
    if low.data.materials:
        low.data.materials[0] = mat
    else:
        low.data.materials.append(mat)

    # 激活漫射贴图节点
    nodes.active = tex_diffuse
    for n in nodes:
        n.select = False
    tex_diffuse.select = True
    log("  纹理节点已激活 / Texture node activated")

    STATE.stage = 'baking_diffuse'
    update_progress()


def do_baking_diffuse():
    """Cycles GPU 漫射烘焙"""
    high = get_mesh(STATE.high_name)
    low = get_mesh(STATE.low_name)
    if high is None or low is None:
        raise RuntimeError("找不到模型 / Model not found")

    settings = bpy.context.scene.glb_settings
    log("Cycles GPU 漫射烘焙 / Diffuse baking...")
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'

    # GPU 检测
    try:
        detect_gpu()
    except Exception:
        log("  ⚠ GPU 检测失败，使用 CPU / GPU detection failed, using CPU")
    try:
        scene.cycles.device = 'GPU'
    except Exception:
        pass

    # 烘焙参数
    scene.cycles.bake_type = 'DIFFUSE'
    rb = scene.render.bake
    rb.use_pass_indirect = False
    rb.use_pass_direct = False
    rb.use_pass_color = True
    rb.use_selected_to_active = True
    rb.cage_extrusion = settings.bake.cage_extrusion

    # 取消隐藏
    high.hide_set(False)
    high.hide_viewport = False
    low.hide_set(False)
    low.hide_viewport = False

    # 先选低模再选高模（低模为活动物体）
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    high.select_set(True)
    bpy.context.view_layer.objects.active = low

    # 确保漫射贴图节点激活
    if low.active_material and low.active_material.use_nodes:
        for n in low.active_material.node_tree.nodes:
            if n.name == "BakeTarget_Diffuse":
                low.active_material.node_tree.nodes.active = n
                n.select = True
                break

    log("  ⏳ 漫射烘焙中... / Baking diffuse...")
    bpy.ops.object.bake(type='DIFFUSE')
    log("  ✓ 漫射烘焙完成 / Diffuse bake done")

    # 保存漫射贴图
    if settings.bake.save_textures_separate:
        _save_baked_image("BakeTarget_Diffuse", f"{STATE.base}_diffuse")

    # 决定下一步
    if settings.bake.bake_normal:
        STATE.stage = 'baking_normal'
    else:
        STATE.stage = 'export'
    update_progress()


def do_baking_normal():
    """Cycles GPU 法线烘焙"""
    high = get_mesh(STATE.high_name)
    low = get_mesh(STATE.low_name)
    if high is None or low is None:
        raise RuntimeError("找不到模型 / Model not found")

    settings = bpy.context.scene.glb_settings
    log("Cycles GPU 法线烘焙 / Normal baking...")
    scene = bpy.context.scene

    # 设置法线烘焙
    scene.cycles.bake_type = 'NORMAL'
    rb = scene.render.bake
    rb.use_selected_to_active = True
    rb.cage_extrusion = settings.bake.cage_extrusion

    # 确保选中正确
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    high.select_set(True)
    bpy.context.view_layer.objects.active = low

    # 激活法线贴图节点
    if low.active_material and low.active_material.use_nodes:
        for n in low.active_material.node_tree.nodes:
            if n.name == "BakeTarget_Normal":
                low.active_material.node_tree.nodes.active = n
                for nn in low.active_material.node_tree.nodes:
                    nn.select = False
                n.select = True
                break

    log("  ⏳ 法线烘焙中... / Baking normal...")
    bpy.ops.object.bake(type='NORMAL')
    log("  ✓ 法线烘焙完成 / Normal bake done")

    # 保存法线贴图
    if settings.bake.save_textures_separate:
        _save_baked_image("BakeTarget_Normal", f"{STATE.base}_normal")

    STATE.stage = 'export'
    update_progress()


def do_export():
    """连接贴图 + 按格式导出"""
    settings = bpy.context.scene.glb_settings
    low = get_mesh(STATE.low_name)
    if low is None:
        raise RuntimeError(f"找不到低模: {STATE.low_name}")

    # 连接贴图到材质（对所有格式统一处理）
    if low.active_material and low.active_material.use_nodes:
        nodes = low.active_material.node_tree.nodes
        links = low.active_material.node_tree.links
        tex_diffuse = bsdf = tex_normal = None
        for n in nodes:
            if n.name == "BakeTarget_Diffuse":
                tex_diffuse = n
            elif n.name == "BakeTarget_Normal":
                tex_normal = n
            elif n.type == 'BSDF_PRINCIPLED':
                bsdf = n

        if tex_diffuse and bsdf:
            if not any(
                l.from_node == tex_diffuse and l.to_node == bsdf for l in links
            ):
                links.new(tex_diffuse.outputs['Color'], bsdf.inputs['Base Color'])
                log("  漫射贴图 → 基础色 / Diffuse → Base Color ✓")

        if tex_normal and bsdf and settings.bake.bake_normal:
            if not any(
                l.from_node == tex_normal for l in links
            ):
                normal_map = nodes.new(type='ShaderNodeNormalMap')
                normal_map.location = (-200, -100)
                links.new(tex_normal.outputs['Color'], normal_map.inputs['Color'])
                links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])
                log("  法线贴图 → Normal Map → BSDF ✓")

    # 选中低模
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    bpy.context.view_layer.objects.active = low

    # 格式分派
    export_fmt = settings.export.export_format
    out_dir = resolve_output_dir()
    out_path = ""

    if export_fmt == 'GLB':
        out_path = _export_glb(low, out_dir)
    elif export_fmt == 'GLTF_SEPARATE':
        out_path = _export_gltf_separate(low, out_dir)
    elif export_fmt == 'FBX':
        out_path = _export_fbx(low, out_dir)
    elif export_fmt == 'OBJ':
        out_path = _export_obj(low, out_dir)
    elif export_fmt == 'USD':
        out_path = _export_usd(low, out_dir)
    elif export_fmt == 'STL':
        out_path = _export_stl(low, out_dir)
    else:
        raise RuntimeError(f"不支持的导出格式: {export_fmt}")

    log(f"✅ {STATE.base} 完成 → {os.path.basename(out_path)} / Done")
    STATE.ok.append(out_path)

    # 下一个文件或完成
    STATE.idx += 1
    if STATE.idx < len(STATE.files):
        clear_all()
        STATE.high_name = ''
        STATE.low_name = ''
        STATE.base = ''
        STATE.wait_count = 0
        STATE.objs_before = set()
        STATE.stage = 'import'
        update_progress()
    else:
        STATE.stage = 'done'
        update_progress()


def _save_baked_image(node_name: str, file_stem: str):
    """将指定 TEX_IMAGE 节点的烘焙结果保存到磁盘"""
    settings = bpy.context.scene.glb_settings
    low = get_mesh(STATE.low_name)
    if low is None:
        return

    mat = low.active_material
    if not mat or not mat.use_nodes:
        return

    for n in mat.node_tree.nodes:
        if n.name == node_name and n.image:
            out_dir = resolve_output_dir()
            fmt = settings.bake.image_format
            ext = 'png' if fmt == 'PNG' else 'jpg'
            img_path = os.path.join(out_dir, f"{file_stem}.{ext}")

            img = n.image
            img.file_format = fmt
            try:
                img.filepath_raw = img_path
                img.save()
            except Exception:
                # 如果 save() 失败，尝试 save_render()
                try:
                    img.save_render(img_path)
                except Exception:
                    log(f"  ⚠ 贴图保存失败: {file_stem}.{ext}")
                    return

            log(f"  贴图已保存: {os.path.basename(img_path)} / Texture saved")
            return


# ============================================================
# 格式导出辅助函数 / Export Helpers (per format)
# ============================================================

def _export_glb(low, out_dir: str) -> str:
    """导出 GLB (Binary glTF)"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low.glb")
    log(f"  导出 GLB: {os.path.basename(out_path)}")
    bpy.ops.export_scene.gltf(
        filepath=out_path, use_selection=True, export_format='GLB',
        export_apply=True, export_image_format='AUTO',
        export_texcoords=True, export_normals=True, export_materials='EXPORT')
    return out_path


def _export_gltf_separate(low, out_dir: str) -> str:
    """导出 glTF Separate (.gltf + .bin + textures)"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low")  # .gltf 自动追加
    log(f"  导出 glTF Separate: {os.path.basename(out_path)}.gltf")
    bpy.ops.export_scene.gltf(
        filepath=out_path, use_selection=True, export_format='GLTF_SEPARATE',
        export_apply=True, export_image_format='AUTO',
        export_texcoords=True, export_normals=True, export_materials='EXPORT')
    return out_path + '.gltf'


def _export_fbx(low, out_dir: str) -> str:
    """导出 FBX"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low.fbx")
    log(f"  导出 FBX: {os.path.basename(out_path)}")
    bpy.ops.export_scene.fbx(
        filepath=out_path, use_selection=True,
        apply_unit_scale=True, apply_scale_options='FBX_SCALE_NONE',
        bake_space_transform=False, object_types={'MESH'},
        use_mesh_modifiers=True, add_leaf_bones=False,
        path_mode='COPY', embed_textures=False)
    return out_path


def _export_obj(low, out_dir: str) -> str:
    """导出 OBJ + MTL"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low.obj")
    log(f"  导出 OBJ: {os.path.basename(out_path)}")
    bpy.ops.export_scene.obj(
        filepath=out_path, use_selection=True,
        apply_modifiers=True,
        export_materials=True, export_uv=True, export_normals=True,
        path_mode='RELATIVE')
    return out_path


def _export_usd(low, out_dir: str) -> str:
    """导出 USDA (文本格式，兼容性好)"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low.usda")
    log(f"  导出 USD: {os.path.basename(out_path)}")
    bpy.ops.wm.usd_export(
        filepath=out_path, selection_only=True,
        export_materials=True, export_uvmaps=True, export_normals=True,
        convert_orientation=False, export_textures=False)
    return out_path


def _export_stl(low, out_dir: str) -> str:
    """导出 STL（纯几何，无材质/贴图）"""
    out_path = os.path.join(out_dir, f"{STATE.base}_low.stl")
    log(f"  导出 STL: {os.path.basename(out_path)}")
    bpy.ops.export_mesh.stl(
        filepath=out_path, use_selection=True,
        apply_modifiers=True, ascii=False)
    return out_path


# ============================================================
# 阶段函数注册表
# ============================================================

STAGE_FUNCS = {
    'import':          do_import,
    'remesh_wait':     do_remesh_wait,
    'uv_mat':          do_uv_mat,
    'baking_diffuse':  do_baking_diffuse,
    'baking_normal':   do_baking_normal,
    'export':          do_export,
}


# ============================================================
# 单一持续定时器 / Timer + 状态机
# ============================================================

def timer_tick():
    """
    每 0.5 秒触发一次，根据 STATE.stage 执行对应阶段。
    返回正数 = 继续调度，返回 None = 停止。
    """
    stage = STATE.stage

    # 终止状态
    if stage in ('idle', 'done', 'cancelled'):
        _finalize()
        return None

    # 安全检查：如果场景异常，停止
    try:
        _ = bpy.context.scene
    except Exception:
        return None

    func = STAGE_FUNCS.get(stage)
    if func is None:
        log(f"❌ 未知阶段: {stage} / Unknown stage")
        return None

    try:
        func()
    except Exception as e:
        log(f"❌ [{STATE.base}] 阶段 '{stage}' 失败: {e}")
        log(traceback.format_exc())
        STATE.fail.append((STATE.base or STATE.files[STATE.idx], str(e)))
        # 跳到下一个文件
        STATE.idx += 1
        if STATE.idx < len(STATE.files):
            try:
                clear_all()
            except Exception:
                pass
            STATE.high_name = ''
            STATE.low_name = ''
            STATE.base = ''
            STATE.wait_count = 0
            STATE.objs_before = set()
            STATE.stage = 'import'
            update_progress()
            return 0.5
        else:
            STATE.stage = 'done'
            update_progress()
            return 0.5

    # 处理完成
    if STATE.stage == 'done':
        _finalize()
        return None

    return 0.5


def _finalize():
    """批次完成 / 取消后的清理+汇总"""
    scene = bpy.context.scene
    settings = scene.glb_settings
    STATE.timer_running = False

    elapsed = time.time() - STATE.t0 if STATE.t0 > 0 else 0
    log("\n" + "=" * 50)
    if STATE.stage == 'cancelled':
        log(f"  ⏹ 用户取消 / Cancelled by user")
    log(f"  全部完成! 耗时 {int(elapsed // 60)}分{int(elapsed % 60)}秒")
    log(f"  成功: {len(STATE.ok)}  失败: {len(STATE.fail)}")
    if STATE.ok:
        log("  输出:")
        for p in STATE.ok:
            log(f"    → {p}")
    if STATE.fail:
        log("  失败:")
        for n, e in STATE.fail:
            log(f"    ✗ {n}: {e}")
    log("=" * 50)

    popup(
        f"批量处理完成!\n成功: {len(STATE.ok)}  失败: {len(STATE.fail)}\n"
        f"耗时: {int(elapsed // 60)}分{int(elapsed % 60)}秒\n"
        f"Batch done! OK:{len(STATE.ok)} Fail:{len(STATE.fail)}",
        "处理完毕 / Done", 'INFO'
    )

    scene.glb_is_running = False
    scene.glb_progress_pct = 100.0
    scene.glb_progress_text = "完成 / Done"
    scene.glb_ok_count = len(STATE.ok)
    scene.glb_fail_count = len(STATE.fail)

    close_log()
    STATE.reset()

    # 自动关闭
    if settings.export.close_when_done and STATE.stage != 'cancelled':
        log("正在关闭 Blender... / Closing Blender...")
        bpy.ops.wm.quit_blender()


# ============================================================
# Operator 类
# ============================================================

class GLB_OT_BatchProcess(bpy.types.Operator):
    """批量处理输入文件夹中的所有 GLB 文件"""
    bl_idname = "glb.batch_process"
    bl_label = "开始批量处理 / Start Batch"
    bl_description = "处理输入文件夹中的所有 GLB 文件 / Process all GLB files"

    def execute(self, context):
        global _log_path
        scene = context.scene
        settings = scene.glb_settings

        # 校验输入文件夹
        folder = settings.input.input_folder
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "请选择有效的输入文件夹 / Invalid input folder")
            return {'CANCELLED'}

        # 校验 Quad Remesher — 直接检测操作符是否存在（比查addon名更可靠）
        if not hasattr(bpy.ops.qremesher, 'remesh'):
            self.report({'ERROR'}, "请先安装并启用 Quad Remesher 插件！")
            popup("未检测到 Quad Remesher 插件!\n"
                  "请先安装: https://exoside.com/quadremesher/\n"
                  "Quad Remesher add-on not found!",
                  "错误 / Error", 'ERROR')
            return {'CANCELLED'}

        # 收集文件
        files = sorted(set(
            glob_module.glob(os.path.join(folder, "*.glb")) +
            glob_module.glob(os.path.join(folder, "*.GLB"))
        ))
        if not files:
            self.report({'ERROR'}, "未找到 GLB 文件 / No GLB files found")
            return {'CANCELLED'}

        # 确保输出目录存在
        out_dir = settings.input.output_folder or os.path.join(folder, "输出")
        os.makedirs(out_dir, exist_ok=True)
        _log_path = out_dir

        # 初始化状态
        STATE.reset()
        STATE.files = files
        STATE.idx = 0
        STATE.stage = 'import'
        STATE.ok = []
        STATE.fail = []
        STATE.t0 = time.time()
        STATE.timer_running = True
        STATE.gpu_ok = False

        scene.glb_is_running = True
        scene.glb_progress_pct = 0.0
        scene.glb_progress_text = f"开始处理 {len(files)} 个文件..."
        scene.glb_ok_count = 0
        scene.glb_fail_count = 0

        log("=" * 50)
        log("  GLB 自动化拓扑与烘焙 / GLB Auto-Retopo & Bake")
        log(f"  Blender {bpy.app.version_string}")
        log("=" * 50)
        log(f"输入: {folder}")
        log(f"输出: {out_dir}")
        log(f"找到 {len(files)} 个文件:")
        for i, f in enumerate(files, 1):
            log(f"  [{i}] {os.path.basename(f)}")
        log(f"\n定时器已注册 (每0.5秒触发)")
        log("请勿操作 Blender，等待完成提示...\n")

        clear_all()
        bpy.app.timers.register(timer_tick, first_interval=0.3)
        self.report({'INFO'}, f"已启动，共 {len(files)} 个文件。请勿操作 Blender！")
        return {'FINISHED'}


class GLB_OT_StopBatch(bpy.types.Operator):
    """停止当前正在运行的批量处理"""
    bl_idname = "glb.stop_batch"
    bl_label = "停止处理 / Stop"
    bl_description = "中止当前批量处理（已完成的不受影响）"

    def execute(self, context):
        if STATE.timer_running:
            STATE.stage = 'cancelled'
            scene = context.scene
            scene.glb_is_running = False
            scene.glb_progress_text = "已取消 / Cancelled"
            log("⏹ 用户手动停止 / User stopped the batch")
            self.report({'INFO'}, "已停止 / Stopped")
        return {'FINISHED'}


class GLB_OT_SingleProcess(bpy.types.Operator):
    """选择单个 GLB 文件进行处理"""
    bl_idname = "glb.single_process"
    bl_label = "处理单个文件... / Process Single File"
    bl_description = "选择并处理单个 GLB 文件 / Pick and process one GLB"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore
    filter_glob: bpy.props.StringProperty(default="*.glb;*.GLB", options={'HIDDEN'})  # type: ignore

    def execute(self, context):
        global _log_path
        settings = context.scene.glb_settings

        # 校验 Quad Remesher — 直接检测操作符是否存在
        if not hasattr(bpy.ops.qremesher, 'remesh'):
            self.report({'ERROR'}, "请先安装并启用 Quad Remesher 插件！")
            return {'CANCELLED'}

        fp = self.filepath
        if not fp or not os.path.isfile(fp):
            self.report({'ERROR'}, "请选择有效的 GLB 文件")
            return {'CANCELLED'}

        out_dir = settings.input.output_folder or os.path.join(os.path.dirname(fp), "输出")
        os.makedirs(out_dir, exist_ok=True)
        _log_path = out_dir

        STATE.reset()
        STATE.files = [fp]
        STATE.idx = 0
        STATE.stage = 'import'
        STATE.ok = []
        STATE.fail = []
        STATE.t0 = time.time()
        STATE.timer_running = True
        STATE.gpu_ok = False

        scene = context.scene
        scene.glb_is_running = True
        scene.glb_progress_pct = 0.0
        scene.glb_progress_text = f"处理: {os.path.basename(fp)}"
        scene.glb_ok_count = 0
        scene.glb_fail_count = 0

        log("=" * 50)
        log("  GLB 单文件处理 / Single File Process")
        log(f"  文件: {os.path.basename(fp)}")
        log("=" * 50)

        clear_all()
        bpy.app.timers.register(timer_tick, first_interval=0.3)
        self.report({'INFO'}, f"开始处理 {os.path.basename(fp)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class GLB_OT_OpenOutput(bpy.types.Operator):
    """在文件浏览器中打开输出文件夹"""
    bl_idname = "glb.open_output"
    bl_label = "打开输出文件夹 / Open Output"
    bl_description = "在文件浏览器中打开输出目录"

    def execute(self, context):
        settings = context.scene.glb_settings
        out_dir = settings.input.output_folder or settings.input.input_folder
        if out_dir and os.path.isdir(out_dir):
            _open_folder(out_dir)
            self.report({'INFO'}, f"已打开: {out_dir}")
        else:
            self.report({'WARNING'}, "输出文件夹不存在 / Output folder not found")
        return {'FINISHED'}


# ============================================================
# Panel 面板
# ============================================================

class GLB_PT_MainPanel(bpy.types.Panel):
    """N面板主界面"""
    bl_label = "GLB 自动化拓扑与烘焙"
    bl_idname = "GLB_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GLB处理"
    bl_context = ""

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.glb_settings
        running = scene.glb_is_running

        # ── 📁 输入输出 ──
        box_io = layout.box()
        row = box_io.row()
        row.label(text="📁 输入输出 / I/O", icon='FILEBROWSER')
        box_io.prop(settings.input, "input_folder")
        box_io.prop(settings.input, "output_folder")
        # 显示文件计数
        folder = settings.input.input_folder
        if folder and os.path.isdir(folder):
            count = len(
                glob_module.glob(os.path.join(folder, "*.glb")) +
                glob_module.glob(os.path.join(folder, "*.GLB"))
            )
            box_io.label(text=f"  找到 GLB 文件: {count} 个 / Found: {count} GLB files")
        else:
            box_io.label(text="  请选择输入文件夹 / Select input folder")

        # ── 🔧 重拓扑 ──
        box_remesh = layout.box()
        row = box_remesh.row()
        row.label(text="🔧 重拓扑设置 / Remesh", icon='MOD_REMESH')
        box_remesh.prop(settings.remesh, "quad_count")
        box_remesh.prop(settings.remesh, "adapt_quad_count")
        box_remesh.prop(settings.remesh, "timeout_seconds")

        # ── 🎨 烘焙 ──
        box_bake = layout.box()
        row = box_bake.row()
        row.label(text="🎨 烘焙设置 / Bake", icon='TEXTURE')
        box_bake.prop(settings.bake, "resolution")
        box_bake.prop(settings.bake, "cage_extrusion")
        box_bake.prop(settings.bake, "bake_normal")
        box_bake.prop(settings.bake, "save_textures_separate")
        box_bake.prop(settings.bake, "image_format")

        # ── 📦 导出 ──
        box_export = layout.box()
        row = box_export.row()
        row.label(text="📦 导出设置 / Export", icon='EXPORT')
        box_export.prop(settings.export, "export_format")
        box_export.prop(settings.export, "flat_output")
        box_export.prop(settings.export, "close_when_done")

        # ── ▶ 操作 ──
        box_action = layout.box()
        row = box_action.row()
        row.label(text="▶ 操作 / Actions", icon='PLAY')

        if not running:
            # 停止状态：显示开始按钮
            box_action.operator("glb.single_process", icon='FILE_NEW')
            row = box_action.row()
            row.scale_y = 2.0
            row.operator("glb.batch_process", icon='PLAY')
        else:
            # 运行状态：显示进度 + 停止按钮
            box_action.prop(scene, "glb_progress_pct", text="进度 / Progress", slider=True)
            box_action.label(text=scene.glb_progress_text)
            row = box_action.row()
            row.scale_y = 1.5
            row.operator("glb.stop_batch", icon='CANCEL')

        # 统计
        if scene.glb_ok_count > 0 or scene.glb_fail_count > 0:
            box_action.label(
                text=f"  成功: {scene.glb_ok_count}  失败: {scene.glb_fail_count}",
                icon='INFO'
            )

        # 打开输出文件夹
        box_action.operator("glb.open_output", icon='FILE_FOLDER')

        # ── ℹ 关于 ──
        box_about = layout.box()
        row = box_about.row()
        row.label(text="ℹ 关于 / About", icon='INFO')
        box_about.label(text="GLB 批量处理 v1.0.0")
        box_about.label(text="依赖: Quad Remesher 1.23+")
        box_about.label(text="需要: Blender 4.0+")
        box_about.label(text="GitHub: glb-batch-processor")


# ============================================================
# 注册 / 注销
# ============================================================

CLASSES = (
    GLB_InputProperties,
    GLB_RemeshProperties,
    GLB_BakeProperties,
    GLB_ExportProperties,
    GLB_Settings,
    GLB_OT_BatchProcess,
    GLB_OT_StopBatch,
    GLB_OT_SingleProcess,
    GLB_OT_OpenOutput,
    GLB_PT_MainPanel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    # Scene 顶层指针
    bpy.types.Scene.glb_settings = bpy.props.PointerProperty(type=GLB_Settings)

    # 进度显示属性
    bpy.types.Scene.glb_progress_pct = bpy.props.FloatProperty(
        name="进度 / Progress", subtype='PERCENTAGE', min=0, max=100, default=0
    )
    bpy.types.Scene.glb_progress_text = bpy.props.StringProperty(
        name="状态 / Status", default="就绪 / Ready"
    )
    bpy.types.Scene.glb_is_running = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.glb_ok_count = bpy.props.IntProperty(default=0)
    bpy.types.Scene.glb_fail_count = bpy.props.IntProperty(default=0)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    del bpy.types.Scene.glb_settings
    del bpy.types.Scene.glb_progress_pct
    del bpy.types.Scene.glb_progress_text
    del bpy.types.Scene.glb_is_running
    del bpy.types.Scene.glb_ok_count
    del bpy.types.Scene.glb_fail_count


if __name__ == "__main__":
    register()
