# Godot Prototype

这个目录是 `capy-lulu` 桌宠的 Godot 原型骨架。

当前目标：

- 用 Godot 替代 Tk 做透明窗口和动画播放
- 直接复用现有资源：
  - `assets/hatch-pet/spritesheet.png`
  - `assets/edge-hide/*.png`
  - `assets/window-dock/*.png`
- 先把渲染、透明无边框窗口、基础拖拽、拖拽方向动画、屏幕边缘吸附、状态切换、特殊姿态切换跑通
- 当前已经通过本地 `window_bridge.py` 原型接入外部窗体吸附与跟随

## 运行

```powershell
D:\work\Godot\Godot_v4.6.3-stable_win64.exe --path D:\work\Pet\godot_pet
```

如果仍然看到黑底，优先再试兼容渲染器：

```powershell
D:\work\Godot\Godot_v4.6.3-stable_win64.exe --rendering-method gl_compatibility --path D:\work\Pet\godot_pet
```

如果你是从 Godot 编辑器里直接点运行：

- 透明窗口在 `Embed Game` 模式下不会正常工作
- 先切到 `Game` 面板
- 点右上角 3 个点
- 关闭 `Embed Game on Next Play`

否则经常会看到黑底，而不是透明背景

## 当前快捷键

- 鼠标左键拖拽：移动窗口
- 左右拖拽时会切到 `running-left / running-right`
- 拖到屏幕边缘附近松手：会吸附到最近屏幕边，并切到对应 `edge-hide`
- 顶部吸附后会按左 / 中 / 右三段停靠
- 顶部吸附后单击：按左→中→右、右→中→左、中随机左右的规则跑位
- 拖到普通应用窗口边缘附近松手：会尝试吸附到窗体边缘，并切到对应 `window-dock`
- `1-9`: 切换 atlas 的 9 个普通状态
- `Q/W/E/R`: 切换屏幕边缘 `edge-hide` 左/上/右/下
- `A/S/D/F`: 切换窗体边缘 `window-dock` 左/上/右/下，窗体吸附姿态会轻微眨眼
- `Esc`: 回到 `idle`

## 窗体桥接服务

Godot 原型目前通过本地 Python 小服务来做 Win32 窗体枚举、吸附与跟随：

```powershell
python .\tools\window_bridge.py --host 127.0.0.1 --port 18992
```

如果桥接服务没启动，Godot 原型仍然可以运行，但外部窗体边缘吸附不会生效。

## 下一步

1. 继续消除少数 Windows 环境下的黑底透明兼容问题
2. 把 Godot 里的精灵大小和锚点整理成和当前 Tk 原型一致
3. 继续微调 `window-dock` 姿态与真实窗体边缘的贴合位置

## Asset helpers

Generate the `window-dock` blink frames from the current open-eye poses:

```powershell
python D:\work\Pet\make_window_dock_blinks.py
```

The script writes `*-blink-clean.png` into both `artifacts/window-dock/` and `godot_pet/assets/window-dock/`.
4. 把桥接服务从原型 HTTP 方案进一步收敛成更稳的本地接口
5. 继续微调顶边跑位动画、速度和贴边姿态
