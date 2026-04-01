import sys
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea, QToolBar,
    QAction, QSpinBox, QMessageBox, QStatusBar, QComboBox
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QCursor, QKeySequence


class PDFPage:
    """管理单个PDF页面的数据和修改"""
    def __init__(self, page, page_num, dpi=150):
        self.page = page
        self.page_num = page_num
        self.dpi = dpi
        self.modifications = []  # 存储修改记录: {'type': 'erase'/'grayscale', 'rect': QRect, 'color': QColor}
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
        
        self.setMouseTracking(True)
        
    def set_page(self, pdf_page):
        """设置要显示的PDF页面"""
        self._pdf_page = pdf_page
        self.update_display()
    
    def set_scale(self, scale):
        """设置缩放比例"""
        self._scale = scale
        self.update_display()
    
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
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pdf_page:
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
        hint_label = QLabel("快捷键: W下一页(循环) | ←/→换页 | E擦除 | G转黑白 | Ctrl+Z撤销")
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
        if page.undo_last():
            self.viewer.update_display()
            self.statusBar().showMessage("已撤销")
        else:
            self.statusBar().showMessage("没有可撤销的操作")
    
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
            # 创建新文档
            new_doc = fitz.open()
            
            for idx, page_data in enumerate(self._pages):
                self.statusBar().showMessage(f"正在处理第 {idx+1}/{len(self._pages)} 页...")
                QApplication.processEvents()
                
                # 获取修改后的pixmap
                qt_pixmap = page_data.get_pixmap()
                
                # QPixmap -> QImage -> 临时PNG文件 -> PyMuPDF
                img = qt_pixmap.toImage()
                img = img.convertToFormat(QImage.Format_RGB888)
                
                # 保存为临时PNG
                import tempfile
                import os
                temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                temp_path = temp_file.name
                temp_file.close()
                
                img.save(temp_path, 'PNG')
                
                # 计算PDF页面尺寸（点）
                orig_page = page_data.page
                pdf_width = orig_page.rect.width
                pdf_height = orig_page.rect.height
                
                # 创建新页面
                new_page = new_doc.new_page(width=pdf_width, height=pdf_height)
                
                # 插入图像
                new_page.insert_image(new_page.rect, filename=temp_path)
                
                # 删除临时文件
                os.unlink(temp_path)
            
            new_doc.save(file_path)
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
