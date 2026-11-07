---
name: ppt-generation
description: 当用户要求生成、创建或制作演示文稿时使用。为每页幻灯片生成视觉丰富的图片，再合成为 PowerPoint 演示文件。
---

# 演示文稿生成技能

## 概述

本技能先规划统一风格的演示结构，逐页生成图片，再合成为 PowerPoint 文件。后续页面以上一页为参考图，保持整体视觉一致。

## 核心能力

- 规划多页演示结构和统一视觉风格。
- 支持商务、学术、极简、Apple Keynote 和创意风格。
- 使用 image-generation 技能为每页生成独特图片。
- 以上一页为参考，保持视觉一致。
- 将图片合成为专业演示文稿。

## 演示风格

制定计划时从以下风格选择：

| 风格 | 描述 | 适用场景 |
|---|---|---|
| **glassmorphism** | 磨砂玻璃模糊面板、悬浮半透明卡片、鲜明渐变背景、层叠纵深 | 科技产品、人工智能与软件服务演示、未来感路演 |
| **dark-premium** | 浓黑背景（#0a0a0a）、发光强调色、微光、奢华品牌气质 | 高端产品、管理层演示、高端品牌 |
| **gradient-modern** | 大胆网格渐变、流动色彩、现代字体，鲜明而精致 | 初创企业、创意机构、品牌发布 |
| **neo-brutalist** | 粗犷醒目字体、高对比、刻意粗粝的反设计、孟菲斯风格 | 前卫品牌、年轻受众、颠覆性初创企业 |
| **3d-isometric** | 简洁等距插画、悬浮三维元素、柔和阴影、科技感 | 技术原理、产品功能、软件服务介绍 |
| **editorial** | 杂志级布局、精致字体层次、戏剧化摄影、Vogue/Bloomberg 气质 | 年报、高端品牌、思想领导力 |
| **minimal-swiss** | 精准网格、Helvetica 风格字体、大量留白、经典现代主义 | 建筑、设计机构、高端咨询 |
| **keynote** | Apple 风格的醒目字体、戏剧化图像、高对比和电影感 | 主题演讲、产品揭幕、激励演讲 |

## 工作流程

### 步骤 1：理解需求

识别：

- 主题：演示内容是什么。
- 页数：默认 5-10 页。
- 风格：business / academic / minimal / keynote / creative。
- 画幅：宽屏 16:9 或经典 4:3。
- 内容大纲：每页关键要点。
- 无需检查 `/mnt/user-data` 下的文件夹。

### 步骤 2：创建演示计划

在 `/mnt/user-data/workspace/` 创建结构化计划，必须包含 `style` 字段以统一视觉。

```json
{
  "title": "演示标题",
  "style": "keynote",
  "style_guidelines": {
    "color_palette": "深黑背景、白字、单一强调色（蓝或橙）",
    "typography": "粗体无衬线标题、清晰正文、显著字号对比",
    "imagery": "高质量摄影、满版图片、电影式构图",
    "layout": "大量留白、中心焦点、每页少量元素"
  },
  "aspect_ratio": "16:9",
  "slides": [
    {
      "slide_number": 1,
      "type": "title",
      "title": "主标题",
      "subtitle": "副标题或标语",
      "visual_description": "用于图像生成的详细描述"
    },
    {
      "slide_number": 2,
      "type": "content",
      "title": "页面标题",
      "key_points": ["要点 1", "要点 2", "要点 3"],
      "visual_description": "用于图像生成的详细描述"
    }
  ]
}
```

### 步骤 3：按顺序逐页生成图片

重要：必须严格按顺序一次生成一页，禁止并行或批量生成。每页依赖上一页作为参考图；并行会破坏风格一致性。

1. 读取图像生成技能：`/mnt/skills/public/image-generation/SKILL.md`。
2. 第一页确立整套演示的视觉语言：

