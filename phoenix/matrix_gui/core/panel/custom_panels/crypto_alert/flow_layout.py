from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=0, spacing=10):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.items = []

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, i): return self.items[i] if i < len(self.items) else None
    def takeAt(self, i): return self.items.pop(i) if i < len(self.items) else None
    def expandingDirections(self): return Qt.Orientations(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self.doLayout(QtCore.QRect(0, 0, w, 0), True)
    def setGeometry(self, rect): super().setGeometry(rect); self.doLayout(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        s = QtCore.QSize()
        for item in self.items:
            s = s.expandedTo(item.minimumSize())
        s += QtCore.QSize(2*self.contentsMargins().top(), 2*self.contentsMargins().top())
        return s
    def doLayout(self, rect, test=False):
        x, y = rect.x(), rect.y()
        lineHeight = 0
        for item in self.items:
            spaceX, spaceY = self.spacing(), self.spacing()
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y += lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            if not test:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y()
