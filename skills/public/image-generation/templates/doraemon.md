# 哆啦A梦八格漫画生成器

## 工作流程

1. 提取故事背景：主题、道具、冲突、笑点。
2. 映射为八个叙事节拍。
3. 使用下方模板生成 JSON（JavaScript Object Notation，JavaScript 对象表示法）提示词文件。

## 分格布局

```
┌─────────┬─────────┐
│ 第 1 格 │ 第 2 格 │  第 1 行：y=200，height=380
├─────────┼─────────┤
│ 第 3 格 │ 第 4 格 │  第 2 行：y=600，height=380
├─────────┼─────────┤
│ 第 5 格 │ 第 6 格 │  第 3 行：y=1000，height=380
├─────────┼─────────┤
│ 第 7 格 │ 第 8 格 │  第 4 行：y=1400，height=380
└─────────┴─────────┘
左列：x=90，width=450
右列：x=540，width=450
```

## 角色

* 哆啦A梦
* 大雄
* 静香
* 胖虎
* 小夫

## 提示词模板

```json
{
  "canvas": {
    "width": 1080,
    "height": 1920,
    "background": { "type": "solid", "color": "#F0F8FF" }
  },
  "header": {
    "title": {
      "text": "[故事标题]",
      "position": { "x": 540, "y": 100 },
      "style": {
        "font_family": "Doraemon, sans-serif",
        "font_size": 56,
        "font_weight": "bold",
        "color": "#0095D9",
        "text_align": "center",
        "stroke": "#FFFFFF",
        "stroke_width": 4,
        "text_shadow": "3px 3px 0px #FFD700"
      }
    }
  },
  "panels": [
    {
      "id": "panel1",
      "position": { "x": 90, "y": 200 },
      "size": { "width": 450, "height": 380 },
      "border": { "width": 4, "color": "#000000", "radius": 12 },
      "background": "#FFFFFF",
      "scene": {
        "location": "[地点名称]",
        "characters": [
          {
            "name": "[角色]",
            "position": { "x": 0, "y": 0 },
            "expression": "[表情]",
            "pose": "[姿态描述]"
          }
        ],
        "dialogues": [
          {
            "speaker": "[角色]",
            "text": "[对话文本]",
            "position": { "x": 0, "y": 0 },
            "style": {
              "bubble_type": "speech",
              "backgroundColor": "#FFFFFF",
              "border_color": "#000000",
              "font_size": 22,
              "text_align": "center"
            }
          }
        ],
        "props": []
      }
    }
  ],
  "footer": {
    "text": "[结束语]——哆啦A梦",
    "position": { "x": 540, "y": 1860 },
    "style": {
      "font_family": "Doraemon, sans-serif",
      "font_size": 24,
      "color": "#0095D9",
      "text_align": "center"
    }
  },
}
```

## 故事模式

铺垫 → 问题 → 道具 → 误用 → 反噬 → 混乱 → 后果 → 反讽笑点

## 宽高比

9:16
