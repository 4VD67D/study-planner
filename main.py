# -*- coding: utf-8 -*-
"""Учебный планировщик — программа для учёта учебных заданий.

Возможности: добавление, просмотр, изменение, удаление заданий,
смена статуса, поиск по названию, просмотр просроченных и ближайших
заданий, автоматическое сохранение в базе данных SQLite.

Запуск:  python main.py [путь_к_файлу_базы_данных]

Требуется только стандартная библиотека Python 3.8+ (tkinter, sqlite3).
"""

import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:  # tkinter не установлен — работа с окном невозможна
    tk = None
    ttk = None
    messagebox = None

# --------------------------------------------------------------------------
# Константы
# --------------------------------------------------------------------------
APP_TITLE = "Учебный планировщик"
APP_VERSION = "1.0"
DB_FILE_NAME = "planner.db"

DATE_FORMAT = "%d.%m.%Y"          # формат даты на экране: ДД.ММ.ГГГГ
UPCOMING_DAYS = 7                 # «ближайшие» — срок в пределах 7 дней
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 1000
MIN_YEAR = 2000
MAX_YEAR = 2100

STATUS_NOT_STARTED = "Не начато"
STATUS_IN_PROGRESS = "В процессе"
STATUS_DONE = "Выполнено"
STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_DONE)

FILTER_ALL = "Все задания"
FILTER_OVERDUE = "Просроченные"
FILTER_UPCOMING = "Ближайшие (7 дней)"
FILTERS = (FILTER_ALL, FILTER_OVERDUE, FILTER_UPCOMING)

STATE_NORMAL = "normal"
STATE_DONE = "done"
STATE_OVERDUE = "overdue"
STATE_UPCOMING = "upcoming"

EXIT_OK = 0
EXIT_DB_ERROR = 1
EXIT_NO_TKINTER = 2

# --------------------------------------------------------------------------
# Тексты сообщений
# --------------------------------------------------------------------------
MSG_TITLE_EMPTY = "Введите название задания."
MSG_TITLE_TOO_LONG = "Название слишком длинное (не более %d символов)." % MAX_TITLE_LENGTH
MSG_DESC_TOO_LONG = "Описание слишком длинное (не более %d символов)." % MAX_DESCRIPTION_LENGTH
MSG_DATE_EMPTY = "Введите дату сдачи в формате ДД.ММ.ГГГГ."
MSG_DATE_INVALID = ("Дата введена неверно. Используйте формат ДД.ММ.ГГГГ "
                    "и существующую дату, например 25.12.2026.")
MSG_DATE_RANGE = "Год в дате сдачи должен быть от %d до %d." % (MIN_YEAR, MAX_YEAR)
MSG_STATUS_INVALID = "Выбран недопустимый статус."
MSG_SELECT_TASK = "Сначала выберите задание в списке."
MSG_CONFIRM_DELETE = "Удалить задание «{title}»?\nЭто действие нельзя отменить."
MSG_TASK_NOT_FOUND = "Задание не найдено (возможно, оно уже удалено). Список обновлён."
MSG_DB_ERROR = ("Ошибка при работе с базой данных:\n{error}\n\n"
                "Повторите операцию. Если ошибка повторяется, закройте программу "
                "и запустите её снова.")
MSG_DB_OPEN_ERROR = ("Не удалось открыть базу данных:\n{path}\n\nПричина: {error}\n\n"
                     "Закройте другие копии программы, проверьте права доступа к папке. "
                     "Если файл повреждён, переименуйте его (например, в planner_old.db) "
                     "и запустите программу снова — будет создана новая пустая база.")
MSG_UNEXPECTED = ("Произошла непредвиденная ошибка:\n{error}\n\n"
                  "Данные, сохранённые ранее, не потеряны. Повторите действие "
                  "или перезапустите программу.")
MSG_NO_TKINTER = ("Не найден модуль tkinter. Переустановите Python с сайта python.org, "
                  "отметив компонент «tcl/tk and IDLE».")

INFO_ADDED = "Задание добавлено."
INFO_UPDATED = "Задание изменено."
INFO_DELETED = "Задание удалено."
INFO_STATUS_CHANGED = "Статус изменён на «{status}»."
INFO_STATUS_SAME = "Задание уже имеет статус «{status}»."
INFO_EMPTY = "Список пуст. Нажмите «Добавить», чтобы создать первое задание."
INFO_NOTHING_FOUND = "Заданий, подходящих под условия поиска, нет."
INFO_COUNT = "Показано заданий: {shown} из {total}"


