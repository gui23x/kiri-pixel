from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    FluentWindow,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SwitchButton,
    Theme,
    setTheme,
)
from rembg import new_session, remove

LOGGER = logging.getLogger("image_editor")

ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"
APP_USER_MODEL_ID = "com.imageeditor.desktop.main"
WINDOWS_PLATFORM = "win32"

WINDOW_WIDTH = 920
WINDOW_HEIGHT = 540
PAGE_MARGIN = 24
PAGE_SPACING = 24
CONTROLS_SPACING = 12
PREVIEW_SIZE = 420
BUSY_RING_SIZE = 32
NOTIFICATION_DURATION_MS = 4000

CHECKER_TILE = 12
CHECKER_LIGHT = QColor(235, 235, 235)
CHECKER_DARK = QColor(200, 200, 200)

INPUT_FILTER = "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
PNG_FILTER = "PNG (*.png)"
ICO_FILTER = "Icone (*.ico)"
PNG_SUFFIX = ".png"
ICO_SUFFIX = ".ico"
NO_BACKGROUND_NAME_SUFFIX = "_sem_fundo"

BACKGROUND_MODELS = ("u2net", "isnet-general-use", "birefnet-general")
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICO_SIDE = 256
ICO_MARGIN_RATIO = 0.03
ALPHA_CONTENT_THRESHOLD = 8
OPAQUE = 255
TRANSPARENT = (0, 0, 0, 0)


@dataclass(frozen=True)
class BackgroundRemovalOptions:
    model_name: str
    alpha_matting: bool


def load_image(path: Path) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    try:
        with Image.open(path) as opened:
            return ImageOps.exif_transpose(opened).convert("RGBA")
    except UnidentifiedImageError as error:
        raise ValueError("O arquivo selecionado nao e uma imagem valida.") from error


@lru_cache(maxsize=None)
def load_session(model_name: str) -> Any:
    return new_session(model_name)


def remove_background(
    image: Image.Image, options: BackgroundRemovalOptions
) -> Image.Image:
    if options.model_name not in BACKGROUND_MODELS:
        raise ValueError(f"Modelo invalido: {options.model_name}")
    result = remove(
        image,
        session=load_session(options.model_name),
        alpha_matting=options.alpha_matting,
    )
    return result.convert("RGBA")


def crop_to_content(image: Image.Image) -> Image.Image:
    visible_mask = image.getchannel("A").point(
        lambda value: OPAQUE if value > ALPHA_CONTENT_THRESHOLD else 0
    )
    bounds = visible_mask.getbbox()
    return image.crop(bounds) if bounds else image