```json
{
  "prompt": "专业演示页面。[计划中的 style_guidelines]。标题：你的标题。[visual_description]。本页确立整套演示的视觉语言。",
  "style": "依据所选风格，例如 Apple Keynote 气质、戏剧化灯光、电影感",
  "composition": "清晰布局和文字层次，采用所选风格对应的构图",
  "color_palette": "来自 style_guidelines",
  "typography": "来自 style_guidelines"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-01-prompt.json \
  --output-file /mnt/user-data/outputs/slide-01.jpg \
  --aspect-ratio 16:9
```

3. 第二页及之后，必须引用上一页：

```json
{
  "prompt": "专业演示页面，严格延续参考图的视觉风格。保持完全相同的配色、字体风格和整体气质。标题：页面标题。[visual_description]。与参考图保持视觉一致。",
  "style": "准确匹配参考图风格",
  "composition": "沿用参考图的布局原则，适配本页内容",
  "color_palette": "与参考图相同",
  "consistency_note": "本页必须让人一眼看出与参考图属于同一套演示"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-02-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-01.jpg \
  --output-file /mnt/user-data/outputs/slide-02.jpg \
  --aspect-ratio 16:9
```

4. 其余各页始终引用紧邻的上一页：

```bash
# 第 3 页引用第 2 页
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-03-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-02.jpg \
  --output-file /mnt/user-data/outputs/slide-03.jpg \
  --aspect-ratio 16:9

# 第 4 页引用第 3 页
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-04-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-03.jpg \
  --output-file /mnt/user-data/outputs/slide-04.jpg \
  --aspect-ratio 16:9
```

### 步骤 4：合成演示文稿

所有页面图片生成后，调用合成脚本：

```bash
python /mnt/skills/public/ppt-generation/scripts/generate.py \
  --plan-file /mnt/user-data/workspace/presentation-plan.json \
  --slide-images /mnt/user-data/outputs/slide-01.jpg /mnt/user-data/outputs/slide-02.jpg /mnt/user-data/outputs/slide-03.jpg \
  --output-file /mnt/user-data/outputs/presentation.pptx
```

参数：

- `--plan-file`：演示计划文件的绝对路径，必填。
- `--slide-images`：按页序排列的图片绝对路径，空格分隔，必填。
- `--output-file`：输出演示文件的绝对路径，必填。

[!NOTE]
无需读取脚本源码，直接传入参数调用。

## 完整示例：玻璃拟态风格（最现代前卫）

用户请求：“制作人工智能产品发布演示。”

### 步骤 1：创建演示计划

创建 `/mnt/user-data/workspace/ai-product-plan.json`：