# --------------------------------------------------------------------------
# Модель и проверка данных
# --------------------------------------------------------------------------
class ValidationError(ValueError):
    """Ошибка проверки введённых данных. field — имя поля формы."""

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.field = field


@dataclass
class Task:
    id: int
    title: str
    description: str
    due_date: date
    status: str
    created_at: str


def parse_date(text: str) -> date:
    """Преобразует строку ДД.ММ.ГГГГ в дату; при ошибке — ValidationError."""
    text = (text or "").strip()
    if not text:
        raise ValidationError(MSG_DATE_EMPTY, "due")
    try:
        value = datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        raise ValidationError(MSG_DATE_INVALID, "due")
    if not MIN_YEAR <= value.year <= MAX_YEAR:
        raise ValidationError(MSG_DATE_RANGE, "due")
    return value


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def validate_task_fields(title: str, description: str, due_text: str,
                         status: str) -> Tuple[str, str, date, str]:
    """Проверяет поля задания. Возвращает очищенные значения или
    выбрасывает ValidationError."""
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        raise ValidationError(MSG_TITLE_EMPTY, "title")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValidationError(MSG_TITLE_TOO_LONG, "title")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(MSG_DESC_TOO_LONG, "description")
    due = parse_date(due_text)
    if status not in STATUSES:
        raise ValidationError(MSG_STATUS_INVALID, "status")
    return title, description, due, status


def task_state(task: Task, today: Optional[date] = None) -> str:
    """Определяет состояние задания: выполнено / просрочено / ближайшее / обычное."""
    today = today or date.today()
    if task.status == STATUS_DONE:
        return STATE_DONE
    days = (task.due_date - today).days
    if days < 0:
        return STATE_OVERDUE
    if days <= UPCOMING_DAYS:
        return STATE_UPCOMING
    return STATE_NORMAL


def state_text(task: Task, today: Optional[date] = None) -> str:
    """Текст для столбца «Состояние» (не зависит от цвета строки)."""
    today = today or date.today()
    state = task_state(task, today)
    days = (task.due_date - today).days
    if state == STATE_OVERDUE:
        return "Просрочено на %d дн." % (-days)
    if state == STATE_UPCOMING:
        return "Сегодня" if days == 0 else "Через %d дн." % days
    return ""


def filter_tasks(tasks: List[Task], query: str = "", mode: str = FILTER_ALL,
                 today: Optional[date] = None) -> List[Task]:
    """Поиск по названию (без учёта регистра) и фильтр по режиму просмотра."""
    today = today or date.today()
    needle = (query or "").strip().casefold()
    result = []
    for task in tasks:
        if needle and needle not in task.title.casefold():
            continue
        state = task_state(task, today)
        if mode == FILTER_OVERDUE and state != STATE_OVERDUE:
            continue
        if mode == FILTER_UPCOMING and state != STATE_UPCOMING:
            continue
        result.append(task)
    return result


# --------------------------------------------------------------------------
# Работа с базой данных
# --------------------------------------------------------------------------
_STATUS_LIST_SQL = ", ".join("'%s'" % s for s in STATUSES)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    due_date    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT '%s' CHECK (status IN (%s)),
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks (due_date);
""" % (STATUS_NOT_STARTED, _STATUS_LIST_SQL)


def default_db_path() -> Path:
    """Файл базы лежит рядом с программой (или с .exe, если программа собрана)."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / DB_FILE_NAME


