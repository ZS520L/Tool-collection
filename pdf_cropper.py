"""
PDF裁剪工具 - PyQt5实时预览
============================
支持四边独立裁剪，实时预览效果，满意后保存
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QFileDialog, QGroupBox, QSpinBox,
    QScrollArea, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage, QFont
from PyPDF2 import PdfReader, PdfWriter
import fitz  # PyMuPDF for rendering


# 可爱风格样式表
CUTE_STYLE = """
QMainWindow {
    background-color: #FFF5F5;
}

QGroupBox {
    font-size: 14px;
    font-weight: bold;
    color: #E91E63;
    border: 2px solid #FFCDD2;
    border-radius: 15px;
    margin-top: 10px;
    padding-top: 15px;
    background-color: #FFFFFF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 8px;
    background-color: #FFFFFF;
}

QPushButton {
    background-color: #FF8A80;
    color: white;
    border: none;
    border-radius: 12px;
    padding: 12px 20px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #FF5252;
}

QPushButton:pressed {
    background-color: #D32F2F;
}

QPushButton:disabled {
    background-color: #FFCDD2;
    color: #FFFFFF;
}

QPushButton#saveBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 #FF6B6B, stop:1 #FFE66D);
    font-size: 15px;
    padding: 15px;
}

QPushButton#saveBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 #FF5252, stop:1 #FFD93D);
}

QPushButton#resetBtn {
    background-color: #B39DDB;
}

QPushButton#resetBtn:hover {
    background-color: #9575CD;
}

QSpinBox {
    border: 2px solid #FFCDD2;
    border-radius: 8px;
    padding: 5px 10px;
    background-color: #FFFFFF;
    font-size: 13px;
    min-height: 30px;
}

QSpinBox:focus {
    border-color: #FF8A80;
}

QSpinBox::up-button, QSpinBox::down-button {
    width: 20px;
    border-radius: 4px;
}

QLabel {
    color: #555;
    font-size: 13px;
}

QLabel#titleLabel {
    color: #E91E63;
    font-size: 16px;
    font-weight: bold;
}

QLabel#fileInfo {
    background-color: #FFF8E1;
    border: 1px solid #FFECB3;
    border-radius: 8px;
    padding: 10px;
    color: #795548;
}

QLabel#sizeInfo {
    background-color: #E8F5E9;
    border: 1px solid #C8E6C9;
    border-radius: 8px;
    padding: 10px;
    color: #4CAF50;
    font-weight: bold;
}

QScrollArea {
    border: 3px solid #FFCDD2;
    border-radius: 15px;
    background-color: #FAFAFA;
}