```json
{
  "title": "介绍 Nova 人工智能",
  "style": "glassmorphism",
  "style_guidelines": {
    "color_palette": "鲜明的紫到青渐变背景（#667eea→#00d4ff），白色不透明度 15-20% 的磨砂玻璃面板，电光强调色",
    "typography": "SF Pro Display 风格，700 字重白色粗标题，轻微文字阴影，400 字重清晰正文，确保玻璃上有优秀对比",
    "imagery": "抽象三维玻璃球、悬浮半透明几何形状、柔和发光球体，以层叠透明度创造纵深",
    "layout": "居中磨砂玻璃卡片，32px 圆角、48-64px 内边距，悬浮在渐变背景上，用柔和阴影营造层次",
    "effects": "面板背景模糊 20-40px，细微白色边框辉光，与渐变配色一致的柔和彩色阴影，光线折射",
    "visual_language": "Apple Vision Pro / visionOS 气质，通过透明度体现高级纵深，未来感而亲切，2024 设计趋势"
  },
  "aspect_ratio": "16:9",
  "slides": [
    {
      "slide_number": 1,
      "type": "title",
      "title": "介绍 Nova 人工智能",
      "subtitle": "重新想象智能",
      "visual_description": "背景由深紫 #667eea 经洋红流向青色 #00d4ff。中央大型磨砂玻璃面板，强背景模糊，放置粗白标题及更轻的副标题。周围悬浮三维玻璃球和抽象形状，面板后方柔光，呈现高级 visionOS 气质。卡片白色细边框：1px rgba 255,255,255,0.3，配柔和紫色阴影。"
    },
    {
      "slide_number": 2,
      "type": "content",
      "title": "为什么选择 Nova？",
      "key_points": ["处理速度提升 10 倍", "类人理解能力", "企业级安全"],
      "visual_description": "沿用紫青渐变。左侧悬浮磨砂玻璃卡片，粗白标题和三条要点，下方配轻盈玻璃胶囊标签。右侧以互联玻璃节点构成抽象三维神经网络，发出柔光。悬浮半透明二十面体和圆环增加纵深。与上一页保持相同玻璃拟态风格。"
    },
    {
      "slide_number": 3,
      "type": "content",
      "title": "工作原理",
      "key_points": ["自然语言输入", "多模态处理", "即时洞察"],
      "visual_description": "延续渐变背景，中央三张略微倾斜的磨砂玻璃卡片层叠展示流程，柔和发光线相连，每卡含抽象图标。周围悬浮玻璃球和光粒，顶部粗白标题，通过层叠和透明度创造纵深。"
    },
    {
      "slide_number": 4,
      "type": "content",
      "title": "为规模化而建",
      "key_points": ["超过 100 万并发用户", "99.99% 可用率", "全球基础设施"],
      "visual_description": "沿用背景，不对称构图。右侧大型磨砂面板以粗体展示指标，左侧由玻璃面板和连接线组成抽象三维地球，象征全球规模。带数字的小玻璃卡片悬浮，柔和环境光，高级科技气质。"
    },
    {
      "slide_number": 5,
      "type": "conclusion",
      "title": "未来即刻开启",
      "subtitle": "加入等候名单",
      "visual_description": "戏剧化收尾，背景稍更鲜明。中央磨砂卡片承载粗体标题和行动副标题，后方柔和光束爆发、玻璃粒子悬浮，形成庆祝感。多层玻璃形状增加纵深，在保持风格统一的前提下成为视觉冲击最强的一页。"
    }
  ]
}
```

### 步骤 2：读取图像生成技能

读取 `/mnt/skills/public/image-generation/SKILL.md`，了解生成方法。

### 步骤 3：以前页参考链逐页生成

第一页：标题页，确立视觉语言。创建 `/mnt/user-data/workspace/nova-slide-01.json`：

```json
{
  "prompt": "超高端玻璃拟态演示标题页。背景平滑地从深紫 #667eea 经洋红 #f093fb 过渡到青色 #00d4ff，柔和鲜明。中央大型磨砂玻璃面板，强背景模糊，32px 圆角。粗白无衬线标题“介绍 Nova 人工智能”，72pt，SF Pro Display 风格，700 字重，轻微文字阴影；下方轻字重副标题“重新想象智能”。白色细边框：1px rgba 255,255,255,0.25，柔和紫色投影。周围悬浮折射玻璃球、半透明二十面体和抽象形状，营造纵深。面板背后柔和辉光，小光粒悬浮。Apple Vision Pro / visionOS 界面气质，16:9，超现代高端科技产品发布感。",
  "style": "玻璃拟态、visionOS 气质、Apple Vision Pro 界面风格、高端科技、2024 设计趋势",
  "composition": "居中玻璃卡片为焦点，边缘悬浮三维元素，40% 留白，清晰视觉层次",
  "lighting": "渐变柔和环境光、玻璃折射、三维形状的轻微轮廓光",
  "color_palette": "紫 #667eea、洋红 #f093fb、青 #00d4ff、磨砂白 rgba(255,255,255,0.15)、纯白文字 #ffffff",
  "effects": "面板背景模糊、带色柔和投影、光线折射、玻璃轻微噪点纹理、悬浮粒子"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/nova-slide-01.json \
  --output-file /mnt/user-data/outputs/nova-slide-01.jpg \
  --aspect-ratio 16:9
```

第二页：内容页，必须引用第一页。创建 `/mnt/user-data/workspace/nova-slide-02.json`：

