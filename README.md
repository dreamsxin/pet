# Capy Lulu Pet

这个仓库现在包含两套相关产物：

1. `artifacts/hatch-pet/`
   - 最终的 Codex 自定义宠物包产物
   - 关键文件：
     - `spritesheet.webp`
     - `pet.json`
     - `contact-sheet.png`
     - `validation.json`
   - 这是当前仓库内最新的可安装宠物包目录，可以直接复制到 `C:\Users\admin\.codex\pets\capy-lulu\`

2. 本地 Windows 桌宠原型
   - 入口：`main.py`
   - 使用 `artifacts/hatch-pet/spritesheet.webp` 作为动画源
   - 支持无边框悬浮、拖拽、屏幕边缘吸附、窗体边缘吸附、右键菜单切换状态

## 目录

- `main.py`
  - 本地桌宠入口
- `pet_window.py`
  - 窗口、拖拽、吸附、右键菜单、状态切换、动画播放
- `image_pipeline.py`
  - 读取 Codex 宠物包 atlas，并按状态切出帧
- `artifacts/hatch-pet/`
  - 最终宠物包与 QA 文件
- `artifacts/edge-hide/`
  - 边缘停靠隐藏素材（上/下/左/右），包含开眼/闭眼帧
- `assests/01.webp`
  - 角色母版参考图
- `imagegen_scripts/`
  - 当前项目保留的 OpenAI 图像生成辅助脚本副本
- `prompts/capy-lulu/`
  - 当前保留在项目中的动画生成提示词

## 本地桌宠运行

安装依赖：

```powershell
python -m pip install pillow
```

启动：

```powershell
python .\main.py
```

## 本地桌宠控制

- 左键拖拽：移动宠物
- 左键单击：普通情况下轮换状态
- 顶边停靠后左键单击：
  - 当前在左侧：先跑到中间，再点一次跑到右侧
  - 当前在右侧：先跑到中间，再点一次跑到左侧
  - 当前在中间：随机选择跑到左侧或右侧
- 右键菜单：切换状态、取消窗体吸附、置顶、退出

快捷键：

- `1` `idle`
- `2` `running-right`
- `3` `running-left`
- `4` `waving`
- `5` `jumping`
- `6` `failed`
- `7` `waiting`
- `8` `running`
- `9` `review`

## Codex 自定义宠物包

当前包已经安装到：

```text
C:\Users\admin\.codex\pets\capy-lulu\
```

也可以直接运行项目内安装脚本：

```powershell
python .\install_capy_lulu_to_codex.py
```

当前选择的宠物配置：

```text
C:\Users\admin\.codex\config.toml
[desktop]
selected-avatar-id = "custom:capy-lulu"
```

## Codex 9 行状态说明

atlas 固定使用 9 行：

1. `idle`
2. `running-right`
3. `running-left`
4. `waving`
5. `jumping`
6. `failed`
7. `waiting`
8. `running`
9. `review`

本地可以确认的事实：

- Codex 已经选中 `custom:capy-lulu`
- 包结构和 atlas 校验通过
- 9 行语义来自 `hatch-pet` contract

当前无法仅靠本地配置文件完全证明的部分：

- Codex 桌面版内部到底以什么精确时机切换 `running-right` / `running-left`
- 是否存在额外的桌面端动画降级逻辑

可以合理确认的典型语义：

- `idle`：空闲
- `waiting`：等待用户输入或确认
- `running`：任务处理中
- `review`：检查或展示结果
- `failed`：失败或取消

`running-left` / `running-right` 更像桌面端位置移动动画，是否触发取决于 Codex 桌面应用内部实现，不由 `pet.json` 配置。

## 窗体边缘吸附

本地 Windows 桌宠原型支持：

- 屏幕工作区边缘吸附
- 普通应用窗口边缘吸附
- 目标窗口移动时跟随
- 停靠到屏幕边缘时自动切换到 `edge-hide` 素材
- `edge-hide` 使用开眼/闭眼/开眼三帧循环，形成轻微眨眼动画
- 顶边吸附时按左/中/右三段最近位置停靠
- 顶边停靠后点击可在左/中/右之间自动跑位

这部分是 `main.py + pet_window.py` 的本地行为，不是 Codex 自定义宠物包能力。

## 保留与清理策略

仓库只保留：

- 最终可运行代码
- 最终宠物包产物
- 角色母版参考图
- 当前项目实际用到的 imagegen 脚本副本
- 当前确认有效的生成提示词

不再保留历史生成中间目录、旧版本 strip、临时 frames 目录和 `__pycache__`。

如果后续需要继续优化动画，建议重新生成新的 strip，而不是保留大量历史中间图片。当前策略是：

- 保留最终 `artifacts/hatch-pet/`
- 保留角色母版与当前使用的脚本
- 需要微调时重新生成对应状态 strip，再回填 atlas