class TaskRepository:
    """Хранилище заданий в SQLite. Каждое изменение сразу сохраняется (commit)."""

    def __init__(self, db_path):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(str(self.path), timeout=5)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.executescript(SCHEMA_SQL)   # создаёт таблицу при первом запуске
            self.conn.commit()
        except sqlite3.Error:
            self.conn.close()
            raise

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        try:
            due = date.fromisoformat(row["due_date"])
        except ValueError:
            raise sqlite3.DatabaseError(
                "в записи №%s некорректная дата «%s»" % (row["id"], row["due_date"]))
        return Task(row["id"], row["title"], row["description"], due,
                    row["status"], row["created_at"])

    def add_task(self, title: str, description: str, due: date,
                 status: str = STATUS_NOT_STARTED) -> int:
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO tasks (title, description, due_date, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, description, due.isoformat(), status, created))
        return cur.lastrowid

    def update_task(self, task_id: int, title: str, description: str,
                    due: date, status: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE tasks SET title = ?, description = ?, due_date = ?, status = ? "
                "WHERE id = ?",
                (title, description, due.isoformat(), status, task_id))
        return cur.rowcount > 0

    def set_status(self, task_id: int, status: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        return cur.rowcount > 0

    def delete_task(self, task_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self) -> List[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY due_date, id").fetchall()
        return [self._row_to_task(r) for r in rows]


# --------------------------------------------------------------------------
# Графический интерфейс
# --------------------------------------------------------------------------
class TaskDialog:
    """Модальное окно добавления / изменения задания."""

    def __init__(self, parent, title: str, task: Optional[Task] = None):
        self.parent = parent
        self.result: Optional[Tuple[str, str, date, str]] = None

        win = self.window = tk.Toplevel(parent)
        win.title(title)
        win.resizable(False, False)
        win.transient(parent)

        self.title_var = tk.StringVar(value=task.title if task else "")
        self.due_var = tk.StringVar(
            value=format_date(task.due_date if task else date.today()))
        self.status_var = tk.StringVar(
            value=task.status if task else STATUS_NOT_STARTED)

        frame = ttk.Frame(win, padding=12)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="Название *").grid(row=0, column=0, sticky="w", pady=4)
        self.title_entry = ttk.Entry(frame, textvariable=self.title_var, width=50)
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text="Описание").grid(row=1, column=0, sticky="nw", pady=4)
        self.desc_text = tk.Text(frame, width=50, height=6, wrap="word")
        self.desc_text.grid(row=1, column=1, sticky="ew", pady=4)
        if task:
            self.desc_text.insert("1.0", task.description)

        ttk.Label(frame, text="Дата сдачи *").grid(row=2, column=0, sticky="w", pady=4)
        date_row = ttk.Frame(frame)
        date_row.grid(row=2, column=1, sticky="w", pady=4)
        self.due_entry = ttk.Entry(date_row, textvariable=self.due_var, width=14)
        self.due_entry.pack(side="left")
        ttk.Label(date_row, text="  формат ДД.ММ.ГГГГ").pack(side="left")

        ttk.Label(frame, text="Статус").grid(row=3, column=0, sticky="w", pady=4)
        self.status_combo = ttk.Combobox(frame, textvariable=self.status_var,
                                         values=STATUSES, state="readonly", width=20)
        self.status_combo.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="* — обязательные поля").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 8))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Сохранить", command=self._on_save).pack(
            side="left", padx=4)
        ttk.Button(buttons, text="Отмена", command=self._on_cancel).pack(
            side="left", padx=4)

        win.bind("<Escape>", lambda event: self._on_cancel())
        self.title_entry.bind("<Return>", lambda event: self._on_save())
        self.due_entry.bind("<Return>", lambda event: self._on_save())
        win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._center()
        self.title_entry.focus_set()

    def _center(self) -> None:
        self.window.update_idletasks()
        x = self.parent.winfo_rootx() + (self.parent.winfo_width()
                                         - self.window.winfo_width()) // 2
        y = self.parent.winfo_rooty() + (self.parent.winfo_height()
                                         - self.window.winfo_height()) // 3
        self.window.geometry("+%d+%d" % (max(x, 0), max(y, 0)))

    def _on_save(self) -> None:
        description = self.desc_text.get("1.0", "end-1c")
        try:
            self.result = validate_task_fields(
                self.title_var.get(), description,
                self.due_var.get(), self.status_var.get())
        except ValidationError as error:
            messagebox.showwarning(APP_TITLE, str(error), parent=self.window)
            if error.field == "title":
                self.title_entry.focus_set()
            elif error.field == "description":
                self.desc_text.focus_set()
            elif error.field == "due":
                self.due_entry.focus_set()
            return
        self.window.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> Optional[Tuple[str, str, date, str]]:
        self.window.grab_set()
        self.window.wait_window()
        return self.result


