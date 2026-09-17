"未说明"

from __future__ import annotations

from textual.widgets import Input


class ComposerInput(Input):
    """调整输入控件的光标单元格偏移计算。"""

    @property
    def _cursor_offset(self) -> int:
        """返回输入光标在当前文本中的终端单元格偏移量。"""
        # True cell offset of the cursor, without Textual's end-of-value +1.
        return self._position_to_cell(self.cursor_position)
