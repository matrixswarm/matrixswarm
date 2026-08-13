from PyQt6.QtGui import QColor

class ColorManager:
    BASE_COLOR = QColor("#5AB5FF")  # cyan/blue family

    @staticmethod
    def lighten(color, pct):
        r = min(255, color.red()   + pct)
        g = min(255, color.green() + pct)
        b = min(255, color.blue()  + pct)
        return QColor(r, g, b)

    @staticmethod
    def color_for_depth(depth):
        if depth == 0:
            return ColorManager.BASE_COLOR
        return ColorManager.lighten(ColorManager.BASE_COLOR, depth * 35)