class PlannerApp:
    """Главное окно программы."""

    COLUMNS = (
        ("num", "№", 45, "center"),
        ("title", "Название", 330, "w"),
        ("due", "Срок сдачи", 100, "center"),
        ("status", "Статус", 100, "center"),
        ("state", "Состояние", 150, "w"),
    )

    def __init__(self, root, repo: TaskRepository):
        self.root = root
        self.repo = repo
        self.shown: List[Task] = []

        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        self.message_var = tk.StringVar()
        self.count_var = tk.StringVar()

        root.title("%s %s" % (APP_TITLE, APP_VERSION))
        root.minsize(820, 540)
        root.geometry("900x600")
        root.report_callback_exception = self._on_unexpected_error
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_style()
        self._build_widgets()
        self.search_var.trace_add("write", lambda *args: self.refresh())
        self.refresh()

    # ----- построение окна -------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style()

        def fixed_map(option):
            # обход ошибки Tk 8.6.9: цвета строк Treeview не применялись
            return [e for e in style.map("Treeview", query_opt=option)
                    if e[:2] != ("!disabled", "!selected")]

        style.map("Treeview", foreground=fixed_map("foreground"),
                  background=fixed_map("background"))

    def _build_widgets(self) -> None:
        root = self.root

        top = ttk.Frame(root, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Поиск по названию:").pack(side="left")
        search_entry = ttk.Entry(top, textvariable=self.search_var, width=30)
        search_entry.pack(side="left", padx=6)
        ttk.Button(top, text="Сбросить", command=self.reset_search).pack(side="left")
        ttk.Label(top, text="   Показать:").pack(side="left")
        self.filter_combo = ttk.Combobox(top, textvariable=self.filter_var,
                                         values=FILTERS, state="readonly", width=22)
        self.filter_combo.pack(side="left", padx=6)
        self.filter_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())

        middle = ttk.Frame(root, padding=(10, 4))
        middle.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            middle, columns=[c[0] for c in self.COLUMNS],
            show="headings", selectmode="browse", height=12)
        for key, heading, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "title"))
        scrollbar = ttk.Scrollbar(middle, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")
        self.tree.tag_configure(STATE_OVERDUE, foreground="#B00020")
        self.tree.tag_configure(STATE_UPCOMING, foreground="#A65D00")
        self.tree.tag_configure(STATE_DONE, foreground="#777777")
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.show_details())
        self.tree.bind("<Double-1>", lambda event: self.edit_task())
        self.tree.bind("<Delete>", lambda event: self.delete_task())

        details_frame = ttk.LabelFrame(root, text="Сведения о выбранном задании",
                                       padding=6)
        details_frame.pack(fill="x", padx=10, pady=4)
        self.details = tk.Text(details_frame, height=6, wrap="word",
                               state="disabled", background="#F5F5F5")
        self.details.pack(fill="x")

        buttons = ttk.Frame(root, padding=(10, 4))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить", command=self.add_task).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self.edit_task).pack(
            side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self.delete_task).pack(side="left")
        ttk.Label(buttons, text="     Установить статус:").pack(side="left")
        for status in STATUSES:
            ttk.Button(buttons, text=status,
                       command=lambda s=status: self.change_status(s)).pack(
                side="left", padx=2)

        bar = ttk.Frame(root, padding=(10, 4))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.message_var).pack(side="left")
        ttk.Label(bar, textvariable=self.count_var).pack(side="right")

    # ----- вспомогательные методы -------------------------------------------
    def _run_db(self, action: Callable, *args):
        """Выполняет операцию с БД. Возвращает (успех, результат)."""
        try:
            return True, action(*args)
        except sqlite3.Error as error:
            messagebox.showerror(APP_TITLE, MSG_DB_ERROR.format(error=error),
                                 parent=self.root)
            return False, None

    def _selected_id(self) -> Optional[int]:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _require_selection(self) -> Optional[int]:
        task_id = self._selected_id()
        if task_id is None:
            messagebox.showinfo(APP_TITLE, MSG_SELECT_TASK, parent=self.root)
        return task_id

    def _on_unexpected_error(self, exc_type, exc_value, exc_traceback) -> None:
        try:
            messagebox.showerror(APP_TITLE,
                                 MSG_UNEXPECTED.format(error=exc_value),
                                 parent=self.root)
        except Exception:
            pass

    # ----- обновление списка -------------------------------------------------
    def refresh(self, select_id: Optional[int] = None) -> None:
        if select_id is None:
            select_id = self._selected_id()
        ok, all_tasks = self._run_db(self.repo.list_tasks)
        if not ok:
            return
        today = date.today()
        self.shown = filter_tasks(all_tasks, self.search_var.get(),
                                  self.filter_var.get(), today)

        self.tree.delete(*self.tree.get_children())
        for number, task in enumerate(self.shown, start=1):
            self.tree.insert(
                "", "end", iid=str(task.id),
                values=(number, task.title, format_date(task.due_date),
                        task.status, state_text(task, today)),
                tags=(task_state(task, today),))
        if select_id is not None and self.tree.exists(str(select_id)):
            self.tree.selection_set(str(select_id))
            self.tree.see(str(select_id))

        self.count_var.set(INFO_COUNT.format(shown=len(self.shown),
                                             total=len(all_tasks)))
        if not all_tasks:
            self.message_var.set(INFO_EMPTY)
        elif not self.shown:
            self.message_var.set(INFO_NOTHING_FOUND)
        self.show_details()

    def show_details(self) -> None:
        task_id = self._selected_id()
        task = next((t for t in self.shown if t.id == task_id), None)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if task:
            self.details.insert(
                "1.0",
                "Название: %s\nСрок сдачи: %s\nСтатус: %s\nДобавлено: %s\n"
                "Описание: %s" % (task.title, format_date(task.due_date),
                                  task.status, task.created_at,
                                  task.description or "(не указано)"))
        else:
            self.details.insert("1.0", "Выберите задание в списке.")
        self.details.configure(state="disabled")

    def reset_search(self) -> None:
        self.search_var.set("")
        self.filter_var.set(FILTER_ALL)
        self.refresh()

    # ----- операции ------------------------------------------------------------
    def add_task(self) -> None:
        data = TaskDialog(self.root, "Добавление задания").show()
        if data is None:
            return
        title, description, due, status = data
        ok, new_id = self._run_db(self.repo.add_task, title, description, due, status)
        if ok:
            self.refresh(select_id=new_id)
            self.message_var.set(INFO_ADDED)

    def edit_task(self) -> None:
        task_id = self._require_selection()
        if task_id is None:
            return
        ok, task = self._run_db(self.repo.get_task, task_id)
        if not ok:
            return
        if task is None:
            messagebox.showwarning(APP_TITLE, MSG_TASK_NOT_FOUND, parent=self.root)
            self.refresh()
            return
        data = TaskDialog(self.root, "Изменение задания", task).show()
        if data is None:
            return
        title, description, due, status = data
        ok, found = self._run_db(self.repo.update_task, task_id,
                                 title, description, due, status)
        if not ok:
            return
        if not found:
            messagebox.showwarning(APP_TITLE, MSG_TASK_NOT_FOUND, parent=self.root)
            self.refresh()
            return
        self.refresh(select_id=task_id)
        self.message_var.set(INFO_UPDATED)

    def delete_task(self) -> None:
        task_id = self._require_selection()
        if task_id is None:
            return
        ok, task = self._run_db(self.repo.get_task, task_id)
        if not ok:
            return
        if task is None:
            messagebox.showwarning(APP_TITLE, MSG_TASK_NOT_FOUND, parent=self.root)
            self.refresh()
            return
        agree = messagebox.askyesno(
            APP_TITLE, MSG_CONFIRM_DELETE.format(title=task.title),
            default="no", icon="warning", parent=self.root)
        if not agree:
            return
        ok, found = self._run_db(self.repo.delete_task, task_id)
        if not ok:
            return
        if not found:
            messagebox.showwarning(APP_TITLE, MSG_TASK_NOT_FOUND, parent=self.root)
            self.refresh()
            return
        self.refresh()
        self.message_var.set(INFO_DELETED)

    def change_status(self, status: str) -> None:
        task_id = self._require_selection()
        if task_id is None:
            return
        ok, task = self._run_db(self.repo.get_task, task_id)
        if not ok:
            return
        if task is None:
            messagebox.showwarning(APP_TITLE, MSG_TASK_NOT_FOUND, parent=self.root)
            self.refresh()
            return
        if task.status == status:
            self.message_var.set(INFO_STATUS_SAME.format(status=status))
            return
        ok, found = self._run_db(self.repo.set_status, task_id, status)
        if not ok:
            return
        self.refresh(select_id=task_id)
        self.message_var.set(INFO_STATUS_CHANGED.format(status=status))

    def on_close(self) -> None:
        self.repo.close()
        self.root.destroy()


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------
def _enable_dpi_awareness() -> None:
    """Чёткое отображение окна на экранах Windows с масштабированием."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if tk is None:
        print(MSG_NO_TKINTER)
        return EXIT_NO_TKINTER

    db_path = Path(argv[0]) if argv else default_db_path()
    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        repo = TaskRepository(db_path)
    except (sqlite3.Error, OSError) as error:
        root.withdraw()
        messagebox.showerror(
            APP_TITLE, MSG_DB_OPEN_ERROR.format(path=db_path, error=error))
        root.destroy()
        return EXIT_DB_ERROR

    PlannerApp(root, repo)
    root.mainloop()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