def pad_to_square(image: Image.Image, margin: int) -> Image.Image:
    side = max(image.size) + 2 * margin
    canvas = Image.new("RGBA", (side, side), TRANSPARENT)
    offset = ((side - image.width) // 2, (side - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def prepare_icon_source(image: Image.Image) -> Image.Image:
    content = crop_to_content(image)
    margin = round(max(content.size) * ICO_MARGIN_RATIO)
    square = pad_to_square(content, margin)
    return square.resize((ICO_SIDE, ICO_SIDE), Image.Resampling.LANCZOS)


def save_ico(image: Image.Image, destination: Path) -> None:
    sizes = [(size, size) for size in ICO_SIZES]
    prepare_icon_source(image).save(destination, format="ICO", sizes=sizes)


def save_png(image: Image.Image, destination: Path) -> None:
    image.save(destination, format="PNG")


def to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    raw_bytes = rgba.tobytes("raw", "RGBA")
    qimage = QImage(
        raw_bytes,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    return QPixmap.fromImage(qimage.copy())


def draw_checkerboard(painter: QPainter, width: int, height: int) -> None:
    for row in range(0, height, CHECKER_TILE):
        for column in range(0, width, CHECKER_TILE):
            is_light = ((row + column) // CHECKER_TILE) % 2 == 0
            color = CHECKER_LIGHT if is_light else CHECKER_DARK
            painter.fillRect(column, row, CHECKER_TILE, CHECKER_TILE, color)


def build_preview(image: Image.Image) -> QPixmap:
    scaled = to_pixmap(image).scaled(
        PREVIEW_SIZE,
        PREVIEW_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(scaled.size())
    painter = QPainter(canvas)
    draw_checkerboard(painter, canvas.width(), canvas.height())
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return canvas


class ProcessingThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Image.Image], parent: QWidget) -> None:
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self._operation())
        except Exception as error:
            LOGGER.exception("processing_failed")
            self.failed.emit(str(error))


class EditorInterface(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editor")
        self._source_path: Path | None = None
        self._source_image: Image.Image | None = None
        self._result_image: Image.Image | None = None
        self._thread: ProcessingThread | None = None

        self.preview_label = BodyLabel("Nenhuma imagem carregada", self)
        self.preview_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.open_button = PushButton(FluentIcon.FOLDER, "Abrir imagem", self)
        self.model_selector = ComboBox(self)
        self.model_selector.addItems(list(BACKGROUND_MODELS))
        self.model_selector.setCurrentIndex(0)
        self.alpha_matting_switch = SwitchButton(self)
        self.remove_button = PrimaryPushButton(FluentIcon.PHOTO, "Remover fundo", self)
        self.save_png_button = PushButton(FluentIcon.SAVE, "Salvar PNG", self)
        self.save_ico_button = PushButton(FluentIcon.APPLICATION, "Salvar ICO", self)
        self.busy_ring = IndeterminateProgressRing(self)
        self.busy_ring.setFixedSize(BUSY_RING_SIZE, BUSY_RING_SIZE)

        matting_row = QHBoxLayout()
        matting_row.addWidget(BodyLabel("Refinar bordas", self))
        matting_row.addWidget(self.alpha_matting_switch)
        matting_row.addStretch()

        controls = QVBoxLayout()
        controls.setSpacing(CONTROLS_SPACING)
        controls.addWidget(self.open_button)
        controls.addWidget(BodyLabel("Modelo", self))
        controls.addWidget(self.model_selector)
        controls.addLayout(matting_row)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.save_png_button)
        controls.addWidget(self.save_ico_button)
        controls.addWidget(self.busy_ring, alignment=Qt.AlignmentFlag.AlignLeft)
        controls.addStretch()

        root = QHBoxLayout(self)
        root.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        root.setSpacing(PAGE_SPACING)
        root.addWidget(self.preview_label)
        root.addLayout(controls, stretch=1)

        self.open_button.clicked.connect(self._on_open_clicked)
        self.remove_button.clicked.connect(self._on_remove_clicked)
        self.save_png_button.clicked.connect(self._on_save_png_clicked)
        self.save_ico_button.clicked.connect(self._on_save_ico_clicked)
        self._refresh_controls(busy=False)

    def _working_image(self) -> Image.Image | None:
        if self._result_image is not None:
            return self._result_image
        return self._source_image

    def _refresh_controls(self, busy: bool) -> None:
        has_working_image = self._working_image() is not None
        self.open_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and self._source_image is not None)
        self.save_png_button.setEnabled(not busy and has_working_image)
        self.save_ico_button.setEnabled(not busy and has_working_image)
        self.busy_ring.setVisible(busy)

    def _show_preview(self) -> None:
        image = self._working_image()
        if image is None:
            return
        self.preview_label.setPixmap(build_preview(image))

    def _notify_error(self, message: str) -> None:
        InfoBar.error(
            "Erro",
            message,
            duration=NOTIFICATION_DURATION_MS,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self.window(),
        )

    def _notify_success(self, message: str) -> None:
        InfoBar.success(
            "Concluido",
            message,
            duration=NOTIFICATION_DURATION_MS,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self.window(),
        )

    def _on_open_clicked(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Abrir imagem", "", INPUT_FILTER
        )
        if not selected:
            return
        path = Path(selected)
        try:
            image = load_image(path)
        except (OSError, ValueError) as error:
            LOGGER.warning("load_failed path=%s", path)
            self._notify_error(str(error))
            return
        self._source_path = path
        self._source_image = image
        self._result_image = None
        self._show_preview()
        self._refresh_controls(busy=False)

    def _on_remove_clicked(self) -> None:
        if self._source_image is None:
            return
        options = BackgroundRemovalOptions(
            model_name=self.model_selector.currentText(),
            alpha_matting=self.alpha_matting_switch.isChecked(),
        )
        source = self._source_image
        self._thread = ProcessingThread(
            lambda: remove_background(source, options), self
        )
        self._thread.succeeded.connect(self._on_remove_succeeded)
        self._thread.failed.connect(self._on_remove_failed)
        self._refresh_controls(busy=True)
        self._thread.start()

    def _on_remove_succeeded(self, result: object) -> None:
        if not isinstance(result, Image.Image):
            self._on_remove_failed("Resultado de processamento invalido.")
            return
        self._result_image = result
        self._show_preview()
        self._refresh_controls(busy=False)

    def _on_remove_failed(self, message: str) -> None:
        self._refresh_controls(busy=False)
        self._notify_error(message)

    def _on_save_png_clicked(self) -> None:
        name_suffix = (
            NO_BACKGROUND_NAME_SUFFIX if self._result_image is not None else ""
        )
        self._save(PNG_FILTER, PNG_SUFFIX, name_suffix, save_png)

    def _on_save_ico_clicked(self) -> None:
        self._save(ICO_FILTER, ICO_SUFFIX, "", save_ico)

    def _save(
        self,
        file_filter: str,
        suffix: str,
        name_suffix: str,
        writer: Callable[[Image.Image, Path], None],
    ) -> None:
        image = self._working_image()
        if image is None or self._source_path is None:
            return
        default_path = self._source_path.with_name(
            f"{self._source_path.stem}{name_suffix}{suffix}"
        )
        selected, _ = QFileDialog.getSaveFileName(
            self, "Salvar", str(default_path), file_filter
        )
        if not selected:
            return
        destination = Path(selected).with_suffix(suffix)
        try:
            writer(image, destination)
        except (OSError, ValueError) as error:
            LOGGER.warning("save_failed path=%s", destination)
            self._notify_error(str(error))
            return
        self._notify_success(f"Arquivo salvo em {destination}")


def register_taskbar_identity() -> None:
    if sys.platform != WINDOWS_PLATFORM:
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def load_app_icon() -> QIcon:
    if not ICON_PATH.is_file():
        LOGGER.warning("icon_not_found path=%s", ICON_PATH)
        return QIcon()
    return QIcon(str(ICON_PATH))


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(load_app_icon())
        self.setWindowTitle("Editor de Imagens")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.addSubInterface(EditorInterface(self), FluentIcon.PHOTO, "Editor")
        self.navigationInterface.hide()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","event":"%(message)s"}',
    )
    register_taskbar_identity()
    application = QApplication(sys.argv)
    application.setWindowIcon(load_app_icon())
    setTheme(Theme.AUTO)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