```json
{
  "prompt": "演示页面，严格延续参考图的视觉风格。完全相同的紫青渐变背景、玻璃拟态气质、字体风格。左侧磨砂卡片，背景模糊，粗白标题“为什么选择 Nova？”，字体与参考图一致，下方三项功能采用轻盈玻璃胶囊标签。右侧为互联玻璃节点构成的抽象三维神经网络，发出柔和青光并悬浮。加入与参考图一致的半透明几何形状。玻璃处理完全一致：白色边框、紫色阴影、相同模糊强度。关键：本页必须与参考图属于同一套演示，颜色、玻璃处理、整体气质均完全相同。",
  "style": "准确匹配参考图：玻璃拟态、visionOS 气质、相同视觉语言",
  "composition": "不对称分栏，左侧玻璃卡片 40%，右侧三维图像 40%，元素间保留呼吸空间",
  "color_palette": "准确匹配参考图：紫 #667eea 至青 #00d4ff 渐变，相同磨砂白处理，相同白色文字",
  "consistency_note": "关键：视觉风格必须与参考图一致，渐变颜色、玻璃模糊强度、阴影、字体字重和样式相同，观众应立即认出属于同一套演示。"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/nova-slide-02.json \
  --reference-images /mnt/user-data/outputs/nova-slide-01.jpg \
  --output-file /mnt/user-data/outputs/nova-slide-02.jpg \
  --aspect-ratio 16:9
```

第 3-5 页沿用此模式，每页引用紧邻的上一页：

- 提示词始终包含“严格延续参考图的视觉风格”。
- 明确要求“完全相同的渐变背景、玻璃处理、字体”。
- 用 `consistency_note` 强调风格匹配。
- 参考图使用上一页图片。

### 步骤 4：合成最终文稿

```bash
python /mnt/skills/public/ppt-generation/scripts/generate.py \
  --plan-file /mnt/user-data/workspace/nova-plan.json \
  --slide-images /mnt/user-data/outputs/nova-slide-01.jpg /mnt/user-data/outputs/nova-slide-02.jpg /mnt/user-data/outputs/nova-slide-03.jpg /mnt/user-data/outputs/nova-slide-04.jpg /mnt/user-data/outputs/nova-slide-05.jpg \
  --output-file /mnt/user-data/outputs/nova-presentation.pptx
```

## 各风格的具体规范

### 玻璃拟态（推荐，最现代前卫）

```json
{
  "style": "glassmorphism",
  "style_guidelines": {
    "color_palette": "鲜明渐变：紫 #667eea 到粉 #f093fb，或青 #4facfe 到蓝 #00f2fe；不透明度 20% 的磨砂白面板，突出渐变的强调色",
    "typography": "SF Pro Display 或 Inter 风格，标题字重 600-700，正文字重 400，白字配微弱投影以提高玻璃上的可读性",
    "imagery": "悬浮抽象三维形状、柔和模糊球体、玻璃几何体，通过半透明叠层营造纵深",
    "layout": "背景模糊悬浮卡片、48-64px 内边距、24-32px 圆角、细微阴影",
    "effects": "磨砂玻璃背景模糊 20px，白细边框 1px rgba 255,255,255,0.2，面板后微光，悬浮元素投影",
    "visual_language": "Apple Vision Pro 界面般的高端科技感，以透明度表现深度，光线穿过玻璃表面折射"
  }
}
```

### 深色高端

```json
{
  "style": "dark-premium",
  "style_guidelines": {
    "color_palette": "深黑基底 #0a0a0a 至 #121212，发光强调色：电蓝 #00d4ff、霓虹紫 #bf5af2 或金 #ffd700；深灰渐变 #1a1a1a 至 #0a0a0a 营造深度",
    "typography": "优雅无衬线，Neue Haas Grotesk 或 Suisse Int'l 风格；标题 72pt 以上，正文 18pt；标题字间距 -0.02em，纯白 #ffffff",
    "imagery": "戏剧化影棚灯光、轮廓光与边缘辉光、电影级产品摄影、抽象光轨、高级材料纹理（拉丝金属、哑光表面）",
    "layout": "60% 以上留白，不对称平衡，内容依网格布局但留有呼吸空间，每页一个焦点",
    "effects": "关键元素后方细微环境光、光晕、2-3% 不透明度的颗粒纹理叠加、边缘暗角",
    "visual_language": "Bang & Olufsen、Porsche Design 式奢华科技品牌气质，以克制体现精致，每个元素均有明确目的"
  }
}
```

