# GLB Batch Processor — Blender Add-on

A Blender add-on for batch processing high-poly GLB files into optimized low-poly models with baked textures. One-click workflow: Quad Remesher retopology → smart UV unwrap → Cycles GPU diffuse/normal baking → per-model export with organized subfolders.

## Features

- 🚀 Batch import high-poly .glb files with automatic mesh merging
- 🔧 Quad Remesher automatic retopology (adjustable target quad count)
- 📐 Smart UV projection
- 🎨 Cycles GPU-accelerated baking (Diffuse + optional Normal map)
- 📁 Automatic per-model subfolder output
- 📦 Export to multiple formats: GLB, FBX, OBJ, USD, STL
- 📊 Real-time progress bar + detailed logging
- 🌐 Bilingual UI (Chinese / English)
- ⏹ Cancel processing at any time
- 📂 Single-file processing mode (for testing settings)

## Requirements

| Item | Minimum Version |
|------|-----------------|
| Blender | 4.0+ |
| Quad Remesher | 1.23+ |
| GPU | Recommended: NVIDIA RTX (OptiX) / AMD (HIP) / Apple Silicon (Metal) |

> 💡 CPU fallback is available but significantly slower.

## Installation

1. Download `glb-batch-processor.zip` from [Releases](https://github.com/Lambda021219/glb-batch-processor/releases)
2. Open Blender → **Edit** → **Preferences** → **Add-ons** → **Install**
3. Select the downloaded `.zip` file → click **Install Add-on**
4. Search "GLB" in the add-on list → enable **GLB 自动化拓扑与烘焙工具**
5. In the 3D Viewport, press **N** → find the **"GLB处理"** tab in the sidebar

## Usage

### Batch Processing

1. Set **Input Folder** (containing high-poly .glb files) and **Output Folder**
2. Adjust **Remesh** settings (target quad count, timeout)
3. Configure **Bake** settings (texture resolution, normal map, image format)
4. Configure **Export** settings (format, flat output mode)
5. Click **▶ Start Batch**
6. **Do not interact with Blender during processing** — wait for the completion popup

### Single File Processing (Testing)

Click **Process Single File...** and select a GLB file to test your current settings on one model.

### Output Structure

Each model gets its own subfolder:

```
output/
├── ModelA/
│   ├── ModelA_low.glb          # Low-poly GLB
│   ├── ModelA_diffuse.png      # Diffuse texture
│   └── ModelA_normal.png       # Normal map (if enabled)
├── ModelB/
│   ├── ModelB_low.glb
│   ├── ModelB_diffuse.png
│   └── ModelB_normal.png
└── batch_process_log.txt       # Processing log
```

> 💡 Enable **Flat Output** in export settings for the legacy behavior (all files in root).

## Panel Reference

### Input / Output
| Setting | Description |
|---------|-------------|
| Input Folder | Directory containing high-poly .glb files |
| Output Folder | Output root directory (each model gets a subfolder) |

### Remesh Settings
| Setting | Default | Description |
|---------|---------|-------------|
| Target Quads | 5000 | Target quad count for Quad Remesher |
| Adapt Quads | Off | Let Quad Remesher auto-determine face count |
| Timeout | 300s | Maximum wait time for remeshing |

### Bake Settings
| Setting | Default | Description |
|---------|---------|-------------|
| Resolution | 1024 | Baked texture pixel size |
| Cage Extrusion | 0.10m | Raycasting cage extrusion distance |
| Bake Normal | Off | Additionally bake a normal map |
| Save Textures | On | Save textures as separate image files |
| Image Format | PNG | File format for saved textures |

### Export Settings
| Setting | Default | Description |
|---------|---------|-------------|
| Format | GLB | GLB / glTF Separate / FBX / OBJ / USD / STL |
| Flat Output | Off | Skip subfolders, output all files to root |
| Auto-Close | Off | Close Blender automatically when done |

> ⚠️ **FBX/OBJ/STL formats cannot embed textures.** Enable **Save Textures Separately** in Bake settings when using these formats.

## Troubleshooting

### "Quad Remesher add-on not found"

Install Quad Remesher first: [exoside.com](https://exoside.com/quadremesher/). Enable it in Blender Preferences after installation.

### Remesh times out

1. Verify Quad Remesher works manually in Blender
2. Increase the timeout value for complex models
3. Check if the Quad Remesher external engine is running (system tray)

### Bake produces black textures

1. Ensure high-poly and low-poly models are visible (not hidden)
2. Update your GPU drivers
3. Try switching Cycles device (OptiX → CUDA) in Preferences
4. Increase cage extrusion value

### Exported GLB has no textures

Ensure **Save Textures Separately** is enabled in bake settings. Textures are saved alongside the GLB in the model subfolder.

### Out of memory with many files

The scene is cleaned between files automatically. If memory is still an issue, reduce texture resolution (e.g., 512) or disable normal map baking.

## License

MIT License — see [LICENSE](LICENSE)

## Contributing

Issues and pull requests are welcome!
