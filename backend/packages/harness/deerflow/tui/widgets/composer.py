'''修正终端消息输入控件的光标位置计算，以匹配实际显示单元格偏移。'''

from __future__ import annotations

from textual.widgets import Input


class ComposerInput(Input):
    '''调整输入控件的光标单元格偏移计算。'''

    @property
    def _cursor_offset(self) -> int:
        '''返回输入光标在当前文本中的终端单元格偏移量。'''
        return self._position_to_cell(self.cursor_position)
