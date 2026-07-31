"""面向业务人员的现代桌面界面。"""

from __future__ import annotations

import json
import logging
import platform
import queue
import threading
from pathlib import Path
from tkinter import END, filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

from . import __version__
from .application import ValidationReport, run_validated_companies, validate_input_directory
from .browser import BrowserConfig
from .errors import InputPersistenceError, InputValidationError, TaskCancelled
from .run_logging import (
    IncrementalLogReader,
    configure_logging,
    create_run_log,
    ensure_application_data_directories,
    list_run_logs,
)
from .resources import application_asset_path
from .workflow import WorkflowConfig

LOGGER = logging.getLogger(__name__)
WINDOWS_UI_FONT_FAMILY = "Microsoft YaHei UI"
WINDOWS_MONOSPACE_FONT_FAMILY = "Consolas"
MACOS_MONOSPACE_FONT_FAMILY = "Menlo"


def platform_monospace_font_family(system: str | None = None) -> str:
    current_system = system or platform.system()
    if current_system == "Windows":
        return WINDOWS_MONOSPACE_FONT_FAMILY
    if current_system == "Darwin":
        return MACOS_MONOSPACE_FONT_FAMILY
    return "monospace"


def configure_platform_fonts(system: str | None = None) -> None:
    """让 Windows 使用系统自带的中文 UI 字体。"""

    if (system or platform.system()) == "Windows":
        ctk.ThemeManager.theme["CTkFont"]["family"] = WINDOWS_UI_FONT_FAMILY


class Palette:
    APP_BG = "#F3F6FB"
    SURFACE = "#FFFFFF"
    SURFACE_MUTED = "#F8FAFC"
    SIDEBAR = "#111827"
    SIDEBAR_HOVER = "#1F2937"
    PRIMARY = "#2468F2"
    PRIMARY_HOVER = "#1D55CE"
    PRIMARY_SOFT = "#EAF1FF"
    TEXT = "#111827"
    MUTED = "#64748B"
    BORDER = "#E2E8F0"
    SUCCESS = "#16A34A"
    SUCCESS_SOFT = "#ECFDF3"
    WARNING = "#D97706"
    WARNING_SOFT = "#FFF7E8"
    DANGER = "#DC2626"
    DANGER_SOFT = "#FEF2F2"
    LOG_BG = "#101827"
    LOG_TEXT = "#D7E0EE"


