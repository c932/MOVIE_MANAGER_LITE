"""
流式布局 FlowLayout
用于筛选按钮的自适应排列
"""
from PyQt6.QtWidgets import QLayout, QLayoutItem, QWidget
from PyQt6.QtCore import Qt, QRect, QSize, QPoint


class FlowLayout(QLayout):
    """流式布局 - 自动换行的布局管理器"""
    
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        
        self.setSpacing(spacing)
        self.itemList = []
    
    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item: QLayoutItem):
        """添加布局项"""
        self.itemList.append(item)
    
    def count(self) -> int:
        """返回项目数量"""
        return len(self.itemList)
    
    def itemAt(self, index: int) -> QLayoutItem:
        """获取指定索引的项目"""
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None
    
    def takeAt(self, index: int) -> QLayoutItem:
        """移除并返回指定索引的项目"""
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None
    
    def expandingDirections(self) -> Qt.Orientation:
        """返回扩展方向"""
        return Qt.Orientation(0)
    
    def hasHeightForWidth(self) -> bool:
        """是否有基于宽度的高度"""
        return True
    
    def heightForWidth(self, width: int) -> int:
        """根据宽度计算高度"""
        height = self._doLayout(QRect(0, 0, width, 0), True)
        return height
    
    def setGeometry(self, rect: QRect):
        """设置几何形状"""
        super().setGeometry(rect)
        self._doLayout(rect, False)
    
    def sizeHint(self) -> QSize:
        """返回建议尺寸"""
        return self.minimumSize()
    
    def minimumSize(self) -> QSize:
        """返回最小尺寸"""
        size = QSize()
        
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), 
                     margins.top() + margins.bottom())
        return size
    
    def _doLayout(self, rect: QRect, testOnly: bool) -> int:
        """执行布局"""
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacing = self.spacing()
        
        for item in self.itemList:
            widget = item.widget()
            if widget is None:
                continue
            
            # 使用固定的spacing值
            spaceX = spacing if spacing >= 0 else 8
            spaceY = spacing if spacing >= 0 else 8
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        
        return y + lineHeight - rect.y()
