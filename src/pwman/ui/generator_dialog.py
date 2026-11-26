"""Password / passphrase generator dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
    QPushButton, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import AppConfig
from ..core import generator, strength
from ..core.generator import GeneratorOptions, PassphraseOptions
from . import theme
from .widgets import Dialog, StrengthMeter, button, label, tool_button


class GeneratorPanel(QWidget):
    """Options + live preview. Emits ``generated`` with each new value."""

    generated = Signal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.opts = GeneratorOptions.from_dict(config.generator)
        self.phrase_opts = PassphraseOptions.from_dict(config.passphrase)
        self._loading = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Mode switch (segmented buttons)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        for i, text in enumerate(("Password", "Passphrase")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumWidth(110)
            self.mode_group.addButton(b, i)
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # Output
        out_row = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.setFont(theme.monospace_font(13))
        self.output.setMinimumHeight(40)
        self.regen_btn = tool_button("refresh", "Generate another (Ctrl+R)")
        self.regen_btn.setShortcut("Ctrl+R")
        self.copy_btn = tool_button("copy", "Copy to clipboard")
        out_row.addWidget(self.output, 1)
        out_row.addWidget(self.regen_btn)
        out_row.addWidget(self.copy_btn)
        root.addLayout(out_row)

        meter_row = QHBoxLayout()
        self.meter = StrengthMeter()
        self.entropy = label("", muted=True)
        meter_row.addWidget(self.meter, 1)
        meter_row.addWidget(self.entropy)
        root.addLayout(meter_row)
        self.error = label("", error=True, wrap=True)
        self.error.hide()
        root.addWidget(self.error)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_password_page())
        self.stack.addWidget(self._build_passphrase_page())
        root.addWidget(self.stack)
        root.addStretch(1)

        self.mode_group.idClicked.connect(self._mode_changed)
        self.regen_btn.clicked.connect(self.regenerate)
        mode = 1 if config.generator_mode == "passphrase" else 0
        self.mode_group.button(mode).setChecked(True)
        self.stack.setCurrentIndex(mode)
        self._loading = False
        self.regenerate()

    # ------------------------------------------------------------------ pages
    def _build_password_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        len_row = QHBoxLayout()
        len_row.addWidget(label("Length"))
        self.len_slider = QSlider(Qt.Horizontal)
        self.len_slider.setRange(generator.MIN_LENGTH, 64)
        self.len_spin = QSpinBox()
        self.len_spin.setRange(generator.MIN_LENGTH, generator.MAX_LENGTH)
        self.len_spin.setValue(self.opts.length)
        self.len_slider.setValue(min(64, self.opts.length))
        len_row.addWidget(self.len_slider, 1)
        len_row.addWidget(self.len_spin)
        lay.addLayout(len_row)
        self.len_slider.valueChanged.connect(lambda v: self.len_spin.setValue(v))
        self.len_spin.valueChanged.connect(self._length_changed)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(label("Include", muted=True), 0, 0)
        grid.addWidget(label("At least", muted=True), 0, 1)
        self.class_widgets: dict[str, tuple[QCheckBox, QSpinBox]] = {}
        specs = [("upper", "Upper case (A-Z)"), ("lower", "Lower case (a-z)"),
                 ("digits", "Numbers (0-9)"), ("symbols", "Symbols (!@#$...)")]
        for row, (key, text) in enumerate(specs, start=1):
            check = QCheckBox(text)
            check.setChecked(getattr(self.opts, f"use_{key}"))
            spin = QSpinBox()
            spin.setRange(0, generator.MAX_LENGTH)
            spin.setValue(getattr(self.opts, f"min_{key}"))
            spin.setSuffix(" min")
            spin.setEnabled(check.isChecked())
            check.toggled.connect(spin.setEnabled)
            check.toggled.connect(self._options_changed)
            spin.valueChanged.connect(self._options_changed)
            grid.addWidget(check, row, 0)
            grid.addWidget(spin, row, 1)
            self.class_widgets[key] = (check, spin)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        self.ambiguous = QCheckBox("Avoid look-alike characters (0 O o 1 l I | ` ' \")")
        self.ambiguous.setChecked(self.opts.exclude_ambiguous)
        self.ambiguous.toggled.connect(self._options_changed)
        lay.addWidget(self.ambiguous)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.symbols_edit = QLineEdit(self.opts.symbols)
        self.symbols_edit.setFont(theme.monospace_font())
        self.symbols_edit.setToolTip("Which symbols may be used - some sites only allow a few.")
        self.exclude_edit = QLineEdit(self.opts.exclude_chars)
        self.exclude_edit.setFont(theme.monospace_font())
        self.exclude_edit.setPlaceholderText("e.g.  \\ \" '")
        self.symbols_edit.textChanged.connect(self._options_changed)
        self.exclude_edit.textChanged.connect(self._options_changed)
        reset = button("Default", link=True)
        reset.clicked.connect(lambda: self.symbols_edit.setText(generator.DEFAULT_SYMBOLS))
        sym_row = QHBoxLayout()
        sym_row.addWidget(self.symbols_edit, 1)
        sym_row.addWidget(reset)
        form.addRow("Allowed symbols", sym_row)
        form.addRow("Never use", self.exclude_edit)
        lay.addLayout(form)
        return page

    def _build_passphrase_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.words_spin = QSpinBox()
        self.words_spin.setRange(3, 20)
        self.words_spin.setValue(self.phrase_opts.words)
        self.sep_edit = QLineEdit(self.phrase_opts.separator)
        self.sep_edit.setMaxLength(3)
        self.sep_edit.setFixedWidth(60)
        self.cap_check = QCheckBox("Capitalize words")
        self.cap_check.setChecked(self.phrase_opts.capitalize)
        self.num_check = QCheckBox("Include a number")
        self.num_check.setChecked(self.phrase_opts.include_number)
        form.addRow("Words", self.words_spin)
        form.addRow("Separator", self.sep_edit)
        form.addRow("", self.cap_check)
        form.addRow("", self.num_check)
        hint = label("Passphrases are random words - easy to type and remember, and very strong "
                     "with 5 or more words. Great for your master password.", muted=True, wrap=True)
        form.addRow(hint)
        for sig in (self.words_spin.valueChanged, self.sep_edit.textChanged,
                    self.cap_check.toggled, self.num_check.toggled):
            sig.connect(self._options_changed)
        return page

    # ------------------------------------------------------------------ logic
    def _length_changed(self, value: int) -> None:
        self.len_slider.blockSignals(True)
        self.len_slider.setValue(min(64, value))
        self.len_slider.blockSignals(False)
        self._options_changed()

    def _mode_changed(self, mode: int) -> None:
        self.stack.setCurrentIndex(mode)
        self.config.generator_mode = "passphrase" if mode else "password"
        self.regenerate()

    def _collect(self) -> None:
        o = self.opts
        o.length = self.len_spin.value()
        for key, (check, spin) in self.class_widgets.items():
            setattr(o, f"use_{key}", check.isChecked())
            setattr(o, f"min_{key}", spin.value())
        o.exclude_ambiguous = self.ambiguous.isChecked()
        o.symbols = self.symbols_edit.text()
        o.exclude_chars = self.exclude_edit.text()
        p = self.phrase_opts
        p.words = self.words_spin.value()
        p.separator = self.sep_edit.text()
        p.capitalize = self.cap_check.isChecked()
        p.include_number = self.num_check.isChecked()
        self.config.generator = o.to_dict()
        self.config.passphrase = p.to_dict()

    def _options_changed(self, *_):
        if not self._loading:
            self.regenerate()

    def regenerate(self) -> None:
        self._collect()
        passphrase = self.stack.currentIndex() == 1
        try:
            if passphrase:
                value = generator.generate_passphrase(self.phrase_opts)
                bits = self.phrase_opts.entropy_bits()
            else:
                value = generator.generate_password(self.opts)
                bits = self.opts.entropy_bits()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            self.output.clear()
            self.meter.set_report(None)
            self.entropy.clear()
            self.generated.emit("")
            return
        self.error.hide()
        self.output.setText(value)
        self.output.setCursorPosition(0)
        self.meter.set_report(strength.evaluate(value))
        self.entropy.setText(f"{bits:.0f} bits of randomness")
        self.generated.emit(value)

    def value(self) -> str:
        return self.output.text()


class GeneratorDialog(Dialog):
    """Standalone (copy) or picker mode (``use_button=True`` returns the value)."""

    def __init__(self, config: AppConfig, copy_callback=None, use_button=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Password generator")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(label("Password generator", heading=True))
        self.panel = GeneratorPanel(config)
        lay.addWidget(self.panel)
        if copy_callback:
            self.panel.copy_btn.clicked.connect(lambda: copy_callback(self.panel.value()))
        else:
            self.panel.copy_btn.hide()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if use_button:
            cancel = button("Cancel")
            use = button("Use this password", primary=True)
            use.setDefault(True)
            cancel.clicked.connect(self.reject)
            use.clicked.connect(self.accept)
            self.panel.generated.connect(lambda v: use.setEnabled(bool(v)))
            use.setEnabled(bool(self.panel.value()))
            buttons.addWidget(cancel)
            buttons.addWidget(use)
        else:
            close = button("Close")
            close.clicked.connect(self.accept)
            if copy_callback:
                copy = button("Copy", primary=True, icon_name="copy")
                copy.clicked.connect(lambda: copy_callback(self.panel.value()))
                buttons.addWidget(close)
                buttons.addWidget(copy)
            else:
                buttons.addWidget(close)
        lay.addLayout(buttons)

    def value(self) -> str:
        return self.panel.value()
