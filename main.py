from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                              QVBoxLayout, QPushButton, QLabel, QFileDialog, QScrollArea, QSlider, QSpinBox, QCheckBox)
from PySide6.QtCore import Qt, QPoint, QPointF, QSize, QTimer, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
import numpy as np
from scipy.spatial import Delaunay
import cv2
import sys
import imageio
import csv
from dataclasses import dataclass

@dataclass
class MorphPoint:
    """Store points in normalized coordinates (0-1 range)"""
    source: QPointF
    target: QPointF

class ImageCanvas(QLabel):
    def __init__(self, is_target=False, parent=None):
        super().__init__(parent)
        self.points = []  # Will store MorphPoint objects
        self.selected_point = None
        self.dragging = False
        self.image = None
        self.display_triangles = True
        self.is_target = is_target
        self.setMinimumSize(400, 400)
        self.setAlignment(Qt.AlignCenter)
        
        # Setup update timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(33)  # ~30 FPS
    
    def get_image_space_pos(self, widget_pos: QPoint) -> QPointF:
        """Convert widget coordinates to normalized image coordinates (0-1)"""
        if self.image is None or self.pixmap() is None:
            return QPointF(0, 0)
            
        img_rect = self.get_image_rect()
        if not img_rect.isValid():
            return QPointF(0, 0)
            
        # Convert to normalized coordinates
        x = (widget_pos.x() - img_rect.x()) / img_rect.width()
        y = (widget_pos.y() - img_rect.y()) / img_rect.height()
        
        # Clamp to 0-1 range
        x = max(0, min(1, x))
        y = max(0, min(1, y))
        
        return QPointF(x, y)
    
    def get_widget_space_pos(self, image_pos: QPointF) -> QPoint:
        """Convert normalized coordinates (0-1) to widget space"""
        if self.image is None or self.pixmap() is None:
            return QPoint(0, 0)
            
        img_rect = self.get_image_rect()
        if not img_rect.isValid():
            return QPoint(0, 0)
            
        x = int(img_rect.x() + (image_pos.x() * img_rect.width()))
        y = int(img_rect.y() + (image_pos.y() * img_rect.height()))
        
        return QPoint(x, y)
    
    def get_image_rect(self) -> QRectF:
        """Get the actual rectangle where image is displayed in widget space"""
        if self.pixmap() is None:
            return QRectF()
            
        # Get current sizes
        pixmap_size = self.pixmap().size()
        widget_size = self.size()
        
        # Calculate aspect ratios
        pix_ratio = pixmap_size.width() / pixmap_size.height()
        widget_ratio = widget_size.width() / widget_size.height()
        
        if widget_ratio > pix_ratio:
            # Height is the constraint
            h = widget_size.height()
            w = h * pix_ratio
            x = (widget_size.width() - w) / 2
            y = 0
        else:
            # Width is the constraint
            w = widget_size.width()
            h = w / pix_ratio
            x = 0
            y = (widget_size.height() - h) / 2
            
        return QRectF(x, y, w, h)
    
    def set_image(self, image: np.ndarray):
        """Set new image and update display"""
        self.image = image.copy() if image is not None else None
        self.update_display()
    
    def update_display(self):
        """Update the display with current image and points"""
        if self.image is None:
            return
            
        # Convert numpy image to QImage
        height, width = self.image.shape[:2]
        bytes_per_line = 3 * width
        q_img = QImage(self.image.data, width, height, bytes_per_line, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(q_img)
        
        # Scale pixmap to fit widget while maintaining aspect ratio
        pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        # Create painter for annotations
        painter = QPainter(pixmap)
        
        # Draw triangulation
        if self.display_triangles and len(self.points) >= 3:
            points = [(self.get_widget_space_pos(p.target if self.is_target else p.source))
                     for p in self.points]
            points_array = np.array([(p.x(), p.y()) for p in points])
            
            try:
                tri = Delaunay(points_array)
                pen = QPen(QColor(0, 255, 0, 128))
                pen.setWidth(1)
                painter.setPen(pen)
                
                for simplex in tri.simplices:
                    for i in range(3):
                        j = (i + 1) % 3
                        start = points[simplex[i]]
                        end = points[simplex[j]]
                        painter.drawLine(start, end)
            except Exception as e:
                print(f"Triangulation error: {e}")
        
        # Draw points
        pen = QPen(Qt.red)
        pen.setWidth(5)
        painter.setPen(pen)
        for point in self.points:
            pos = self.get_widget_space_pos(point.target if self.is_target else point.source)
            painter.drawPoint(pos)
            
        painter.end()
        self.setPixmap(pixmap)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Convert to normalized coordinates
            pos = self.get_image_space_pos(event.position().toPoint())
            
            # Check if clicking near existing point
            for i, point in enumerate(self.points):
                curr_pos = point.target if self.is_target else point.source
                widget_curr = self.get_widget_space_pos(curr_pos)
                if (event.position().toPoint() - widget_curr).manhattanLength() < 10:
                    self.selected_point = i
                    self.dragging = True
                    return
                    
            # If not near existing point and not target canvas, add new point
            if not self.is_target:
                self.points.append(MorphPoint(pos, pos))
                if hasattr(self.parent(), "points_updated"):
                    self.parent().points_updated()
                    
        elif event.button() == Qt.RightButton and not self.is_target:
            # Only allow deletion on source canvas
            pos = event.position().toPoint()
            for i, point in enumerate(self.points):
                curr_pos = self.get_widget_space_pos(point.source)
                if (pos - curr_pos).manhattanLength() < 10:
                    self.points.pop(i)
                    if hasattr(self.parent(), "points_updated"):
                        self.parent().points_updated()
                    break
    
    def mouseMoveEvent(self, event):
        if self.dragging and self.selected_point is not None:
            pos = self.get_image_space_pos(event.position().toPoint())
            if self.is_target:
                self.points[self.selected_point].target = pos
            else:
                self.points[self.selected_point].source = pos
                
            if hasattr(self.parent(), "points_updated"):
                self.parent().points_updated()
    
    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.selected_point = None

class MorphEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Morph Editor")
        self.resize(1200, 800)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Canvas layout
        canvas_layout = QHBoxLayout()
        
        # Source canvas
        source_scroll = QScrollArea()
        source_scroll.setWidgetResizable(True)
        self.source_canvas = ImageCanvas(is_target=False)
        source_scroll.setWidget(self.source_canvas)
        
        # Target canvas
        target_scroll = QScrollArea()
        target_scroll.setWidgetResizable(True)
        self.target_canvas = ImageCanvas(is_target=True)
        target_scroll.setWidget(self.target_canvas)
        
        canvas_layout.addWidget(source_scroll)
        canvas_layout.addWidget(target_scroll)
        layout.addLayout(canvas_layout)
        
        # Share points between canvases
        self.target_canvas.points = self.source_canvas.points
        
        # Buttons
        button_layout = QHBoxLayout()
        
        load_button = QPushButton("Load Image")
        load_button.clicked.connect(self.load_image)
        
        toggle_triangles = QPushButton("Toggle Triangles")
        toggle_triangles.clicked.connect(self.toggle_triangles)
        
        clear_points = QPushButton("Clear Points")
        clear_points.clicked.connect(self.clear_points)
        
        reset_morph = QPushButton("Reset Morph")
        reset_morph.clicked.connect(self.reset_morph)
        
        button_layout.addWidget(load_button)
        button_layout.addWidget(toggle_triangles)
        button_layout.addWidget(clear_points)
        button_layout.addWidget(reset_morph)
        layout.addLayout(button_layout)
        # Controls
        control_layout = QHBoxLayout()

        save_template_button = QPushButton("Save Template")
        save_template_button.clicked.connect(self.save_template)
        load_template_button = QPushButton("Load Template")
        load_template_button.clicked.connect(self.load_template)
        
        self.frames_input = QSpinBox()
        self.frames_input.setRange(2, 100)
        self.frames_input.setValue(10)
        
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 100)
        self.speed_slider.setValue(50)
        
        self.loop_checkbox = QCheckBox("Loop GIF")
        
        save_gif_button = QPushButton("Save GIF")
        save_gif_button.clicked.connect(self.save_gif)
        
        control_layout.addWidget(QLabel("Frames:"))
        control_layout.addWidget(self.frames_input)
        control_layout.addWidget(QLabel("Speed:"))
        control_layout.addWidget(self.speed_slider)
        control_layout.addWidget(self.loop_checkbox)
        control_layout.addWidget(save_template_button)
        control_layout.addWidget(load_template_button)
        control_layout.addWidget(save_gif_button)
        
        layout.addLayout(control_layout)
        
        # Setup update timer for morph
        self.morph_timer = QTimer(self)
        self.morph_timer.timeout.connect(self.update_morph)
        self.morph_timer.start(33)  # ~30 FPS
        
        self.source_image = None
        self.target_image = None
    
    def load_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image File",
                                                 "", "Images (*.png *.xpm *.jpg *.bmp)")
        if file_name:
            image = cv2.imread(file_name)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            self.source_image = image.copy()
            self.target_image = image.copy()
            
            self.source_canvas.set_image(self.source_image)
            self.target_canvas.set_image(self.target_image)
    
    def toggle_triangles(self):
        self.source_canvas.display_triangles = not self.source_canvas.display_triangles
        self.target_canvas.display_triangles = not self.target_canvas.display_triangles
    
    def clear_points(self):
        self.source_canvas.points.clear()
    
    def reset_morph(self):
        for point in self.source_canvas.points:
            point.target = QPointF(point.source)
    
    def points_updated(self):
        if self.source_image is not None and len(self.source_canvas.points) >= 3:
            self.update_morph()
    
    def update_morph(self):
        if self.source_image is None or len(self.source_canvas.points) < 3:
            return
            
        height, width = self.source_image.shape[:2]
        
        # Convert normalized points to image coordinates
        source_points = np.float32([(p.source.x() * width, p.source.y() * height) 
                                  for p in self.source_canvas.points])
        target_points = np.float32([(p.target.x() * width, p.target.y() * height) 
                                  for p in self.source_canvas.points])
        
        try:
            tri = Delaunay(source_points)
            morphed = self.source_image.copy()
            
            for simplex in tri.simplices:
                src_tri = source_points[simplex]
                dst_tri = target_points[simplex]
                
                warp_mat = cv2.getAffineTransform(src_tri, dst_tri)
                warped = cv2.warpAffine(self.source_image, warp_mat, 
                                      (width, height))
                
                mask = np.zeros_like(self.source_image)
                cv2.fillConvexPoly(mask, dst_tri.astype(np.int32), (1, 1, 1))
                
                morphed = morphed * (1 - mask) + warped * mask
            
            self.target_canvas.set_image(morphed.astype(np.uint8))
        except Exception as e:
            print(f"Morph error: {e}")

    def save_template(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Morph Template", "", "CSV Files (*.csv)")
        if file_name:
            with open(file_name, 'w', newline='') as file:
                writer = csv.writer(file)
                for point in self.source_canvas.points:
                    writer.writerow([point.source.x(), point.source.y(), point.target.x(), point.target.y()])

    def load_template(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Load Morph Template", "", "CSV Files (*.csv)")
        if file_name:
            with open(file_name, 'r') as file:
                reader = csv.reader(file)
                self.source_canvas.points.clear()
                for row in reader:
                    src_x, src_y, tgt_x, tgt_y = map(float, row)
                    self.source_canvas.points.append(MorphPoint(QPointF(src_x, src_y), QPointF(tgt_x, tgt_y)))
            self.target_canvas.points = self.source_canvas.points

    def save_gif(self):
        from PySide6.QtWidgets import QProgressDialog
        progress = QProgressDialog("Generating GIF...", "Cancel", 0, self.frames_input.value(), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        num_frames = self.frames_input.value()
        loop = self.loop_checkbox.isChecked()
        height, width = self.source_canvas.image.shape[:2]
        
        images = []
        for i in range(num_frames):
            progress.setValue(i)
            if progress.wasCanceled():
                return
            t = i / (num_frames - 1)
            morphed = self.interpolate_image(t)
            images.append(morphed)
        
        if loop:
            images += images[::-1]
        
        file_name, _ = QFileDialog.getSaveFileName(self, "Save GIF", "", "GIF Files (*.gif)")
        if file_name:
            progress.setValue(num_frames)
            imageio.mimsave(file_name, images, duration=max(1, 100 - self.speed_slider.value()), loop=0 if loop else 1)
    
    def interpolate_image(self, t):
        height, width = self.source_canvas.image.shape[:2]
        source_points = np.float32([(p.source.x() * width, p.source.y() * height) for p in self.source_canvas.points])
        target_points = np.float32([(p.target.x() * width, p.target.y() * height) for p in self.source_canvas.points])
        
        inter_points = (1 - t) * source_points + t * target_points
        try:
            tri = Delaunay(source_points)
            morphed = np.zeros_like(self.source_canvas.image)
            for simplex in tri.simplices:
                src_tri = source_points[simplex]
                dst_tri = inter_points[simplex]
                warp_mat = cv2.getAffineTransform(src_tri, dst_tri)
                warped = cv2.warpAffine(self.source_canvas.image, warp_mat, (width, height))
                mask = np.zeros_like(self.source_canvas.image)
                cv2.fillConvexPoly(mask, dst_tri.astype(np.int32), (1, 1, 1))
                morphed = morphed * (1 - mask) + warped * mask
            return morphed.astype(np.uint8)
        except Exception as e:
            print(f"Morph error: {e}")
            return self.source_canvas.image


def main():
    app = QApplication(sys.argv)
    editor = MorphEditor()
    editor.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
