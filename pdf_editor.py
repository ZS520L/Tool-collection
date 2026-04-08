"""
PDF编辑器 - PyQt5实时预览
============================
支持文字擦除、黑白转换、添加可拖动文字标签（自定义字体/大小/颜色）、
水平垂直居中对齐，多行文字编辑，实时预览后导出PDF
"""

import sys
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea, QToolBar,
    QAction, QSpinBox, QMessageBox, QStatusBar, QComboBox,
    QFontComboBox, QColorDialog, QInputDialog, QLineEdit,
    QTextEdit, QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QCursor, QKeySequence, QFont, QFontDatabase


class MultiLineTextDialog(QDialog):
    """多行文字输入对话框"""
    def __init__(self, parent=None, title="编辑文字", label="文字内容:", text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(400, 250)
        self.setStyleSheet(
            "QDialog { background: #353535; }"
            "QLabel { color: white; }"
            "QTextEdit { color: white; background: #1a1a1a; border: 1px solid #555; padding: 4px; font-size: 13px; }"
            "QPushButton { color: white; background: #353535; border: 1px solid #555; padding: 6px 20px; }"
            "QPushButton:hover { background: #454545; }"
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_text(self):
        return self.text_edit.toPlainText()


class DraggableText(QLabel):
    """可拖动的文字标签"""
    moved = pyqtSignal()  # 位置变化信号
    selected = pyqtSignal(object)  # 选中信号
    deleted = pyqtSignal(object)  # 删除信号

    def __init__(self, text, font, color, parent=None):
        super().__init__(text, parent)
        self._font = font
        self._color = color
        self._dragging = False
        self._drag_offset = QPoint()
        self._scale = 1.0
        # 原始坐标（相对于未缩放的pixmap）
        self._orig_x = 0
        self._orig_y = 0
        self._is_selected = False

        self.setFont(font)
        self._update_style()
        self.adjustSize()
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self.setMouseTracking(True)
        self.show()

    def _update_style(self):
        """更新样式"""
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        border = "2px dashed #0078D7" if self._is_selected else "1px dashed rgba(128,128,128,80)"
        bg = "rgba(0,120,215,20)" if self._is_selected else "transparent"
        self.setStyleSheet(
            f"color: rgb({r},{g},{b}); background: {bg}; border: {border}; padding: 2px;"
        )

    def set_selected(self, selected):
        self._is_selected = selected
        self._update_style()

    def set_scale(self, scale):
        """更新缩放并调整显示"""
        self._scale = scale
        scaled_font = QFont(self._font)
        scaled_font.setPointSizeF(self._font.pointSizeF() * scale)
        self.setFont(scaled_font)
        self.adjustSize()
        self.move(int(self._orig_x * scale), int(self._orig_y * scale))

    def set_orig_pos(self, x, y):
        """设置原始坐标"""
        self._orig_x = x
        self._orig_y = y
        self.move(int(x * self._scale), int(y * self._scale))

    def get_orig_pos(self):
        return self._orig_x, self._orig_y

    def get_text_info(self):
        """返回文字信息字典"""
        return {
            'type': 'text',
            'text': self.text(),
            'font_family': self._font.family(),
            'font_size': self._font.pointSizeF(),
            'font_bold': self._font.bold(),
            'color': self._color,
            'orig_x': self._orig_x,
            'orig_y': self._orig_y,
        }

    def update_text(self, text):
        self.setText(text)
        self.adjustSize()

    def update_font(self, font):
        self._font = font
        scaled_font = QFont(font)
        scaled_font.setPointSizeF(font.pointSizeF() * self._scale)
        self.setFont(scaled_font)
        self.adjustSize()

    def update_color(self, color):
        self._color = color
        self._update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.pos()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            self.selected.emit(self)
            self.raise_()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            new_pos = self.mapToParent(event.pos() - self._drag_offset)
            self.move(new_pos)
            # 更新原始坐标
            self._orig_x = new_pos.x() / self._scale
            self._orig_y = new_pos.y() / self._scale
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(QCursor(Qt.OpenHandCursor))
            self.moved.emit()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        """双击编辑文字"""
        dialog = MultiLineTextDialog(self, title="编辑文字", label="文字内容:", text=self.text())
        if dialog.exec_():
            text = dialog.get_text()
            if text:
                self.update_text(text)
                self.moved.emit()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            self.deleted.emit(self)
            event.accept()
        else:
            super().keyPressEvent(event)


class PDFPage:
    """管理单个PDF页面的数据和修改"""
    def __init__(self, page, page_num, dpi=150):
        self.page = page
        self.page_num = page_num
        self.dpi = dpi
        self.modifications = []  # 存储修改记录: {'type': 'erase'/'grayscale'/'text', 'rect': QRect, 'color': QColor}
        self.text_items = []  # 文字标签信息列表
        self._pixmap = None
        self._original_pixmap = None
        
    def get_pixmap(self, force_refresh=False):
        """获取页面的QPixmap"""
        if self._pixmap is None or force_refresh:
            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = self.page.get_pixmap(matrix=mat)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            self._original_pixmap = QPixmap.fromImage(img.copy())
            self._pixmap = QPixmap.fromImage(img)
            self._apply_modifications()
        return self._pixmap
    
    def _apply_modifications(self):
        """应用所有修改到pixmap"""
        if not self.modifications:
            return
        
        # 从原始pixmap重新开始
        self._pixmap = self._original_pixmap.copy()
        
        for mod in self.modifications:
            if mod['type'] == 'erase':
                self._apply_erase(mod['rect'], mod.get('color', QColor(255, 255, 255)))
            elif mod['type'] == 'grayscale':
                self._apply_grayscale(mod['rect'])
    
    def _apply_erase(self, rect, color):
        """擦除指定区域，用颜色填充"""
        painter = QPainter(self._pixmap)
        painter.fillRect(rect, color)
        painter.end()
    
    def _apply_grayscale(self, rect):
        """将指定区域转为灰度"""
        # 提取区域图像
        img = self._pixmap.toImage()
        
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        # 边界检查
        x = max(0, x)
        y = max(0, y)
        w = min(w, img.width() - x)
        h = min(h, img.height() - y)
        
        if w <= 0 or h <= 0:
            return
            
        for py in range(y, y + h):
            for px in range(x, x + w):
                pixel = img.pixelColor(px, py)
                gray = int(0.299 * pixel.red() + 0.587 * pixel.green() + 0.114 * pixel.blue())
                img.setPixelColor(px, py, QColor(gray, gray, gray))
        
        self._pixmap = QPixmap.fromImage(img)
    
    def add_erase(self, rect, color=None):
        """添加擦除修改"""
        if color is None:
            color = QColor(255, 255, 255)
        self.modifications.append({'type': 'erase', 'rect': rect, 'color': color})
        self.get_pixmap(force_refresh=True)
    
    def add_grayscale(self, rect):
        """添加灰度修改"""
        self.modifications.append({'type': 'grayscale', 'rect': rect})
        self.get_pixmap(force_refresh=True)
    
    def undo_last(self):
        """撤销最后一次修改"""
        if self.modifications:
            self.modifications.pop()
            self.get_pixmap(force_refresh=True)
            return True
        return False
    
    def get_pdf_rect(self, display_rect, scale):
        """将显示坐标转换为PDF坐标"""
        factor = 72 / self.dpi / scale
        return fitz.Rect(
            display_rect.x() * factor,
            display_rect.y() * factor,
            (display_rect.x() + display_rect.width()) * factor,
            (display_rect.y() + display_rect.height()) * factor
        )


class PDFViewer(QLabel):
    """PDF页面查看器，支持框选"""
    selection_made = pyqtSignal(QRect)  # 框选完成信号
    text_selected = pyqtSignal(object)  # 文字标签被选中信号
    
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(600, 800)
        self.setStyleSheet("background-color: #404040; border: 1px solid #606060;")
        
        self._pdf_page = None
        self._scale = 1.0
        self._selecting = False
        self._selection_start = QPoint()
        self._selection_end = QPoint()
        self._current_selection = QRect()
        self._show_selection = False
        self._text_labels = []  # 当前页面的DraggableText列表
        self._selected_text = None  # 当前选中的文字标签
        
        self.setMouseTracking(True)
        
    def set_page(self, pdf_page):
        """设置要显示的PDF页面"""
        # 保存当前页面的文字信息
        self._save_text_to_page()
        # 清除旧的文字标签控件
        self._clear_text_labels()
        self._pdf_page = pdf_page
        self.update_display()
        # 从页面数据恢复文字标签
        self._restore_text_from_page()
    
    def set_scale(self, scale):
        """设置缩放比例"""
        self._scale = scale
        self.update_display()
        for label in self._text_labels:
            label.set_scale(scale)
    
    def update_display(self):
        """更新显示"""
        if self._pdf_page is None:
            return
        
        pixmap = self._pdf_page.get_pixmap()
        scaled_pixmap = pixmap.scaled(
            int(pixmap.width() * self._scale),
            int(pixmap.height() * self._scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)
        self.setFixedSize(scaled_pixmap.size())

    def add_text_label(self, text, font, color, x=50, y=50):
        """添加一个可拖动的文字标签"""
        label = DraggableText(text, font, color, parent=self)
        label.set_scale(self._scale)
        label.set_orig_pos(x, y)
        label.selected.connect(self._on_text_selected)
        label.moved.connect(self._on_text_moved)
        label.deleted.connect(self._on_text_deleted)
        label.setFocusPolicy(Qt.ClickFocus)
        self._text_labels.append(label)
        self._on_text_selected(label)
        return label

    def _on_text_selected(self, label):
        """文字标签被选中"""
        if self._selected_text and self._selected_text is not label:
            self._selected_text.set_selected(False)
        self._selected_text = label
        label.set_selected(True)
        self.text_selected.emit(label)

    def _on_text_moved(self):
        """文字标签位置变化"""
        pass

    def _on_text_deleted(self, label):
        """删除文字标签"""
        if label in self._text_labels:
            self._text_labels.remove(label)
        if self._selected_text is label:
            self._selected_text = None
        label.deleteLater()

    def deselect_text(self):
        """取消选中文字"""
        if self._selected_text:
            self._selected_text.set_selected(False)
            self._selected_text = None

    def get_selected_text(self):
        return self._selected_text

    def get_text_labels(self):
        return self._text_labels

    def _save_text_to_page(self):
        """将当前文字标签信息保存到PDFPage"""
        if self._pdf_page is None:
            return
        self._pdf_page.text_items = [lbl.get_text_info() for lbl in self._text_labels]

    def _restore_text_from_page(self):
        """从PDFPage恢复文字标签"""
        if self._pdf_page is None:
            return
        for info in self._pdf_page.text_items:
            font = QFont(info['font_family'], int(info['font_size']))
            font.setBold(info.get('font_bold', False))
            label = DraggableText(info['text'], font, info['color'], parent=self)
            label.set_scale(self._scale)
            label.set_orig_pos(info['orig_x'], info['orig_y'])
            label.selected.connect(self._on_text_selected)
            label.moved.connect(self._on_text_moved)
            label.deleted.connect(self._on_text_deleted)
            label.setFocusPolicy(Qt.ClickFocus)
            self._text_labels.append(label)

    def _clear_text_labels(self):
        """清除所有文字标签控件"""
        for label in self._text_labels:
            label.deleteLater()
        self._text_labels.clear()
        self._selected_text = None

    def remove_last_text(self):
        """移除最后添加的文字标签，返回是否成功"""
        if self._text_labels:
            label = self._text_labels.pop()
            if self._selected_text is label:
                self._selected_text = None
            label.deleteLater()
            return True
        return False
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pdf_page:
            self.deselect_text()
            self._selecting = True
            self._selection_start = event.pos()
            self._selection_end = event.pos()
            self._show_selection = True
            self.update()
    
    def mouseMoveEvent(self, event):
        if self._selecting:
            self._selection_end = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._selection_end = event.pos()
            
            # 计算选择区域（相对于原始图片坐标）
            x1 = min(self._selection_start.x(), self._selection_end.x())
            y1 = min(self._selection_start.y(), self._selection_end.y())
            x2 = max(self._selection_start.x(), self._selection_end.x())
            y2 = max(self._selection_start.y(), self._selection_end.y())
            
            # 转换为原始坐标
            orig_x1 = int(x1 / self._scale)
            orig_y1 = int(y1 / self._scale)
            orig_x2 = int(x2 / self._scale)
            orig_y2 = int(y2 / self._scale)
            
            self._current_selection = QRect(orig_x1, orig_y1, orig_x2 - orig_x1, orig_y2 - orig_y1)
            
            if self._current_selection.width() > 5 and self._current_selection.height() > 5:
                self.selection_made.emit(self._current_selection)
            
            self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if self._show_selection and (self._selecting or self._current_selection.isValid()):
            painter = QPainter(self)
            
            # 绘制选择框
            pen = QPen(QColor(0, 120, 215), 2, Qt.DashLine)
            painter.setPen(pen)
            
            if self._selecting:
                rect = QRect(self._selection_start, self._selection_end).normalized()
            else:
                rect = QRect(
                    int(self._current_selection.x() * self._scale),
                    int(self._current_selection.y() * self._scale),
                    int(self._current_selection.width() * self._scale),
                    int(self._current_selection.height() * self._scale)
                )
            
            # 半透明填充
            painter.fillRect(rect, QColor(0, 120, 215, 30))
            painter.drawRect(rect)
            
            painter.end()
    
    def clear_selection(self):
        """清除选择"""
        self._show_selection = False
        self._current_selection = QRect()
        self.update()
    
    def get_current_selection(self):
        """获取当前选择区域（原始坐标）"""
        return self._current_selection


class PDFEditorWindow(QMainWindow):
    """PDF编辑器主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF编辑器 - 文字擦除与颜色转换")
        self.setMinimumSize(1000, 800)
        
        self._doc = None
        self._pages = []
        self._current_page_idx = 0
        self._fill_color = QColor(255, 255, 255)  # 默认白色填充
        self._source_file_path = None  # 保存源文件路径
        self._text_color = QColor(0, 0, 0)  # 默认文字颜色：黑色
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化UI"""
        # 工具栏
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 打开文件
        self.action_open = QAction("📂 打开PDF (Ctrl+O)", self)
        self.action_open.setShortcut(QKeySequence("Ctrl+O"))
        toolbar.addAction(self.action_open)
        
        # 保存文件
        self.action_save = QAction("💾 导出PDF (Ctrl+S)", self)
        self.action_save.setShortcut(QKeySequence("Ctrl+S"))
        self.action_save.setEnabled(False)
        toolbar.addAction(self.action_save)
        
        toolbar.addSeparator()
        
        # 擦除按钮
        self.action_erase = QAction("🧹 擦除选区 (E)", self)
        self.action_erase.setShortcut(QKeySequence("E"))
        self.action_erase.setEnabled(False)
        toolbar.addAction(self.action_erase)
        
        # 灰度按钮
        self.action_grayscale = QAction("⬛ 转黑白 (G)", self)
        self.action_grayscale.setShortcut(QKeySequence("G"))
        self.action_grayscale.setEnabled(False)
        toolbar.addAction(self.action_grayscale)
        
        # 撤销
        self.action_undo = QAction("↩️ 撤销 (Ctrl+Z)", self)
        self.action_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.action_undo.setEnabled(False)
        toolbar.addAction(self.action_undo)
        
        toolbar.addSeparator()
        
        # 填充颜色选择
        toolbar.addWidget(QLabel(" 填充色: "))
        self.color_combo = QComboBox()
        self.color_combo.addItems(["白色", "自动检测"])
        toolbar.addWidget(self.color_combo)
        
        toolbar.addSeparator()
        
        # 页面导航
        toolbar.addWidget(QLabel(" 页码: "))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setEnabled(False)
        toolbar.addWidget(self.page_spin)
        
        self.page_label = QLabel(" / 0 ")
        toolbar.addWidget(self.page_label)
        
        toolbar.addSeparator()
        
        # 缩放
        toolbar.addWidget(QLabel(" 缩放: "))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%"])
        self.zoom_combo.setCurrentText("100%")
        toolbar.addWidget(self.zoom_combo)
        
        # 文字工具栏
        text_toolbar = QToolBar("文字工具栏")
        text_toolbar.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(text_toolbar)
        
        # 添加文字按钮
        self.action_add_text = QAction("🔤 添加文字 (T)", self)
        self.action_add_text.setShortcut(QKeySequence("T"))
        self.action_add_text.setEnabled(False)
        text_toolbar.addAction(self.action_add_text)
        
        # 删除选中文字
        self.action_del_text = QAction("❌ 删除文字", self)
        self.action_del_text.setEnabled(False)
        text_toolbar.addAction(self.action_del_text)
        
        text_toolbar.addSeparator()
        
        # 字体选择
        text_toolbar.addWidget(QLabel(" 字体: "))
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("SimSun"))
        self.font_combo.setMinimumWidth(150)
        text_toolbar.addWidget(self.font_combo)
        
        # 字号
        text_toolbar.addWidget(QLabel(" 字号: "))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setMinimum(6)
        self.font_size_spin.setMaximum(200)
        self.font_size_spin.setValue(14)
        self.font_size_spin.setSuffix(" pt")
        text_toolbar.addWidget(self.font_size_spin)
        
        # 加粗
        self.action_bold = QAction("B", self)
        self.action_bold.setCheckable(True)
        self.action_bold.setToolTip("加粗")
        font_bold = QFont()
        font_bold.setBold(True)
        text_toolbar.addAction(self.action_bold)
        
        text_toolbar.addSeparator()
        
        # 文字颜色按钮
        self.btn_text_color = QPushButton(" 文字颜色 ")
        self.btn_text_color.setStyleSheet(
            "QPushButton { background-color: #000000; color: white; border: 1px solid #888; padding: 3px 8px; }"
        )
        self.btn_text_color.setToolTip("选择文字颜色")
        text_toolbar.addWidget(self.btn_text_color)
        
        text_toolbar.addSeparator()
        
        # 对齐按钮
        self.action_center_h = QAction("⬌ 水平居中", self)
        self.action_center_h.setToolTip("将选中文字水平居中于页面")
        self.action_center_h.setEnabled(False)
        text_toolbar.addAction(self.action_center_h)
        
        self.action_center_v = QAction("⬍ 垂直居中", self)
        self.action_center_v.setToolTip("将选中文字垂直居中于页面")
        self.action_center_v.setEnabled(False)
        text_toolbar.addAction(self.action_center_v)
        
        # 中央区域
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setStyleSheet("QScrollArea { background-color: #505050; }")
        
        self.viewer = PDFViewer()
        scroll.setWidget(self.viewer)
        layout.addWidget(scroll)
        
        # 状态栏
        self.statusBar().showMessage("请打开PDF文件")
        
        # 提示标签
        hint_label = QLabel("快捷键: W下一页(循环) | ←/→换页 | E擦除 | G转黑白 | T添加文字 | 双击文字编辑 | Del删除文字 | Ctrl+Z撤销")
        hint_label.setStyleSheet("color: #888; padding: 5px;")
        layout.addWidget(hint_label)
    
    def _connect_signals(self):
        """连接信号"""
        self.action_open.triggered.connect(self.open_pdf)
        self.action_save.triggered.connect(self.save_pdf)
        self.action_erase.triggered.connect(self.erase_selection)
        self.action_grayscale.triggered.connect(self.grayscale_selection)
        self.action_undo.triggered.connect(self.undo)
        self.page_spin.valueChanged.connect(self.go_to_page)
        self.zoom_combo.currentTextChanged.connect(self.change_zoom)
        self.viewer.selection_made.connect(self.on_selection_made)
        # 文字工具信号
        self.action_add_text.triggered.connect(self.add_text)
        self.action_del_text.triggered.connect(self.delete_selected_text)
        self.btn_text_color.clicked.connect(self.pick_text_color)
        self.font_combo.currentFontChanged.connect(self._on_font_changed)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        self.action_bold.toggled.connect(self._on_bold_changed)
        self.viewer.text_selected.connect(self._on_text_label_selected)
        self.action_center_h.triggered.connect(self.center_text_horizontal)
        self.action_center_v.triggered.connect(self.center_text_vertical)
    
    def open_pdf(self):
        """打开PDF文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开PDF文件", "", "PDF文件 (*.pdf)"
        )
        if not file_path:
            return
        
        try:
            self._doc = fitz.open(file_path)
            self._source_file_path = file_path  # 保存源文件路径
            self._pages = []
            
            for i, page in enumerate(self._doc):
                self._pages.append(PDFPage(page, i))
            
            self._current_page_idx = 0
            self.page_spin.setMaximum(len(self._pages))
            self.page_spin.setValue(1)
            self.page_spin.setEnabled(True)
            self.page_label.setText(f" / {len(self._pages)} ")
            
            self.action_save.setEnabled(True)
            self.action_undo.setEnabled(True)
            self.action_add_text.setEnabled(True)
            
            self._show_current_page()
            self.statusBar().showMessage(f"已打开: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开PDF文件:\n{str(e)}")
    
    def _show_current_page(self):
        """显示当前页面"""
        if not self._pages:
            return
        
        page = self._pages[self._current_page_idx]
        self.viewer.set_page(page)
        self.viewer.clear_selection()
    
    def go_to_page(self, page_num):
        """跳转到指定页面"""
        if 1 <= page_num <= len(self._pages):
            self._current_page_idx = page_num - 1
            self._show_current_page()
    
    def change_zoom(self, zoom_text):
        """改变缩放"""
        zoom = int(zoom_text.replace("%", "")) / 100
        self.viewer.set_scale(zoom)
    
    def on_selection_made(self, rect):
        """选择区域完成"""
        self.action_erase.setEnabled(True)
        self.action_grayscale.setEnabled(True)
        self.statusBar().showMessage(f"已选择区域: ({rect.x()}, {rect.y()}) - {rect.width()}x{rect.height()}")
    
    def keyPressEvent(self, event):
        """处理键盘事件 - W换页"""
        if not self._pages:
            return super().keyPressEvent(event)
        
        if event.key() == Qt.Key_W:
            # 下一页，到最后一页后回到第一页
            if self._current_page_idx < len(self._pages) - 1:
                self.page_spin.setValue(self._current_page_idx + 2)
            else:
                self.page_spin.setValue(1)  # 回到第一页
        elif event.key() == Qt.Key_Left or event.key() == Qt.Key_PageUp:
            # 上一页
            if self._current_page_idx > 0:
                self.page_spin.setValue(self._current_page_idx)
        elif event.key() == Qt.Key_Right or event.key() == Qt.Key_PageDown:
            # 下一页
            if self._current_page_idx < len(self._pages) - 1:
                self.page_spin.setValue(self._current_page_idx + 2)
        else:
            super().keyPressEvent(event)
    
    def _get_fill_color(self, rect):
        """获取填充颜色（自动检测或指定颜色）"""
        if self.color_combo.currentText() == "白色":
            return QColor(255, 255, 255)
        
        # 自动检测：采样选区边缘像素获取背景色
        page = self._pages[self._current_page_idx]
        pixmap = page.get_pixmap()
        img = pixmap.toImage()
        
        colors = []
        # 采样四边的像素
        for x in range(rect.x(), rect.x() + rect.width(), 5):
            if 0 <= x < img.width():
                if 0 <= rect.y() < img.height():
                    colors.append(img.pixelColor(x, rect.y()))
                if 0 <= rect.y() + rect.height() - 1 < img.height():
                    colors.append(img.pixelColor(x, rect.y() + rect.height() - 1))
        
        for y in range(rect.y(), rect.y() + rect.height(), 5):
            if 0 <= y < img.height():
                if 0 <= rect.x() < img.width():
                    colors.append(img.pixelColor(rect.x(), y))
                if 0 <= rect.x() + rect.width() - 1 < img.width():
                    colors.append(img.pixelColor(rect.x() + rect.width() - 1, y))
        
        if not colors:
            return QColor(255, 255, 255)
        
        # 计算平均颜色
        r = sum(c.red() for c in colors) // len(colors)
        g = sum(c.green() for c in colors) // len(colors)
        b = sum(c.blue() for c in colors) // len(colors)
        
        return QColor(r, g, b)
    
    def erase_selection(self):
        """擦除选中区域"""
        selection = self.viewer.get_current_selection()
        if not selection.isValid() or selection.width() < 5:
            QMessageBox.warning(self, "提示", "请先框选一个区域")
            return
        
        page = self._pages[self._current_page_idx]
        fill_color = self._get_fill_color(selection)
        page.add_erase(selection, fill_color)
        
        self.viewer.update_display()
        self.viewer.clear_selection()
        self.action_erase.setEnabled(False)
        self.action_grayscale.setEnabled(False)
        self.statusBar().showMessage("已擦除选中区域")
    
    def grayscale_selection(self):
        """将选中区域转为黑白"""
        selection = self.viewer.get_current_selection()
        if not selection.isValid() or selection.width() < 5:
            QMessageBox.warning(self, "提示", "请先框选一个区域")
            return
        
        page = self._pages[self._current_page_idx]
        page.add_grayscale(selection)
        
        self.viewer.update_display()
        self.viewer.clear_selection()
        self.action_erase.setEnabled(False)
        self.action_grayscale.setEnabled(False)
        self.statusBar().showMessage("已将选中区域转为黑白")
    
    def undo(self):
        """撤销最后一次修改"""
        if not self._pages:
            return
        
        page = self._pages[self._current_page_idx]
        # 先尝试撤销文字标签
        if self.viewer.remove_last_text():
            self.statusBar().showMessage("已撤销文字")
            return
        if page.undo_last():
            self.viewer.update_display()
            self.statusBar().showMessage("已撤销")
        else:
            self.statusBar().showMessage("没有可撤销的操作")
    
    def _get_current_font(self):
        """获取当前工具栏设置的字体"""
        font = QFont(self.font_combo.currentFont().family(), self.font_size_spin.value())
        font.setBold(self.action_bold.isChecked())
        return font

    def add_text(self):
        """添加文字标签到当前页面"""
        if not self._pages:
            return
        dialog = MultiLineTextDialog(self, title="添加文字", label="请输入文字内容（支持换行）:")
        if not dialog.exec_():
            return
        text = dialog.get_text()
        if not text:
            return
        font = self._get_current_font()
        self.viewer.add_text_label(text, font, self._text_color)
        self.statusBar().showMessage("已添加文字，拖动可移动位置，双击可编辑")
    
    def delete_selected_text(self):
        """删除选中的文字标签"""
        label = self.viewer.get_selected_text()
        if label:
            self.viewer._on_text_deleted(label)
            self.action_del_text.setEnabled(False)
            self.statusBar().showMessage("已删除文字")
        else:
            self.statusBar().showMessage("请先选中一个文字标签")

    def pick_text_color(self):
        """选择文字颜色"""
        color = QColorDialog.getColor(self._text_color, self, "选择文字颜色")
        if color.isValid():
            self._text_color = color
            r, g, b = color.red(), color.green(), color.blue()
            # 根据亮度决定按钮文字颜色
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            text_col = "white" if lum < 128 else "black"
            self.btn_text_color.setStyleSheet(
                f"QPushButton {{ background-color: rgb({r},{g},{b}); color: {text_col}; border: 1px solid #888; padding: 3px 8px; }}"
            )
            # 如果有选中的文字，实时更新颜色
            label = self.viewer.get_selected_text()
            if label:
                label.update_color(color)

    def _on_font_changed(self, font):
        """字体改变时更新选中文字"""
        label = self.viewer.get_selected_text()
        if label:
            new_font = QFont(font.family(), self.font_size_spin.value())
            new_font.setBold(self.action_bold.isChecked())
            label.update_font(new_font)

    def _on_font_size_changed(self, size):
        """字号改变时更新选中文字"""
        label = self.viewer.get_selected_text()
        if label:
            new_font = QFont(self.font_combo.currentFont().family(), size)
            new_font.setBold(self.action_bold.isChecked())
            label.update_font(new_font)

    def _on_bold_changed(self, checked):
        """加粗切换时更新选中文字"""
        label = self.viewer.get_selected_text()
        if label:
            new_font = QFont(self.font_combo.currentFont().family(), self.font_size_spin.value())
            new_font.setBold(checked)
            label.update_font(new_font)

    def _on_text_label_selected(self, label):
        """文字标签被选中时，同步工具栏状态"""
        self.action_del_text.setEnabled(True)
        self.action_center_h.setEnabled(True)
        self.action_center_v.setEnabled(True)
        info = label.get_text_info()
        # 临时断开信号避免循环
        self.font_combo.blockSignals(True)
        self.font_size_spin.blockSignals(True)
        self.action_bold.blockSignals(True)
        
        self.font_combo.setCurrentFont(QFont(info['font_family']))
        self.font_size_spin.setValue(int(info['font_size']))
        self.action_bold.setChecked(info.get('font_bold', False))
        self._text_color = info['color']
        r, g, b = info['color'].red(), info['color'].green(), info['color'].blue()
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        text_col = "white" if lum < 128 else "black"
        self.btn_text_color.setStyleSheet(
            f"QPushButton {{ background-color: rgb({r},{g},{b}); color: {text_col}; border: 1px solid #888; padding: 3px 8px; }}"
        )
        
        self.font_combo.blockSignals(False)
        self.font_size_spin.blockSignals(False)
        self.action_bold.blockSignals(False)

    def center_text_horizontal(self):
        """将选中文字水平居中于页面"""
        label = self.viewer.get_selected_text()
        if not label or not self._pages:
            return
        page = self._pages[self._current_page_idx]
        pixmap = page.get_pixmap()
        page_width = pixmap.width()
        text_width = label.width() / label._scale  # 原始宽度
        new_x = (page_width - text_width) / 2
        label.set_orig_pos(new_x, label._orig_y)
        self.statusBar().showMessage("已水平居中")

    def center_text_vertical(self):
        """将选中文字垂直居中于页面"""
        label = self.viewer.get_selected_text()
        if not label or not self._pages:
            return
        page = self._pages[self._current_page_idx]
        pixmap = page.get_pixmap()
        page_height = pixmap.height()
        text_height = label.height() / label._scale  # 原始高度
        new_y = (page_height - text_height) / 2
        label.set_orig_pos(label._orig_x, new_y)
        self.statusBar().showMessage("已垂直居中")

    def _generate_output_filename(self):
        """生成输出文件名（原文件名+1）"""
        import os
        import re
        
        if not self._source_file_path:
            return ""
        
        dir_path = os.path.dirname(self._source_file_path)
        basename = os.path.basename(self._source_file_path)
        name, ext = os.path.splitext(basename)
        
        # 检查文件名末尾是否已有数字
        match = re.match(r'^(.+?)(\d+)$', name)
        if match:
            base_name = match.group(1)
            num = int(match.group(2)) + 1
            new_name = f"{base_name}{num}{ext}"
        else:
            new_name = f"{name}1{ext}"
        
        return os.path.join(dir_path, new_name)
    
    def save_pdf(self):
        """导出修改后的PDF"""
        if not self._doc:
            return
        
        # 保存当前页面的文字标签信息
        self.viewer._save_text_to_page()
        
        # 自动生成默认文件名
        default_path = self._generate_output_filename()
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出PDF文件", default_path, "PDF文件 (*.pdf)"
        )
        if not file_path:
            return
        
        self.statusBar().showMessage("正在导出PDF，请稍候...")
        QApplication.processEvents()
        
        try:
            import tempfile
            import os
            
            export_dpi = 300  # 导出DPI，比显示DPI更高以保证清晰度
            
            # 创建新文档
            new_doc = fitz.open()
            
            for idx, page_data in enumerate(self._pages):
                self.statusBar().showMessage(f"正在处理第 {idx+1}/{len(self._pages)} 页...")
                QApplication.processEvents()
                
                has_modifications = len(page_data.modifications) > 0
                has_text = len(page_data.text_items) > 0
                
                if not has_modifications and not has_text:
                    # 未修改的页面：直接从源PDF复制，保留矢量内容
                    new_doc.insert_pdf(self._doc, from_page=idx, to_page=idx)
                    continue
                
                # 修改过的页面：以高DPI重新渲染
                mat = fitz.Matrix(export_dpi / 72, export_dpi / 72)
                pix = page_data.page.get_pixmap(matrix=mat)
                qt_img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                qt_pixmap = QPixmap.fromImage(qt_img.copy())
                
                # 重新应用擦除/灰度修改（按导出DPI缩放坐标）
                scale_ratio = export_dpi / page_data.dpi
                if has_modifications:
                    painter = QPainter(qt_pixmap)
                    for mod in page_data.modifications:
                        r = mod['rect']
                        scaled_rect = QRect(
                            int(r.x() * scale_ratio), int(r.y() * scale_ratio),
                            int(r.width() * scale_ratio), int(r.height() * scale_ratio)
                        )
                        if mod['type'] == 'erase':
                            painter.fillRect(scaled_rect, mod.get('color', QColor(255, 255, 255)))
                        elif mod['type'] == 'grayscale':
                            # 取出区域转灰度
                            region_img = qt_pixmap.toImage().copy(scaled_rect)
                            for y in range(region_img.height()):
                                for x in range(region_img.width()):
                                    c = region_img.pixelColor(x, y)
                                    gray = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                                    region_img.setPixelColor(x, y, QColor(gray, gray, gray))
                            painter.drawImage(scaled_rect, region_img)
                    painter.end()
                
                # 绘制文字标签
                if has_text:
                    painter = QPainter(qt_pixmap)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setRenderHint(QPainter.TextAntialiasing)
                    for info in page_data.text_items:
                        font = QFont(info['font_family'], int(info['font_size']))
                        font.setBold(info.get('font_bold', False))
                        # 按导出DPI与显示DPI的比例缩放字体
                        font.setPointSizeF(info['font_size'] * scale_ratio)
                        painter.setFont(font)
                        painter.setPen(info['color'])
                        draw_x = int(info['orig_x'] * scale_ratio) + 3
                        draw_y = int(info['orig_y'] * scale_ratio) + 3
                        text_rect = QRect(draw_x, draw_y, qt_pixmap.width() - draw_x, qt_pixmap.height() - draw_y)
                        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, info['text'])
                    painter.end()
                
                # 导出为JPEG（体积更小）
                img = qt_pixmap.toImage().convertToFormat(QImage.Format_RGB888)
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_path = temp_file.name
                temp_file.close()
                img.save(temp_path, 'JPEG', 95)
                
                # 创建新页面并插入图像
                orig_page = page_data.page
                new_page = new_doc.new_page(width=orig_page.rect.width, height=orig_page.rect.height)
                new_page.insert_image(new_page.rect, filename=temp_path)
                
                os.unlink(temp_path)
            
            new_doc.save(file_path, deflate=True, garbage=4)
            new_doc.close()
            
            self.statusBar().showMessage(f"已导出: {file_path}")
            QMessageBox.information(self, "成功", f"PDF已成功导出到:\n{file_path}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"导出失败:\n{str(e)}")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置深色主题
    palette = app.palette()
    palette.setColor(palette.Window, QColor(53, 53, 53))
    palette.setColor(palette.WindowText, Qt.white)
    palette.setColor(palette.Base, QColor(25, 25, 25))
    palette.setColor(palette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(palette.ToolTipBase, Qt.white)
    palette.setColor(palette.ToolTipText, Qt.white)
    palette.setColor(palette.Text, Qt.white)
    palette.setColor(palette.Button, QColor(53, 53, 53))
    palette.setColor(palette.ButtonText, Qt.white)
    palette.setColor(palette.BrightText, Qt.red)
    palette.setColor(palette.Link, QColor(42, 130, 218))
    palette.setColor(palette.Highlight, QColor(42, 130, 218))
    palette.setColor(palette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    window = PDFEditorWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
