# -*- coding: utf-8 -*-
"""Автоматические тесты «Учебного планировщика».

Запуск из папки StudyPlanner:  python -m unittest discover -s tests -v

Тесты логики и базы данных не требуют окна. Класс TestInterfaceLogic проверяет
логику главного окна на заменителях (mock) элементов tkinter: реальное окно
при этом не создаётся.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as planner  # noqa: E402

TODAY = date(2026, 10, 14)


def make_task(task_id, title, days, status=planner.STATUS_NOT_STARTED):
    return planner.Task(task_id, title, "", TODAY + timedelta(days=days),
                        status, "2026-10-01 10:00:00")


class TestValidation(unittest.TestCase):
    def test_parse_date_ok(self):
        self.assertEqual(planner.parse_date("25.12.2026"), date(2026, 12, 25))
        self.assertEqual(planner.parse_date(" 5.1.2027 "), date(2027, 1, 5))

    def test_parse_date_errors(self):
        for text in ["", "   ", "abc", "31.02.2026", "2026-12-25", "25.13.2026",
                     "25/12/2026", "25.12.26"]:
            with self.assertRaises(planner.ValidationError, msg=text):
                planner.parse_date(text)

    def test_parse_date_year_range(self):
        with self.assertRaises(planner.ValidationError):
            planner.parse_date("01.01.1999")
        with self.assertRaises(planner.ValidationError):
            planner.parse_date("01.01.2101")

    def test_validate_ok_strips_spaces(self):
        title, desc, due, status = planner.validate_task_fields(
            "  Реферат  ", "  текст ", "01.11.2026", planner.STATUS_IN_PROGRESS)
        self.assertEqual((title, desc), ("Реферат", "текст"))
        self.assertEqual(due, date(2026, 11, 1))
        self.assertEqual(status, planner.STATUS_IN_PROGRESS)

    def test_validate_empty_title(self):
        for title in ["", "    "]:
            with self.assertRaises(planner.ValidationError) as ctx:
                planner.validate_task_fields(title, "", "01.11.2026",
                                             planner.STATUS_NOT_STARTED)
            self.assertEqual(ctx.exception.field, "title")

    def test_validate_lengths(self):
        with self.assertRaises(planner.ValidationError):
            planner.validate_task_fields("a" * 101, "", "01.11.2026",
                                         planner.STATUS_NOT_STARTED)
        with self.assertRaises(planner.ValidationError):
            planner.validate_task_fields("a", "b" * 1001, "01.11.2026",
                                         planner.STATUS_NOT_STARTED)
        planner.validate_task_fields("a" * 100, "b" * 1000, "01.11.2026",
                                     planner.STATUS_NOT_STARTED)

    def test_validate_bad_status(self):
        with self.assertRaises(planner.ValidationError):
            planner.validate_task_fields("a", "", "01.11.2026", "Неизвестно")


class TestStatesAndFilters(unittest.TestCase):
    def setUp(self):
        self.tasks = [
            make_task(1, "Реферат по истории", -2),
            make_task(2, "Лабораторная работа", 0),
            make_task(3, "Курсовой проект", 7),
            make_task(4, "Доклад", 8),
            make_task(5, "Старая работа", -5, planner.STATUS_DONE),
        ]

    def test_states(self):
        states = [planner.task_state(t, TODAY) for t in self.tasks]
        self.assertEqual(states, [planner.STATE_OVERDUE, planner.STATE_UPCOMING,
                                  planner.STATE_UPCOMING, planner.STATE_NORMAL,
                                  planner.STATE_DONE])

    def test_state_text(self):
        self.assertEqual(planner.state_text(self.tasks[0], TODAY), "Просрочено на 2 дн.")
        self.assertEqual(planner.state_text(self.tasks[1], TODAY), "Сегодня")
        self.assertEqual(planner.state_text(self.tasks[2], TODAY), "Через 7 дн.")
        self.assertEqual(planner.state_text(self.tasks[3], TODAY), "")
        self.assertEqual(planner.state_text(self.tasks[4], TODAY), "")

    def test_filters(self):
        ids = lambda items: [t.id for t in items]
        self.assertEqual(ids(planner.filter_tasks(self.tasks, "", planner.FILTER_ALL, TODAY)),
                         [1, 2, 3, 4, 5])
        self.assertEqual(ids(planner.filter_tasks(self.tasks, "", planner.FILTER_OVERDUE, TODAY)), [1])
        self.assertEqual(ids(planner.filter_tasks(self.tasks, "", planner.FILTER_UPCOMING, TODAY)), [2, 3])

    def test_search_case_insensitive_cyrillic(self):
        found = planner.filter_tasks(self.tasks, "РЕФЕРАТ", planner.FILTER_ALL, TODAY)
        self.assertEqual([t.id for t in found], [1])
        found = planner.filter_tasks(self.tasks, "работа", planner.FILTER_ALL, TODAY)
        self.assertEqual([t.id for t in found], [2, 5])

    def test_search_combined_with_filter(self):
        found = planner.filter_tasks(self.tasks, "работа", planner.FILTER_UPCOMING, TODAY)
        self.assertEqual([t.id for t in found], [2])

    def test_search_nothing(self):
        self.assertEqual(planner.filter_tasks(self.tasks, "zzz", planner.FILTER_ALL, TODAY), [])


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "test.db")
        self.repo = planner.TaskRepository(self.path)

    def tearDown(self):
        self.repo.close()
        self.dir.cleanup()

    def test_database_created_automatically_and_empty(self):
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(self.repo.list_tasks(), [])

    def test_add_and_get(self):
        task_id = self.repo.add_task("Реферат", "Описание", date(2026, 11, 1))
        task = self.repo.get_task(task_id)
        self.assertEqual(task.title, "Реферат")
        self.assertEqual(task.description, "Описание")
        self.assertEqual(task.due_date, date(2026, 11, 1))
        self.assertEqual(task.status, planner.STATUS_NOT_STARTED)

    def test_update(self):
        task_id = self.repo.add_task("A", "", date(2026, 11, 1))
        self.assertTrue(self.repo.update_task(task_id, "B", "d", date(2026, 12, 1),
                                              planner.STATUS_IN_PROGRESS))
        task = self.repo.get_task(task_id)
        self.assertEqual((task.title, task.description, task.due_date, task.status),
                         ("B", "d", date(2026, 12, 1), planner.STATUS_IN_PROGRESS))

    def test_set_status(self):
        task_id = self.repo.add_task("A", "", date(2026, 11, 1))
        self.assertTrue(self.repo.set_status(task_id, planner.STATUS_DONE))
        self.assertEqual(self.repo.get_task(task_id).status, planner.STATUS_DONE)

    def test_missing_task_operations(self):
        self.assertIsNone(self.repo.get_task(999))
        self.assertFalse(self.repo.delete_task(999))
        self.assertFalse(self.repo.set_status(999, planner.STATUS_DONE))
        self.assertFalse(self.repo.update_task(999, "a", "", date(2026, 1, 1),
                                               planner.STATUS_DONE))

    def test_delete(self):
        task_id = self.repo.add_task("A", "", date(2026, 11, 1))
        self.assertTrue(self.repo.delete_task(task_id))
        self.assertEqual(self.repo.list_tasks(), [])

    def test_sorted_by_due_date(self):
        self.repo.add_task("поздно", "", date(2026, 12, 1))
        self.repo.add_task("рано", "", date(2026, 10, 1))
        self.assertEqual([t.title for t in self.repo.list_tasks()], ["рано", "поздно"])

    def test_status_check_constraint(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.add_task("A", "", date(2026, 11, 1), "Левый статус")
        self.assertEqual(self.repo.list_tasks(), [])

    def test_data_persists_after_restart(self):
        self.repo.add_task("Сохраняемое задание", "текст", date(2026, 11, 5),
                           planner.STATUS_IN_PROGRESS)
        self.repo.close()
        again = planner.TaskRepository(self.path)
        try:
            tasks = again.list_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].title, "Сохраняемое задание")
            self.assertEqual(tasks[0].status, planner.STATUS_IN_PROGRESS)
        finally:
            again.close()
        self.repo = planner.TaskRepository(self.path)

    def test_corrupted_file_raises_database_error(self):
        bad = os.path.join(self.dir.name, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"this is not a sqlite database" * 50)
        with self.assertRaises(sqlite3.DatabaseError):
            planner.TaskRepository(bad)

    def test_bad_date_in_database_raises_database_error(self):
        self.repo.conn.execute(
            "INSERT INTO tasks (title, description, due_date, status, created_at) "
            "VALUES ('x', '', 'не дата', 'Не начато', '2026-01-01 00:00:00')")
        self.repo.conn.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.repo.list_tasks()

    def test_unusable_path_raises_error(self):
        with self.assertRaises((sqlite3.Error, OSError)):
            planner.TaskRepository(os.path.join(self.dir.name, "нет_папки", "x.db"))

    def test_many_records(self):
        for i in range(2000):
            self.repo.add_task("Задание %d" % i, "", date(2026, 11, 1))
        self.assertEqual(len(self.repo.list_tasks()), 2000)


class FakeStringVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def trace_add(self, *args):
        pass


class TestInterfaceLogic(unittest.TestCase):
    """Проверка логики окна без реального tkinter (на заменителях)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.repo = planner.TaskRepository(os.path.join(self.dir.name, "ui.db"))
        patches = [
            mock.patch.object(planner, "tk", mock.MagicMock()),
            mock.patch.object(planner, "ttk", mock.MagicMock()),
            mock.patch.object(planner, "messagebox", mock.MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        planner.tk.StringVar = FakeStringVar
        self.box = planner.messagebox
        self.root = mock.MagicMock()
        self.app = planner.PlannerApp(self.root, self.repo)
        self.tree = self.app.tree
        self.tree.get_children.return_value = ()
        self.tree.selection.return_value = ()
        self.tree.exists.return_value = False

    def tearDown(self):
        self.repo.close()
        self.dir.cleanup()

    def test_empty_database_message(self):
        self.app.refresh()
        self.assertEqual(self.app.message_var.get(), planner.INFO_EMPTY)
        self.assertIn("0 из 0", self.app.count_var.get())

    def test_add_task_through_dialog(self):
        data = ("Новое", "", date(2026, 11, 1), planner.STATUS_NOT_STARTED)
        with mock.patch.object(planner, "TaskDialog") as dialog:
            dialog.return_value.show.return_value = data
            self.app.add_task()
        self.assertEqual(len(self.repo.list_tasks()), 1)
        self.assertEqual(self.app.message_var.get(), planner.INFO_ADDED)

    def test_add_task_cancelled(self):
        with mock.patch.object(planner, "TaskDialog") as dialog:
            dialog.return_value.show.return_value = None
            self.app.add_task()
        self.assertEqual(self.repo.list_tasks(), [])

    def test_actions_without_selection_show_message(self):
        self.app.edit_task()
        self.app.delete_task()
        self.app.change_status(planner.STATUS_DONE)
        self.assertEqual(self.box.showinfo.call_count, 3)
        self.assertEqual(self.box.showinfo.call_args[0][1], planner.MSG_SELECT_TASK)

    def _add_selected(self):
        task_id = self.repo.add_task("Удаляемое", "", date(2026, 11, 1))
        self.tree.selection.return_value = (str(task_id),)
        return task_id

    def test_delete_requires_confirmation(self):
        task_id = self._add_selected()
        self.box.askyesno.return_value = False
        self.app.delete_task()
        self.assertIsNotNone(self.repo.get_task(task_id))
        self.box.askyesno.return_value = True
        self.app.delete_task()
        self.assertIsNone(self.repo.get_task(task_id))
        self.assertEqual(self.app.message_var.get(), planner.INFO_DELETED)

    def test_change_status(self):
        task_id = self._add_selected()
        self.app.change_status(planner.STATUS_DONE)
        self.assertEqual(self.repo.get_task(task_id).status, planner.STATUS_DONE)
        self.app.change_status(planner.STATUS_DONE)
        self.assertIn("уже имеет статус", self.app.message_var.get())

    def test_edit_task(self):
        task_id = self._add_selected()
        data = ("Изменённое", "d", date(2026, 12, 2), planner.STATUS_IN_PROGRESS)
        with mock.patch.object(planner, "TaskDialog") as dialog:
            dialog.return_value.show.return_value = data
            self.app.edit_task()
        self.assertEqual(self.repo.get_task(task_id).title, "Изменённое")

    def test_task_deleted_elsewhere(self):
        self.tree.selection.return_value = ("12345",)
        self.app.change_status(planner.STATUS_DONE)
        self.box.showwarning.assert_called()
        self.assertEqual(self.box.showwarning.call_args[0][1], planner.MSG_TASK_NOT_FOUND)

    def test_database_error_shows_message_not_crash(self):
        self.repo.close()
        self.app.refresh()
        self.box.showerror.assert_called()
        self.assertIn("Ошибка при работе с базой данных",
                      self.box.showerror.call_args[0][1])

    def test_rows_inserted_on_refresh(self):
        self.repo.add_task("A", "", date(2026, 11, 1))
        self.repo.add_task("B", "", date(2026, 11, 2))
        self.tree.insert.reset_mock()
        self.app.refresh()
        self.assertEqual(self.tree.insert.call_count, 2)

    def test_main_without_tkinter_returns_code(self):
        with mock.patch.object(planner, "tk", None):
            self.assertEqual(planner.main([]), planner.EXIT_NO_TKINTER)


if __name__ == "__main__":
    unittest.main()