class DesktopApplication:
    POLL_INTERVAL_MS = 100

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.events: queue.Queue[tuple] = queue.Queue()
        self.report: ValidationReport | None = None
        self.running = False
        self.validating = False
        self.login_event: threading.Event | None = None
        self.current_log: Path | None = None
        self.log_reader: IncrementalLogReader | None = None
        self.cancel_event = threading.Event()
        self.close_when_done = False
        self.closed = False
        self.current_page = "task"
        self.history_paths: list[Path] = []
        self.app_icon_image: Image.Image | None = None
        self.brand_icon: ctk.CTkImage | None = None
        self.window_icon: ImageTk.PhotoImage | None = None
        self.data_directories = ensure_application_data_directories()

        self.input_path = ctk.StringVar()
        self.status = ctk.StringVar(value="等待选择输入目录")
        self.final_submit = ctk.BooleanVar(value=False)

        self.root.title(f"百度资质自动提交工具 {__version__}")
        self.root.geometry("1240x800")
        self.root.minsize(1040, 680)
        self.root.configure(fg_color=Palette.APP_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_window_icon()

        self._configure_table_style()
        self._build_shell()
        self._show_page("task")
        self._refresh_log_history()
        self.root.after(self.POLL_INTERVAL_MS, self._poll_events)

    def _configure_window_icon(self) -> None:
        with Image.open(application_asset_path("app-icon.png")) as source:
            self.app_icon_image = source.convert("RGBA")
        self.window_icon = ImageTk.PhotoImage(
            self.app_icon_image,
            master=self.root,
        )
        self.root.iconphoto(True, self.window_icon)

    def _configure_table_style(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Business.Treeview",
            background=Palette.SURFACE,
            fieldbackground=Palette.SURFACE,
            foreground=Palette.TEXT,
            borderwidth=0,
            relief="flat",
            rowheight=34,
            font=("", 11),
        )
        style.configure(
            "Business.Treeview.Heading",
            background=Palette.SURFACE_MUTED,
            foreground="#475569",
            borderwidth=0,
            relief="flat",
            padding=(10, 8),
            font=("", 10, "bold"),
        )
        style.map(
            "Business.Treeview",
            background=[("selected", Palette.PRIMARY_SOFT)],
            foreground=[("selected", Palette.TEXT)],
        )
        style.configure(
            "Business.Vertical.TScrollbar",
            background="#CBD5E1",
            troughcolor=Palette.SURFACE,
            borderwidth=0,
            arrowsize=0,
        )

    def _build_shell(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        self.content = ctk.CTkFrame(
            self.root,
            fg_color=Palette.APP_BG,
            corner_radius=0,
        )
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self._build_header()
        self.page_host = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
            corner_radius=0,
        )
        self.page_host.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 24))
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_task_page()
        self._build_run_page()
        self._build_history_page()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self.root,
            width=224,
            fg_color=Palette.SIDEBAR,
            corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(6, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(28, 34))
        if self.app_icon_image is None:
            raise RuntimeError("应用图标尚未加载")
        self.brand_icon = ctk.CTkImage(
            light_image=self.app_icon_image,
            dark_image=self.app_icon_image,
            size=(48, 48),
        )
        ctk.CTkLabel(
            brand,
            text="",
            image=self.brand_icon,
            width=48,
            height=48,
        ).grid(row=0, column=0, rowspan=2)
        ctk.CTkLabel(
            brand,
            text="资质助手",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#FFFFFF",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ctk.CTkLabel(
            brand,
            text="自动提交工作台",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).grid(row=1, column=1, sticky="w", padx=(12, 0))

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = (
            ("task", "任务中心", "01"),
            ("run", "本次运行", "02"),
            ("history", "历史日志", "03"),
        )
        for row, (key, text, number) in enumerate(nav_items, start=1):
            button = ctk.CTkButton(
                sidebar,
                text=f"{number}   {text}",
                anchor="w",
                height=44,
                corner_radius=10,
                fg_color="transparent",
                hover_color=Palette.SIDEBAR_HOVER,
                text_color="#CBD5E1",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda page=key: self._show_page(page),
            )
            button.grid(row=row, column=0, sticky="ew", padx=14, pady=4)
            self.nav_buttons[key] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=7, column=0, sticky="sew", padx=22, pady=24)
        ctk.CTkLabel(
            footer,
            text=f"Version {__version__}",
            text_color="#64748B",
            font=ctk.CTkFont(size=10),
        ).pack(anchor="w")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.content, fg_color="transparent", height=94)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 8))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ctk.CTkLabel(
            header,
            text="任务中心",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=Palette.TEXT,
        )
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = ctk.CTkLabel(
            header,
            text="选择输入目录，确认验证结果后开始自动提交",
            font=ctk.CTkFont(size=12),
            text_color=Palette.MUTED,
        )
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.status_pill = ctk.CTkLabel(
            header,
            textvariable=self.status,
            height=34,
            corner_radius=17,
            fg_color=Palette.PRIMARY_SOFT,
            text_color=Palette.PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
            padx=16,
        )
        self.status_pill.grid(row=0, column=1, rowspan=2, sticky="e")

    def _new_page(self, key: str) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.page_host, fg_color="transparent", corner_radius=0)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page
        return page

    @staticmethod
    def _card(parent, **kwargs) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=Palette.SURFACE,
            border_color=Palette.BORDER,
            border_width=1,
            corner_radius=14,
            **kwargs,
        )

    def _build_task_page(self) -> None:
        page = self._new_page("task")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        directory_card = self._card(page)
        directory_card.grid(row=0, column=0, sticky="ew")
        directory_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            directory_card,
            text="输入目录",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=Palette.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(17, 0))
        ctk.CTkLabel(
            directory_card,
            text="请选择包含公司文件夹的根目录，每次任务都需要重新选择",
            font=ctk.CTkFont(size=11),
            text_color=Palette.MUTED,
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(4, 13))

        input_row = ctk.CTkFrame(directory_card, fg_color="transparent")
        input_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 18))
        input_row.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(
            input_row,
            textvariable=self.input_path,
            height=42,
            corner_radius=9,
            border_color=Palette.BORDER,
            border_width=1,
            fg_color=Palette.SURFACE_MUTED,
            text_color=Palette.TEXT,
            placeholder_text="尚未选择输入目录",
            state="disabled",
        )
        self.path_entry.grid(row=0, column=0, sticky="ew")
        self.validate_button = ctk.CTkButton(
            input_row,
            text="重新验证",
            width=96,
            height=42,
            corner_radius=9,
            fg_color=Palette.SURFACE_MUTED,
            hover_color=Palette.PRIMARY_SOFT,
            border_color=Palette.BORDER,
            border_width=1,
            text_color=Palette.TEXT,
            state="disabled",
            command=self._validate_selected_directory,
        )
        self.validate_button.grid(row=0, column=1, padx=(10, 0))
        self.choose_button = ctk.CTkButton(
            input_row,
            text="选择目录",
            width=112,
            height=42,
            corner_radius=9,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._choose_input_directory,
        )
        self.choose_button.grid(row=0, column=2, padx=(10, 0))

        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=14)
        self.stat_values: dict[str, ctk.CTkLabel] = {}
        stat_items = (
            ("companies", "公司", "家"),
            ("types", "资质类型", "类"),
            ("qualifications", "资质项目", "项"),
            ("files", "上传文件", "个"),
        )
        for column, (key, label, unit) in enumerate(stat_items):
            stats.grid_columnconfigure(column, weight=1)
            card = self._card(stats)
            card.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 6, 0 if column == 3 else 6),
            )
            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=Palette.MUTED,
            ).pack(anchor="w", padx=17, pady=(13, 2))
            value_row = ctk.CTkFrame(card, fg_color="transparent")
            value_row.pack(anchor="w", padx=17, pady=(0, 12))
            value = ctk.CTkLabel(
                value_row,
                text="0",
                font=ctk.CTkFont(size=24, weight="bold"),
                text_color=Palette.TEXT,
            )
            value.pack(side="left")
            ctk.CTkLabel(
                value_row,
                text=unit,
                font=ctk.CTkFont(size=11),
                text_color=Palette.MUTED,
            ).pack(side="left", padx=(5, 0), pady=(8, 0))
            self.stat_values[key] = value

        options = self._card(page)
        options.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        options.grid_columnconfigure(1, weight=1)
        self.final_submit_checkbox = ctk.CTkCheckBox(
            options,
            text="完成后执行全部提交",
            variable=self.final_submit,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=5,
            border_color="#94A3B8",
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
            text_color=Palette.TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.final_submit_checkbox.grid(row=0, column=0, padx=(20, 12), pady=16)
        ctk.CTkLabel(
            options,
            text="不勾选时会填写并保存全部资质，但不会点击最后的“全部提交”",
            text_color=Palette.MUTED,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=1, sticky="w")
        self.start_button = ctk.CTkButton(
            options,
            text="开始运行",
            width=132,
            height=42,
            corner_radius=9,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled",
            command=self._start_run,
        )
        self.start_button.grid(row=0, column=2, padx=18, pady=12)

        result_card = self._card(page)
        result_card.grid(row=3, column=0, sticky="nsew")
        result_card.grid_columnconfigure(0, weight=1)
        result_card.grid_rowconfigure(1, weight=1)
        result_header = ctk.CTkFrame(result_card, fg_color="transparent")
        result_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        result_header.grid_columnconfigure(0, weight=1)
        self.validation_title = ctk.CTkLabel(
            result_header,
            text="输入验证",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Palette.TEXT,
        )
        self.validation_title.grid(row=0, column=0, sticky="w")
        self.validation_meta = ctk.CTkLabel(
            result_header,
            text="等待选择目录",
            font=ctk.CTkFont(size=11),
            text_color=Palette.MUTED,
        )
        self.validation_meta.grid(row=0, column=1, sticky="e")

        self.validation_body = ctk.CTkFrame(
            result_card,
            fg_color=Palette.SURFACE_MUTED,
            corner_radius=10,
        )
        self.validation_body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.validation_body.grid_columnconfigure(0, weight=1)
        self.validation_body.grid_rowconfigure(0, weight=1)
        self._build_validation_views()

    def _build_validation_views(self) -> None:
        self.empty_state = ctk.CTkFrame(
            self.validation_body,
            fg_color="transparent",
        )
        self.empty_state.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(
            self.empty_state,
            text="◎",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#94A3B8",
        ).place(relx=0.5, rely=0.38, anchor="center")
        ctk.CTkLabel(
            self.empty_state,
            text="选择输入目录后，这里会展示完整验证结果",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#475569",
        ).place(relx=0.5, rely=0.52, anchor="center")
        ctk.CTkLabel(
            self.empty_state,
            text="验证通过前不会打开浏览器，也不会执行提交",
            font=ctk.CTkFont(size=11),
            text_color=Palette.MUTED,
        ).place(relx=0.5, rely=0.61, anchor="center")

        self.tree_container = ctk.CTkFrame(
            self.validation_body,
            fg_color=Palette.SURFACE,
            corner_radius=8,
        )
        self.tree_container.grid(row=0, column=0, sticky="nsew")
        self.tree_container.grid_columnconfigure(0, weight=1)
        self.tree_container.grid_rowconfigure(0, weight=1)
        columns = ("url", "types", "qualifications", "files")
        self.validation_tree = ttk.Treeview(
            self.tree_container,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            style="Business.Treeview",
        )
        self.validation_tree.heading("#0", text="公司 / 资质类型")
        self.validation_tree.heading("url", text="清理后的 URL")
        self.validation_tree.heading("types", text="类型")
        self.validation_tree.heading("qualifications", text="资质")
        self.validation_tree.heading("files", text="文件")
        self.validation_tree.column("#0", width=220, minwidth=150)
        self.validation_tree.column("url", width=410, minwidth=220)
        self.validation_tree.column("types", width=65, anchor="center")
        self.validation_tree.column("qualifications", width=65, anchor="center")
        self.validation_tree.column("files", width=65, anchor="center")
        scrollbar = ttk.Scrollbar(
            self.tree_container,
            orient="vertical",
            command=self.validation_tree.yview,
            style="Business.Vertical.TScrollbar",
        )
        self.validation_tree.configure(yscrollcommand=scrollbar.set)
        self.validation_tree.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)

        self.validation_errors = ctk.CTkTextbox(
            self.validation_body,
            fg_color=Palette.DANGER_SOFT,
            border_color="#FECACA",
            border_width=1,
            corner_radius=8,
            text_color="#991B1B",
            font=ctk.CTkFont(size=12),
            wrap="word",
        )
        self.validation_errors.grid(row=0, column=0, sticky="nsew")
        self._show_validation_view("empty")

    def _build_run_page(self) -> None:
        page = self._new_page("run")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        state_card = self._card(page)
        state_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        state_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            state_card,
            text="当前任务",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=Palette.MUTED,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 2))
        self.run_stage_label = ctk.CTkLabel(
            state_card,
            text="尚未开始运行",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=Palette.TEXT,
        )
        self.run_stage_label.grid(row=1, column=0, sticky="w", padx=20)
        self.run_progress = ctk.CTkProgressBar(
            state_card,
            height=7,
            corner_radius=4,
            fg_color=Palette.BORDER,
            progress_color=Palette.PRIMARY,
            mode="indeterminate",
        )
        self.run_progress.grid(row=2, column=0, sticky="ew", padx=20, pady=(12, 17))
        self.run_progress.set(0)

        self.login_button = ctk.CTkButton(
            state_card,
            text="我已完成登录",
            width=126,
            height=40,
            corner_radius=9,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._confirm_login,
        )
        self.login_button.grid(row=0, column=1, rowspan=3, padx=(10, 10), pady=18)
        self.cancel_button = ctk.CTkButton(
            state_card,
            text="取消任务",
            width=98,
            height=40,
            corner_radius=9,
            fg_color=Palette.SURFACE,
            hover_color=Palette.DANGER_SOFT,
            border_color="#FCA5A5",
            border_width=1,
            text_color=Palette.DANGER,
            state="disabled",
            command=self._cancel_run,
        )
        self.cancel_button.grid(row=0, column=2, rowspan=3, padx=(0, 18), pady=18)

        log_card = self._card(page)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 10))
        log_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            log_header,
            text="实时运行日志",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Palette.TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            log_header,
            text="自动保存到应用数据目录",
            font=ctk.CTkFont(size=10),
            text_color=Palette.MUTED,
        ).grid(row=0, column=1, sticky="e")
        self.current_log_text = ctk.CTkTextbox(
            log_card,
            fg_color=Palette.LOG_BG,
            corner_radius=10,
            text_color=Palette.LOG_TEXT,
            font=ctk.CTkFont(family=platform_monospace_font_family(), size=11),
            wrap="none",
        )
        self.current_log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self._set_text(self.current_log_text, "任务开始后，运行日志会显示在这里。\n")

    def _build_history_page(self) -> None:
        page = self._new_page("history")
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)

        list_card = self._card(page, width=260)
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        list_card.grid_propagate(False)
        ctk.CTkLabel(
            list_card,
            text="历史任务",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Palette.TEXT,
        ).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            list_card,
            text="按运行时间倒序排列",
            font=ctk.CTkFont(size=10),
            text_color=Palette.MUTED,
        ).pack(anchor="w", padx=16)
        ctk.CTkButton(
            list_card,
            text="刷新日志",
            height=34,
            corner_radius=8,
            fg_color=Palette.SURFACE_MUTED,
            hover_color=Palette.PRIMARY_SOFT,
            border_color=Palette.BORDER,
            border_width=1,
            text_color=Palette.TEXT,
            command=self._refresh_log_history,
        ).pack(fill="x", padx=14, pady=12)
        self.history_list_frame = ctk.CTkScrollableFrame(
            list_card,
            fg_color="transparent",
            corner_radius=0,
        )
        self.history_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        detail_card = self._card(page)
        detail_card.grid(row=0, column=1, sticky="nsew")
        detail_card.grid_columnconfigure(0, weight=1)
        detail_card.grid_rowconfigure(1, weight=1)
        self.history_title = ctk.CTkLabel(
            detail_card,
            text="日志详情",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Palette.TEXT,
        )
        self.history_title.grid(row=0, column=0, sticky="w", padx=18, pady=(15, 10))
        self.history_text = ctk.CTkTextbox(
            detail_card,
            fg_color=Palette.LOG_BG,
            corner_radius=10,
            text_color=Palette.LOG_TEXT,
            font=ctk.CTkFont(family=platform_monospace_font_family(), size=11),
            wrap="none",
        )
        self.history_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self._set_text(self.history_text, "选择左侧历史任务查看完整日志。\n")

    def _show_page(self, page: str) -> None:
        if page not in self.pages:
            return
        self.pages[page].tkraise()
        self.current_page = page
        page_copy = {
            "task": ("任务中心", "选择输入目录，确认验证结果后开始自动提交"),
            "run": ("本次运行", "查看任务阶段、登录提示和实时运行日志"),
            "history": ("历史日志", "回看每次任务的完整执行记录"),
        }
        title, subtitle = page_copy[page]
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        for key, button in self.nav_buttons.items():
            active = key == page
            button.configure(
                fg_color=Palette.PRIMARY if active else "transparent",
                hover_color=Palette.PRIMARY_HOVER if active else Palette.SIDEBAR_HOVER,
                text_color="#FFFFFF" if active else "#CBD5E1",
            )

    def _set_status(self, text: str, tone: str = "info") -> None:
        tones = {
            "info": (Palette.PRIMARY_SOFT, Palette.PRIMARY),
            "success": (Palette.SUCCESS_SOFT, Palette.SUCCESS),
            "warning": (Palette.WARNING_SOFT, Palette.WARNING),
            "danger": (Palette.DANGER_SOFT, Palette.DANGER),
            "neutral": ("#EEF2F7", "#475569"),
        }
        background, foreground = tones[tone]
        self.status.set(text)
        self.status_pill.configure(fg_color=background, text_color=foreground)

    @staticmethod
    def _set_text(widget: ctk.CTkTextbox, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert(END, content)
        widget.configure(state="disabled")

    def _show_validation_view(self, view: str) -> None:
        for widget in (self.empty_state, self.tree_container, self.validation_errors):
            widget.grid_remove()
        {
            "empty": self.empty_state,
            "tree": self.tree_container,
            "errors": self.validation_errors,
        }[view].grid()

    def _reset_stats(self) -> None:
        for label in self.stat_values.values():
            label.configure(text="0")

    def _choose_input_directory(self) -> None:
        selected = filedialog.askdirectory(title="选择本次任务的输入目录", mustexist=True)
        if not selected:
            return
        self.input_path.set(selected)
        self.report = None
        self.start_button.configure(state="disabled")
        self.validate_button.configure(state="normal")
        self._reset_stats()
        self._show_validation_view("empty")
        self.validation_meta.configure(text="准备验证")
        self._validate_selected_directory()

    def _validate_selected_directory(self) -> None:
        if self.running or self.validating:
            return
        selected = self.input_path.get().strip()
        if not selected:
            messagebox.showwarning("未选择目录", "请先选择输入目录。")
            return
        self.validating = True
        self._set_controls_busy(True)
        self._set_status("正在验证输入", "info")
        self.validation_title.configure(text="正在验证")
        self.validation_meta.configure(text="请稍候…")
        self._show_validation_view("empty")
        threading.Thread(
            target=self._validation_job,
            args=(Path(selected),),
            daemon=True,
            name="input-validation",
        ).start()

    def _validation_job(self, selected: Path) -> None:
        try:
            report = validate_input_directory(selected)
        except (InputValidationError, InputPersistenceError) as exc:
            self.events.put(("validation_error", exc.errors))
        except Exception as exc:
            self.events.put(("validation_error", [f"校验程序异常：{exc}"]))
        else:
            self.events.put(("validation_success", report))

    def _display_validation_report(self, report: ValidationReport) -> None:
        for item in self.validation_tree.get_children():
            self.validation_tree.delete(item)
        for company in report.companies:
            qualification_count = sum(
                len(item.qualifications) for item in company.qualification_types
            )
            file_count = sum(
                len(qualification.files)
                for item in company.qualification_types
                for qualification in item.qualifications
            )
            company_id = self.validation_tree.insert(
                "",
                END,
                text=company.company_name,
                values=(
                    company.url,
                    len(company.qualification_types),
                    qualification_count,
                    file_count,
                ),
                open=True,
            )
            for qualification_type in company.qualification_types:
                type_file_count = sum(
                    len(qualification.files)
                    for qualification in qualification_type.qualifications
                )
                self.validation_tree.insert(
                    company_id,
                    END,
                    text=f"  {qualification_type.type_name}",
                    values=("", "", len(qualification_type.qualifications), type_file_count),
                )
        self.stat_values["companies"].configure(text=str(report.company_count))
        self.stat_values["types"].configure(text=str(report.qualification_type_count))
        self.stat_values["qualifications"].configure(text=str(report.qualification_count))
        self.stat_values["files"].configure(text=str(report.file_count))
        self.validation_title.configure(text="验证通过")
        self.validation_meta.configure(
            text=f"{report.company_count} 家公司 · {report.qualification_count} 项资质"
        )
        self._show_validation_view("tree")

    def _display_validation_errors(self, errors: list[str]) -> None:
        self._reset_stats()
        content = "输入校验失败，浏览器流程尚未启动。\n\n" + "\n".join(
            f"{index}. {item}" for index, item in enumerate(errors, 1)
        )
        self._set_text(self.validation_errors, content)
        self.validation_title.configure(text="发现输入问题")
        self.validation_meta.configure(text=f"{len(errors)} 个错误")
        self._show_validation_view("errors")

    def _start_run(self) -> None:
        if self.running or self.report is None:
            return
        if Path(self.input_path.get()).resolve() != self.report.input_root:
            self.report = None
            self.start_button.configure(state="disabled")
            messagebox.showwarning("需要重新验证", "输入目录已经变化，请重新验证。")
            return
        final_submit = self.final_submit.get()
        final_step = (
            "所有资质完成后，将点击“全部提交”执行最终送审。"
            if final_submit
            else "将填写并保存全部资质，但不会点击最后的“全部提交”。"
        )
        if not messagebox.askokcancel(
            "确认开始",
            f"即将按顺序处理 {self.report.company_count} 家公司。\n\n"
            f"{final_step}\n\n确认继续吗？",
        ):
            return
        self.running = True
        self.cancel_event.clear()
        self.close_when_done = False
        self._set_controls_busy(True)
        self._set_text(self.current_log_text, "")
        self.log_reader = None
        self._show_page("run")
        self._set_status("正在准备任务", "info")
        self.run_stage_label.configure(text="重新复核输入并准备浏览器")
        self.run_progress.start()
        selected = self.report.input_root
        threading.Thread(
            target=self._run_job,
            args=(selected, final_submit),
            daemon=True,
            name="automation-run",
        ).start()

    def _run_job(self, selected: Path, final_submit: bool) -> None:
        self.current_log = create_run_log()
        configure_logging(self.current_log)
        try:
            LOGGER.info("桌面任务开始，版本 %s", __version__)
            LOGGER.info("输入目录：%s", selected)
            LOGGER.info(
                "最终提交：%s",
                "执行全部提交" if final_submit else "跳过全部提交",
            )
            report = validate_input_directory(selected)
            self.events.put(("run_validation_success", report))
            browser_config = BrowserConfig(
                auth_state_path=self.data_directories["auth"] / "storage_state.json",
                screenshot_dir=self.data_directories["screenshots"] / self.current_log.stem,
            )
            result = run_validated_companies(
                report,
                browser_config=browser_config,
                workflow_config=WorkflowConfig(
                    capture_screenshots=False,
                    dry_run=False,
                    final_submit=final_submit,
                ),
                login_prompt=self._wait_for_login_confirmation,
                log_file=self.current_log,
                is_cancelled=self.cancel_event.is_set,
            )
            LOGGER.info(
                "任务结束：成功 %d，失败 %d",
                len(result["successes"]),
                len(result["failures"]),
            )
            self.events.put(("run_complete", result, self.current_log))
        except (InputValidationError, InputPersistenceError) as exc:
            LOGGER.error("%s", exc)
            self.events.put(("run_validation_error", exc.errors, self.current_log))
        except TaskCancelled as exc:
            LOGGER.warning("%s", exc)
            self.events.put(("run_cancelled", str(exc), self.current_log))
        except Exception as exc:
            LOGGER.exception("任务运行失败")
            self.events.put(("run_error", str(exc), self.current_log))

    def _wait_for_login_confirmation(self, message: str) -> str:
        event = threading.Event()
        self.events.put(("login_required", message, event))
        while not event.wait(0.1):
            if self.cancel_event.is_set():
                raise TaskCancelled("用户已取消登录和当前任务")
        if self.cancel_event.is_set():
            raise TaskCancelled("用户已取消登录和当前任务")
        return ""

    def _confirm_login(self) -> None:
        if self.login_event is None:
            return
        self.login_button.configure(state="disabled")
        self._set_status("正在验证登录", "info")
        self.run_stage_label.configure(text="已确认登录，正在验证工作台状态")
        self.login_event.set()
        self.login_event = None

    def _cancel_run(self, *, confirm: bool = True) -> None:
        if not self.running or self.cancel_event.is_set():
            return
        if confirm and not messagebox.askyesno(
            "确认取消",
            "如果当前公司正在提交，将等待该公司稳定结束后停止后续公司。确认取消吗？",
        ):
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.login_button.configure(state="disabled")
        if self.login_event is not None:
            self.login_event.set()
            self.login_event = None
        self._set_status("已请求安全取消", "warning")
        self.run_stage_label.configure(text="等待当前公司稳定结束后停止")

    def _append_log(self, line: str) -> None:
        self.current_log_text.configure(state="normal")
        self.current_log_text.insert(END, line + "\n")
        self.current_log_text.see(END)
        self.current_log_text.configure(state="disabled")

    def _refresh_log_history(self) -> None:
        self.history_paths = list(list_run_logs())
        for widget in self.history_list_frame.winfo_children():
            widget.destroy()
        if not self.history_paths:
            ctk.CTkLabel(
                self.history_list_frame,
                text="暂无历史日志",
                font=ctk.CTkFont(size=11),
                text_color=Palette.MUTED,
            ).pack(pady=24)
            self.history_title.configure(text="日志详情")
            self._set_text(self.history_text, "完成一次任务后，日志会出现在这里。\n")
            return
        for path in self.history_paths:
            ctk.CTkButton(
                self.history_list_frame,
                text=path.stem.replace("run-", ""),
                anchor="w",
                height=38,
                corner_radius=8,
                fg_color="transparent",
                hover_color=Palette.PRIMARY_SOFT,
                text_color="#334155",
                font=ctk.CTkFont(size=11),
                command=lambda selected=path: self._show_history_path(selected),
            ).pack(fill="x", pady=2)

    def _show_history_path(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            content = f"日志读取失败：{exc}"
        self.history_title.configure(text=path.name)
        self._set_text(self.history_text, content)

    def _set_controls_busy(self, busy: bool) -> None:
        regular_state = "disabled" if busy else "normal"
        self.choose_button.configure(state=regular_state)
        self.validate_button.configure(
            state="disabled" if busy or not self.input_path.get() else "normal"
        )
        self.start_button.configure(
            state="disabled" if busy or self.report is None else "normal"
        )
        self.final_submit_checkbox.configure(state=regular_state)
        self.cancel_button.configure(
            state="normal"
            if busy and self.running and not self.cancel_event.is_set()
            else "disabled"
        )

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "validation_success":
                    self.validating = False
                    self.report = event[1]
                    self._display_validation_report(self.report)
                    self._set_status("输入验证通过", "success")
                    self._set_controls_busy(False)
                elif kind == "validation_error":
                    self.validating = False
                    self.report = None
                    self._display_validation_errors(event[1])
                    self._set_status("输入验证失败", "danger")
                    self._set_controls_busy(False)
                elif kind == "run_validation_success":
                    self.report = event[1]
                    self._display_validation_report(self.report)
                    self._set_status("输入复核通过", "success")
                    self.run_stage_label.configure(text="正在打开登录 Chrome")
                elif kind == "run_validation_error":
                    self._finish_running()
                    self.report = None
                    self._display_validation_errors(event[1])
                    self._set_status("运行前复核失败", "danger")
                    self._show_page("task")
                    if not self.close_when_done:
                        messagebox.showerror("输入已发生变化", "\n".join(event[1]))
                    self._close_if_requested()
                elif kind == "login_required":
                    if self.cancel_event.is_set():
                        event[2].set()
                    else:
                        self.login_event = event[2]
                        self.login_button.configure(state="normal")
                        self._set_status("等待人工登录", "warning")
                        self.run_stage_label.configure(text="请在 Chrome 完成登录后返回确认")
                        messagebox.showinfo("需要人工登录", event[1])
                elif kind == "run_complete":
                    result, log_file = event[1], event[2]
                    self._finish_running()
                    failures = result["failures"]
                    busy = result["busy"]
                    final_submission_completed = all(
                        item.get("final_submission_completed")
                        for item in result["successes"]
                    )
                    self._append_log(
                        "\n运行结果：\n" + json.dumps(result, ensure_ascii=False, indent=2)
                    )
                    self._refresh_log_history()
                    if failures:
                        self._set_status("任务存在失败", "danger")
                        self.run_stage_label.configure(
                            text=f"成功 {len(result['successes'])} · 失败 {len(failures)}"
                        )
                    elif busy:
                        self._set_status("任务未全部处理", "warning")
                        self.run_stage_label.configure(text=f"{len(busy)} 家公司由其他任务处理")
                    elif not final_submission_completed:
                        self._set_status("资质填写完成", "success")
                        self.run_stage_label.configure(
                            text=f"已完成 {len(result['successes'])} 家公司 · 未执行最终提交"
                        )
                    else:
                        self._set_status("任务全部完成", "success")
                        self.run_stage_label.configure(
                            text=f"已完成并最终提交 {len(result['successes'])} 家公司"
                        )
                    if self.close_when_done:
                        pass
                    elif failures:
                        messagebox.showerror(
                            "任务完成但存在失败",
                            f"失败 {len(failures)} 家公司。\n日志：{log_file}",
                        )
                    elif busy:
                        messagebox.showwarning(
                            "任务未全部处理",
                            f"{len(busy)} 家公司正在由其他任务处理，本次没有重复提交。\n"
                            f"日志：{log_file}",
                        )
                    elif not final_submission_completed:
                        messagebox.showinfo(
                            "资质填写完成",
                            "全部资质已经填写并校验完成，本次未执行最终提交。\n"
                            f"日志：{log_file}",
                        )
                    else:
                        messagebox.showinfo(
                            "任务完成",
                            f"全部处理并最终提交完成。\n日志：{log_file}",
                        )
                    self._close_if_requested()
                elif kind == "run_cancelled":
                    self._finish_running()
                    self._set_status("任务已安全取消", "warning")
                    self.run_stage_label.configure(text="未开始的公司已标记为取消")
                    self._refresh_log_history()
                    if not self.close_when_done:
                        messagebox.showinfo(
                            "任务已取消",
                            f"{event[1]}\n\n详细日志：{event[2]}",
                        )
                    self._close_if_requested()
                elif kind == "run_error":
                    self._finish_running()
                    self._set_status("任务运行失败", "danger")
                    self.run_stage_label.configure(text="请查看日志定位具体原因")
                    self._refresh_log_history()
                    if not self.close_when_done:
                        messagebox.showerror(
                            "运行失败",
                            f"{event[1]}\n\n详细日志：{event[2]}",
                        )
                    self._close_if_requested()
        except queue.Empty:
            pass
        if self.closed:
            return
        self._read_current_log_updates()
        self.root.after(self.POLL_INTERVAL_MS, self._poll_events)

    def _read_current_log_updates(self) -> None:
        if self.current_log is None or not self.current_log.is_file():
            return
        if self.log_reader is None or self.log_reader.path != self.current_log:
            self.log_reader = IncrementalLogReader(self.current_log)
        addition, reset = self.log_reader.read_new()
        if reset:
            self._set_text(self.current_log_text, "")
        if addition:
            self.current_log_text.configure(state="normal")
            self.current_log_text.insert(END, addition)
            self.current_log_text.see(END)
            self.current_log_text.configure(state="disabled")

    def _finish_running(self) -> None:
        self.running = False
        self.login_event = None
        self.report = None
        self.input_path.set("")
        self._reset_stats()
        self.validation_title.configure(text="输入验证")
        self.validation_meta.configure(text="等待重新选择目录")
        self._show_validation_view("empty")
        self.login_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.run_progress.stop()
        self.run_progress.set(1)
        self._set_controls_busy(False)

    def _on_close(self) -> None:
        if self.validating:
            messagebox.showwarning("正在验证", "请等待当前输入验证结束后再关闭软件。")
            return
        if self.running:
            if messagebox.askyesno(
                "任务进行中",
                "是否安全取消任务并在结束后关闭软件？\n"
                "正在提交的公司会先稳定结束，不会被强制中断。",
            ):
                self.close_when_done = True
                self._cancel_run(confirm=False)
            return
        self.closed = True
        self.root.destroy()

    def _close_if_requested(self) -> None:
        if self.close_when_done:
            self.closed = True
            self.root.destroy()


def main() -> int:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    configure_platform_fonts()
    root = ctk.CTk()
    DesktopApplication(root)
    root.mainloop()
    return 0