QFrame#cropFrame {
    background-color: #FCE4EC;
    border: 2px solid #F8BBD9;
    border-radius: 12px;
    padding: 10px;
}
"""


class PDFCropper(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf_path = None
        self.pdf_doc = None
        self.original_page = None
        self.crop_values = {'top': 0, 'bottom': 0, 'left': 0, 'right': 0}
        self.init_ui()
        
    def resizeEvent(self, event):
        """窗口大小变化时刷新预览"""
        super().resizeEvent(event)
        if self.pdf_doc is not None:
            self.update_preview()
        
    def init_ui(self):
        self.setWindowTitle('🎀 PDF裁剪小工具 ✨')
        self.setMinimumSize(1100, 750)
        self.setStyleSheet(CUTE_STYLE)
        
        # 主窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 左侧：预览区域
        preview_group = QGroupBox('🖼️ 预览区域')
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(15, 20, 15, 15)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.preview_label = QLabel('📄 请打开PDF文件开始裁剪~')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet('''
            background-color: #FAFAFA; 
            border: none;
            font-size: 16px;
            color: #BDBDBD;
        ''')
        self.preview_label.setMinimumSize(600, 500)
        self.scroll_area.setWidget(self.preview_label)
        preview_layout.addWidget(self.scroll_area)
        
        main_layout.addWidget(preview_group, stretch=3)
        
        # 右侧：控制面板（固定宽度，自适应高度）
        control_panel = QWidget()
        control_panel.setFixedWidth(280)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setSpacing(12)
        control_layout.setContentsMargins(10, 10, 10, 10)
        
        # 标题
        title = QLabel('✂️ 裁剪设置')
        title.setObjectName('titleLabel')
        title.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(title)
        
        # 打开文件按钮
        self.open_btn = QPushButton('📂 打开PDF文件')
        self.open_btn.clicked.connect(self.open_pdf)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        control_layout.addWidget(self.open_btn)
        
        # 文件信息
        self.file_info = QLabel('🎯 未加载文件')
        self.file_info.setObjectName('fileInfo')
        self.file_info.setWordWrap(True)
        self.file_info.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.file_info)
        
        # 裁剪控制
        crop_frame = QFrame()
        crop_frame.setObjectName('cropFrame')
        crop_layout = QVBoxLayout(crop_frame)
        crop_layout.setSpacing(12)
        
        crop_title = QLabel('📏 裁剪边距')
        crop_title.setStyleSheet('font-weight: bold; color: #E91E63;')
        crop_layout.addWidget(crop_title)
        
        # 上边裁剪
        self.top_spin = self.create_spin_control('⬆️ 上边:', crop_layout)
        # 下边裁剪
        self.bottom_spin = self.create_spin_control('⬇️ 下边:', crop_layout)
        # 左边裁剪
        self.left_spin = self.create_spin_control('⬅️ 左边:', crop_layout)
        # 右边裁剪
        self.right_spin = self.create_spin_control('➡️ 右边:', crop_layout)
        
        control_layout.addWidget(crop_frame)
        
        # 尺寸信息
        self.size_info = QLabel('📐 原始: -\n✨ 裁剪后: -')
        self.size_info.setObjectName('sizeInfo')
        self.size_info.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.size_info)
        
        # 重置按钮
        reset_btn = QPushButton('🔄 重置全部')
        reset_btn.setObjectName('resetBtn')
        reset_btn.clicked.connect(self.reset_crop)
        reset_btn.setCursor(Qt.PointingHandCursor)
        control_layout.addWidget(reset_btn)
        
        # 保存按钮
        self.save_btn = QPushButton('💾 保存裁剪结果')
        self.save_btn.setObjectName('saveBtn')
        self.save_btn.clicked.connect(self.save_pdf)
        self.save_btn.setEnabled(False)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        control_layout.addWidget(self.save_btn)
        
        # 底部提示
        tip = QLabel('💡 灰色区域将被裁掉~')
        tip.setStyleSheet('color: #9E9E9E; font-size: 11px;')
        tip.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(tip)
        
        # 使用ScrollArea包装右侧面板，让它垂直居中
        right_wrapper = QWidget()
        right_wrapper_layout = QVBoxLayout(right_wrapper)
        right_wrapper_layout.addStretch()
        right_wrapper_layout.addWidget(control_panel)
        right_wrapper_layout.addStretch()
        right_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        
        main_layout.addWidget(right_wrapper, stretch=0)
        
    def create_spin_control(self, label_text, parent_layout):
        """创建一个带标签的SpinBox控件"""
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(label_text)
        label.setMinimumWidth(70)
        label.setStyleSheet('font-weight: 500;')
        spin = QSpinBox()
        spin.setRange(0, 500)
        spin.setValue(0)
        spin.setSuffix(' px')
        spin.valueChanged.connect(self.update_preview)
        spin.setCursor(Qt.PointingHandCursor)
        row.addWidget(label)
        row.addWidget(spin, stretch=1)
        parent_layout.addLayout(row)
        return spin
        
    def open_pdf(self):
        """打开PDF文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择PDF文件', 
            'D:/AUST001/AlphaEvolve/results',
            'PDF文件 (*.pdf)'
        )
        if file_path:
            self.pdf_path = file_path
            try:
                self.pdf_doc = fitz.open(file_path)
                self.original_page = self.pdf_doc[0]
                
                # 更新文件信息
                rect = self.original_page.rect
                self.file_info.setText(f'📄 {os.path.basename(file_path)}\n'
                                       f'📐 {rect.width:.0f} × {rect.height:.0f} pt')
                
                self.save_btn.setEnabled(True)
                self.reset_crop()
                self.update_preview()
            except Exception as e:
                QMessageBox.critical(self, '错误', f'无法打开PDF: {e}')
                
    def update_preview(self):
        """更新预览图像"""
        if self.pdf_doc is None:
            return
            
        # 获取裁剪值
        top = self.top_spin.value()
        bottom = self.bottom_spin.value()
        left = self.left_spin.value()
        right = self.right_spin.value()
        
        self.crop_values = {'top': top, 'bottom': bottom, 'left': left, 'right': right}
        
        # 获取原始页面尺寸
        page = self.pdf_doc[0]
        orig_rect = page.rect
        
        # 计算裁剪后的矩形
        new_rect = fitz.Rect(
            orig_rect.x0 + left,
            orig_rect.y0 + top,
            orig_rect.x1 - right,
            orig_rect.y1 - bottom
        )
        
        # 更新尺寸信息
        new_width = max(0, orig_rect.width - left - right)
        new_height = max(0, orig_rect.height - top - bottom)
        self.size_info.setText(
            f'📐 原始: {orig_rect.width:.0f} × {orig_rect.height:.0f}\n'
            f'✨ 裁剪后: {new_width:.0f} × {new_height:.0f}'
        )
        
        # 渲染预览 (自适应缩放)
        # 计算合适的缩放比例，让图片适应预览区域
        scroll_width = self.scroll_area.viewport().width() - 20
        scroll_height = self.scroll_area.viewport().height() - 20
        
        scale_x = scroll_width / orig_rect.width if orig_rect.width > 0 else 1
        scale_y = scroll_height / orig_rect.height if orig_rect.height > 0 else 1
        zoom = min(scale_x, scale_y, 2.0)  # 最大2倍缩放
        zoom = max(zoom, 0.5)  # 最小0.5倍缩放
        
        mat = fitz.Matrix(zoom, zoom)
        
        # 渲染整页
        pix = page.get_pixmap(matrix=mat)
        
        # 转换为QImage
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        
        # 在图像上绘制裁剪框
        from PyQt5.QtGui import QPainter, QPen, QColor
        pixmap = QPixmap.fromImage(img)
        painter = QPainter(pixmap)
        
        # 绘制裁剪区域外的半透明遮罩
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.setPen(Qt.NoPen)
        
        # 上边遮罩
        if top > 0:
            painter.drawRect(0, 0, pixmap.width(), int(top * zoom))
        # 下边遮罩
        if bottom > 0:
            painter.drawRect(0, pixmap.height() - int(bottom * zoom), pixmap.width(), int(bottom * zoom))
        # 左边遮罩
        if left > 0:
            painter.drawRect(0, int(top * zoom), int(left * zoom), pixmap.height() - int((top + bottom) * zoom))
        # 右边遮罩
        if right > 0:
            painter.drawRect(pixmap.width() - int(right * zoom), int(top * zoom), 
                           int(right * zoom), pixmap.height() - int((top + bottom) * zoom))
        
        # 绘制裁剪边界线
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.DashLine))
        crop_rect = (
            int(left * zoom),
            int(top * zoom),
            pixmap.width() - int((left + right) * zoom),
            pixmap.height() - int((top + bottom) * zoom)
        )
        painter.drawRect(*crop_rect)
        
        painter.end()
        
        self.preview_label.setPixmap(pixmap)
        
    def reset_crop(self):
        """重置裁剪值"""
        self.top_spin.setValue(0)
        self.bottom_spin.setValue(0)
        self.left_spin.setValue(0)
        self.right_spin.setValue(0)
        
    def save_pdf(self):
        """保存裁剪后的PDF"""
        if self.pdf_path is None:
            return
            
        # 获取保存路径
        default_name = os.path.splitext(self.pdf_path)[0] + '_cropped.pdf'
        save_path, _ = QFileDialog.getSaveFileName(
            self, '保存裁剪后的PDF',
            default_name,
            'PDF文件 (*.pdf)'
        )
        
        if save_path:
            try:
                # 使用PyPDF2进行裁剪保存
                reader = PdfReader(self.pdf_path)
                writer = PdfWriter()
                
                page = reader.pages[0]
                box = page.mediabox
                
                # 应用裁剪
                page.mediabox.lower_left = (
                    float(box.left) + self.crop_values['left'],
                    float(box.bottom) + self.crop_values['bottom']
                )
                page.mediabox.upper_right = (
                    float(box.right) - self.crop_values['right'],
                    float(box.top) - self.crop_values['top']
                )
                
                writer.add_page(page)
                
                with open(save_path, 'wb') as f:
                    writer.write(f)
                    
                QMessageBox.information(self, '🎉 保存成功', f'✨ PDF已保存到:\n{save_path}')
                
            except Exception as e:
                QMessageBox.critical(self, '错误', f'保存失败: {e}')


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = PDFCropper()
    window.show()
    
    # 如果命令行传入了文件路径，自动打开
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        window.pdf_path = sys.argv[1]
        window.open_pdf()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