### 现代渐变

```json
{
  "style": "gradient-modern",
  "style_guidelines": {
    "color_palette": "Stripe/Linear 风格大胆网格渐变：紫粉橙 #7c3aed→#ec4899→#f97316，或冷色青蓝紫 #06b6d4→#3b82f6→#8b5cf6；依背景深浅选白字或深色字",
    "typography": "现代几何无衬线，Satoshi、General Sans 或 Clash Display 风格，可变字重，80pt 以上超大粗标题，20pt 舒适正文",
    "imagery": "抽象流动形状、变形渐变、三维渲染抽象物体、柔和有机形态、悬浮基础几何体",
    "layout": "动态不对称构图，元素用混合模式叠加，文字融入渐变流向，满版背景",
    "effects": "平滑渐变，3-5% 轻微噪点增加深度，配合渐变的彩色柔影，运动模糊暗示动势",
    "visual_language": "Stripe、Linear、Vercel 式现代软件服务气质，活力而专业，前瞻科技感"
  }
}
```

### 新粗野主义

```json
{
  "style": "neo-brutalist",
  "style_guidelines": {
    "color_palette": "高对比原色：纯黑、纯白，配亮粉 #ff0080、电黄 #ffff00 或原红 #ff0000；可用孟菲斯风格粉彩作辅助色",
    "typography": "超粗紧缩字体，Impact、Druk 或 Bebas Neue 风格，全大写标题，极端字号对比，刻意紧密或重叠的字间距",
    "imagery": "未经修饰的摄影、刻意视觉噪点、半色调图案、剪贴拼贴、手绘元素、贴纸和印章",
    "layout": "打破网格、元素重叠、4-8px 粗黑边框、可见结构，减少留白，密集而有组织的混乱",
    "effects": "无模糊硬阴影，偏移 8-12px，像素化点缀、扫描线、阴极射线管屏幕效果和刻意的瑕疵",
    "visual_language": "反企业化的叛逆感，自制小志与数字媒介结合，粗粝真实，以大胆设计留下记忆"
  }
}
```

### 三维等距

```json
{
  "style": "3d-isometric",
  "style_guidelines": {
    "color_palette": "柔和现代配色：紫 #8b5cf6、青绿 #14b8a6、暖珊瑚 #fb7185，奶油或浅灰背景 #fafafa，各元素饱和度一致",
    "typography": "亲切几何无衬线，Circular、Gilroy 或 Quicksand 风格，中等字重标题，24pt 正文，优秀可读性",
    "imagery": "简洁三维等距插画，统一 30° 视角，柔软黏土渲染，悬浮平台和设备，可爱简化物体",
    "layout": "中央等距场景为主视觉，文字围绕三维元素平衡布局，清晰层次，64px 以上边距",
    "effects": "20px 模糊、30% 不透明度的柔和投影，三维物体环境遮蔽，表面轻微渐变，统一左上光源",
    "visual_language": "Slack、Notion、Asana 式亲切科技插画，用简化体现复杂性，强调清晰易懂"
  }
}
```

### 杂志编辑

```json
{
  "style": "editorial",
  "style_guidelines": {
    "color_palette": "精致中性色：米白 #f5f5f0、炭灰 #2d2d2d，单一强调色可选酒红 #7c2d12、森林绿 #14532d、海军蓝 #1e3a5f，偶尔使用全彩摄影",
    "typography": "精致衬线标题，Playfair Display、Freight、Editorial New 风格；正文使用 Söhne、Graphik 等无衬线；96pt 标题、16pt 正文，1.6 行高",
    "imagery": "杂志级摄影、戏剧化裁切、满版图片、刻意留白的人像、Vogue 与 Bloomberg Businessweek 式灯光",
    "layout": "12 栏精致网格、刻意不对称、引文作为设计元素、图文环绕、优雅边距",
    "effects": "极少装饰，以摄影和字体为主，轻微降饱和、胶片颗粒、优雅边线",
    "visual_language": "高端杂志气质，知识感与精致感，通过克制设计提升内容"
  }
}
```

### 瑞士极简

```json
{
  "style": "minimal-swiss",
  "style_guidelines": {
    "color_palette": "纯白 #ffffff 或米白 #fafaf9，纯黑 #000000 文字，单一醒目强调色：瑞士红 #ff0000、克莱因蓝 #002fa7 或信号黄 #ffcc00",
    "typography": "Helvetica Neue 或 Aktiv Grotesk，严格字号序列 12/16/24/48/96，正文中等字重，仅强调处加粗，左齐右不齐",
    "imagery": "客观摄影、几何形状、清晰图标、数学精度，将留白作为构图元素",
    "layout": "严格网格、模块化构图、40% 以上留白，内容对齐隐形网格",
    "effects": "纯粹形式，无阴影、无渐变、无装饰，偶尔使用单根细线",
    "visual_language": "国际主义字体风格、形式追随功能、经典现代主义、Dieter Rams 式克制"
  }
}
```

### Keynote（Apple 风格）

```json
{
  "style": "keynote",
  "style_guidelines": {
    "color_palette": "深黑 #000000 至 #1d1d1f，纯白字，标志蓝 #0071e3 或渐变强调色：创意用紫粉，科技用蓝青",
    "typography": "San Francisco Pro Display，字重强对比，80pt 以上粗标题、24pt 轻正文，标题字间距 -0.03em，光学对齐",
    "imagery": "电影级摄影、浅景深、轮廓光与聚光灯、带倒影的产品主视觉、满版图片",
    "layout": "最大化留白，每页一张有力图片或一句陈述，居中或戏剧化偏移，避免拥挤",
    "effects": "细微渐变叠加，关键元素光晕与辉光，表面反射，平滑渐变背景",
    "visual_language": "Apple 全球开发者大会主题演讲气质，以简洁体现自信，关注每个像素，舞台化呈现"
  }
}
```

## 输出处理

- 演示文件保存在 `/mnt/user-data/outputs/`。
- 使用 `present_files` 分享给用户。
- 用户要求时同时分享逐页图片。
- 简要描述演示内容。
- 如需修改，可迭代或重新生成指定页面。

## 注意事项

### 关键质量规范

专业图像提示词：

- 图像提示词使用中文。
- 极其具体地描述视觉细节，模糊提示会产生泛化结果。
- 给出准确十六进制颜色，例如 #667eea，而非只说“紫色”。
- 指定字重 400/700、字号层次和字间距。
- 精确描述效果，例如“背景模糊 20px”“投影模糊 8px、不透明度 30%”。
- 引用真实设计体系，如 visionOS、Stripe 网站、Bloomberg Businessweek。

视觉一致性最重要：

- 逐页生成，每页必须引用上一页。
- 第一页确立整套视觉语言。
- 每个后续提示明确写“严格延续参考图的视觉风格”。
- 强调“相同”“完全一致”“准确匹配”，以维持一致性。
- 第一页之后的每个提示都包含 `consistency_note`。
- 风格不一致时，加强参考图匹配要求后重新生成。

现代审美原则：

- 保留 40-60% 留白，营造高级感。
- 每页限制元素数量，一个焦点、一条信息。
- 通过阴影、透明度和纵深层次创造深度。
- 标题 72pt 以上，正文 18-24pt。
- 一个主色盘，最多 1-2 个强调色。

常见错误：

- 只写“专业幻灯片”而不具体描述。
- 每页文字或元素过多，造成拥挤。
- 各页配色不同，未引用上一页。
- 遗漏参考图片参数。
- 同一演示混用不同设计风格。
- 并行生成页面；必须按 1 → 2 → 3 顺序逐页执行。

场景推荐：

- 科技产品发布：`glassmorphism` 或 `gradient-modern`。
- 奢华或高端品牌：`dark-premium` 或 `editorial`。
- 初创企业路演：`gradient-modern` 或 `minimal-swiss`。
- 管理层演示：`dark-premium` 或 `keynote`。
- 创意机构：`neo-brutalist` 或 `gradient-modern`。
- 数据分析：`minimal-swiss` 或 `3d-isometric`。
