import sys 
import os 
import csv  
import json  
import shutil 
import platform 
import traceback  
from pathlib import Path
from datetime import datetime

import bcrypt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QLineEdit,
    QVBoxLayout, QHBoxLayout, QMessageBox, QTableWidget,
    QTableWidgetItem, QInputDialog, QFileDialog, QDialog,
    QFormLayout, QDateEdit, QStackedWidget, QSizePolicy,
    QListWidget, QListWidgetItem, QSpinBox
)
from PyQt6.QtCore import Qt, QDate, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import QHeaderView


def debug_print(*args, **kwargs):
    print("[LibraryApp]", *args, **kwargs)

def make_writable(path: Path):
    try:
        if path.exists():
            mode = path.stat().st_mode
            path.chmod(mode | 0o200) 
    except Exception as e:
        debug_print("make_writable:", e)

def hide_file_on_windows(path: Path):
    if os.name != 'nt':
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        try:
            os.system(f'attrib +h "{str(path)}"')
        except Exception:
            pass

def choose_data_folder():
    home = Path.home()
    try:
        if platform.system() == "Windows":
            appdata = os.getenv("APPDATA")
            if appdata:
                primary = Path(appdata) / "LibraryApp"
            else:
                primary = home / ".library_app"
        else:
            primary = home / ".library_app"

        primary.mkdir(parents=True, exist_ok=True)
        test = primary / ".writetest"
        try:
            with test.open("w", encoding="utf-8") as f:
                f.write("ok")
            test.unlink()
            return primary
        except Exception as e:
            debug_print("Primary data folder not writable:", primary, e)
            fallback = home / ".library_app"
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                test2 = fallback / ".writetest"
                with test2.open("w", encoding="utf-8") as f2:
                    f2.write("ok")
                test2.unlink()
                return fallback
            except Exception as e2:
                debug_print("Fallback also not writable:", fallback, e2)
                return primary
    except Exception as e:
        debug_print("choose_data_folder unexpected error:", e)
        return home / ".library_app"


DATA_FOLDER = choose_data_folder()
BOOKS_CSV = DATA_FOLDER / "books.csv"
MEMBERS_CSV = DATA_FOLDER / "members.csv"
LOANS_CSV = DATA_FOLDER / "loans.csv"
LIBRARIANS_JSON = DATA_FOLDER / ".librarians.json"
LIBRARIAN_PASS_FILE = DATA_FOLDER / "librarian_pass.txt"
LOAN_FIELDS = ["book_name","doi_code","receiver_name","receiver_national_id","borrow_date","return_date","librarian","returned"]

debug_print("Using DATA_FOLDER:", DATA_FOLDER)

ADMIN_USERNAME_HASH = "$2b$12$x.RlRtKzPQRx0P2AZD9E8.TGgOo04rdaz9GIPWiJwwlogKnX64iey"
ADMIN_PASSWORD_HASH = "$2b$12$AOlE7zqeUjM6n/kD/NP6LOxp3bH5fpS9qle5Wy/cp4khxIml7JMfe"


def ensure_librarians_json_exists():
    try:
        if not LIBRARIANS_JSON.exists():
            LIBRARIANS_JSON.parent.mkdir(parents=True, exist_ok=True)
            _save_librarians_json_atomic([], fallback_allowed=True)
            hide_file_on_windows(LIBRARIANS_JSON)
    except Exception as e:
        debug_print("ensure_librarians_json_exists:", e)

def load_librarians_json():
    ensure_librarians_json_exists()
    try:
        with LIBRARIANS_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            return data
    except Exception as e:
        debug_print("load_librarians_json failed:", e)
        try:
            _save_librarians_json_atomic([], fallback_allowed=True)
            hide_file_on_windows(LIBRARIANS_JSON)
        except Exception as ee:
            debug_print("failed recreate librarians json:", ee)
        return []

def _save_librarians_json_atomic(data, fallback_allowed=True):
    path = LIBRARIANS_JSON
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
        make_writable(path)
        try:
            hide_file_on_windows(path)
        except Exception:
            pass
        debug_print("Wrote librarians JSON to", path)
    except PermissionError as pe:
        debug_print("PermissionError writing librarians file:", pe)
        if fallback_allowed:
            fallback = Path.home() / ".library_app" / ".librarians.json"
            try:
                fallback.parent.mkdir(parents=True, exist_ok=True)
                tmp2 = fallback.with_suffix(".tmp")
                with tmp2.open("w", encoding="utf-8") as f2:
                    json.dump(data, f2, indent=2, ensure_ascii=False)
                tmp2.replace(fallback)
                make_writable(fallback)
                debug_print("Saved librarians JSON to fallback:", fallback)
                try:
                    QMessageBox.warning(None, "Permission issue", f"Could not write to {path}.\nSaved librarians file to {fallback} instead.")
                except Exception:
                    print(f"Could not write to {path}. Saved to {fallback} instead.")
                return
            except Exception as e2:
                debug_print("Fallback write failed:", e2)
                raise
        else:
            raise
    except Exception as e:
        debug_print("Error saving librarians json:", e)
        raise

def save_librarians_json(data):
    try:
        _save_librarians_json_atomic(data, fallback_allowed=True)
    except Exception as e:
        debug_print("save_librarians_json final failure:", e)
        try:
            QMessageBox.critical(None, "File Error", f"Cannot write librarians file:\n{e}")
        except Exception:
            print("Cannot write librarians file:", e)

def find_librarian_by_username(username_plain):
    libs = load_librarians_json()
    for rec in libs:
        try:
            uh = rec.get("username_hash","")
            if not uh:
                continue
            if bcrypt.checkpw(username_plain.encode('utf-8'), uh.encode('utf-8')):
                return rec
        except Exception:
            continue
    return None

def add_librarian(username_plain, password_plain):
    try:
        libs = load_librarians_json()
        if find_librarian_by_username(username_plain) is not None:
            return False, "Username already exists."
        username_h = bcrypt.hashpw(username_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        password_h = bcrypt.hashpw(password_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        rec = {"username_hash": username_h, "password_hash": password_h, "created": QDate.currentDate().toString("yyyy-MM-dd")}
        libs.append(rec)
        save_librarians_json(libs)
        hide_file_on_windows(LIBRARIANS_JSON)
        return True, "Added."
    except Exception as e:
        debug_print("add_librarian error:", e)
        return False, f"Error: {e}"

def delete_librarian(username_plain):
    libs = load_librarians_json()
    new = []
    removed = 0
    for rec in libs:
        try:
            if bcrypt.checkpw(username_plain.encode('utf-8'), rec.get("username_hash","").encode('utf-8')):
                removed += 1
                continue
        except Exception:
            pass
        new.append(rec)
    if removed > 0:
        save_librarians_json(new)
    return removed

def load_csv(path: Path):
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        debug_print("load_csv failed for", path, ":", e)
        return []

def save_csv(path: Path, data, fields):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
        make_writable(path)
        debug_print("Saved CSV to", path)
    except PermissionError as pe:
        debug_print("PermissionError saving CSV:", pe)
        fallback_dir = Path.home() / ".library_app"
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = fallback_dir / path.name
            with fallback_path.open("w", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(data)
            make_writable(fallback_path)
            try:
                QMessageBox.warning(None, "Permission issue", f"Could not write {path}. Saved to {fallback_path} instead.")
            except Exception:
                print(f"Could not write {path}. Saved to {fallback_path} instead.")
            debug_print("Saved CSV to fallback:", fallback_path)
        except Exception as e2:
            debug_print("Fallback CSV write failed:", e2)
            try:
                QMessageBox.critical(None, "File Error", f"Cannot write CSV {path} or fallback: {e2}")
            except Exception:
                print("Cannot write CSV", path, e2)
    except Exception as e:
        debug_print("save_csv failed for", path, ":", e)
        try:
            QMessageBox.warning(None, "File Error", f"Cannot write CSV {path.name}: {e}")
        except Exception:
            print("Cannot write CSV", path, e)

def ensure_csv_file(path: Path, fields):
    if not path.exists():
        save_csv(path, [], fields)

def find_stacked_widget_ancestor(widget):
    p = widget.parent()
    while p is not None:
        if isinstance(p, QStackedWidget):
            return p
        p = p.parent()
    return None


class IconWidget(QWidget):
    def __init__(self, shape="square", color=QColor(0, 120, 215)):
        super().__init__()
        self.shape = shape
        self.color = color
        self.setFixedSize(56, 56)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.color)
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(self.color)
        rect = self.rect().adjusted(6, 6, -6, -6)
        if self.shape == "square":
            painter.drawRect(rect)
        elif self.shape == "circle":
            painter.drawEllipse(rect)
        elif self.shape == "triangle":
            x0, y0 = rect.left(), rect.top()
            x1, y1 = rect.right(), rect.bottom()
            top_center = QPointF((x0 + x1) / 2.0, y0)
            p1 = QPointF(x0, y1)
            p2 = QPointF(x1, y1)
            polygon = QPolygonF([p1, p2, top_center])
            painter.drawPolygon(polygon)


class LoginWindow(QWidget):
    def __init__(self, go_librarian, go_admin):
        super().__init__()
        self.go_librarian = go_librarian
        self.go_admin = go_admin
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Library Login")
        self.resize(540, 520)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)

        title = QLabel("Library Management System")
        title.setStyleSheet("font-size:18px; font-weight:600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        icon1 = IconWidget("square", QColor(0, 120, 215))
        layout.addWidget(icon1, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_librarian = QPushButton("Librarian Login")
        btn_librarian.setFixedHeight(48)
        btn_librarian.clicked.connect(self.handle_librarian)
        layout.addWidget(btn_librarian, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(6)

        icon2 = IconWidget("circle", QColor(200, 50, 50))
        layout.addWidget(icon2, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_admin = QPushButton("Admin Login")
        btn_admin.setFixedHeight(48)
        btn_admin.clicked.connect(self.handle_admin)
        layout.addWidget(btn_admin, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(8)
        btn_exit = QPushButton("Exit")
        btn_exit.setFixedHeight(48)
        btn_exit.clicked.connect(self.confirm_exit)
        layout.addWidget(btn_exit, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)

    def confirm_exit(self):
        ret = QMessageBox.question(self, "Exit", "Are you sure you want to exit?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            QApplication.instance().quit()

    def handle_librarian(self):
        ensure_librarians_json_exists()
        libs = load_librarians_json()
        if not libs:
            QMessageBox.warning(self, "No usernames", "No usernames exist. Contact admin.")
            return
        username, ok = QInputDialog.getText(self, "Librarian Login", "Username:")
        if not ok or username is None:
            return
        password, ok2 = QInputDialog.getText(self, "Librarian Login", "Password:", QLineEdit.EchoMode.Password)
        if not ok2 or password is None:
            return
        rec = find_librarian_by_username(username)
        if rec is None:
            QMessageBox.warning(self, "Login Failed", "Username or password incorrect.")
            return
        try:
            if bcrypt.checkpw(password.encode('utf-8'), rec.get("password_hash","").encode('utf-8')):
                self.go_librarian()
                return
        except Exception:
            pass
        QMessageBox.warning(self, "Login Failed", "Username or password incorrect.")

    def handle_admin(self):
        username, ok = QInputDialog.getText(self, "Admin Login", "Admin Username:")
        if not ok or username is None:
            return
        password, ok2 = QInputDialog.getText(self, "Admin Login", "Admin Password:", QLineEdit.EchoMode.Password)
        if not ok2 or password is None:
            return
        try:
            user_ok = bcrypt.checkpw(username.encode('utf-8'), ADMIN_USERNAME_HASH.encode('utf-8'))
            pass_ok = bcrypt.checkpw(password.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8'))
        except Exception:
            user_ok = False
            pass_ok = False
        if user_ok and pass_ok:
            self.go_admin()
        else:
            QMessageBox.warning(self, "Login Failed", "Admin credentials incorrect.")


class AddEditBookDialog(QDialog):
    def __init__(self, book=None, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle("Edit Book" if book else "Add Book")
        self.resize(480, 420)
        self.setup_ui()

    def setup_ui(self):
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name = QLineEdit()
        self.subject = QLineEdit()
        self.doi = QLineEdit()
        self.doi.setPlaceholderText("numbers only")
        self.publisher = QLineEdit() 
        self.health = QLineEdit()

        if self.book:
            self.name.setText(self.book.get("name",""))
            self.subject.setText(self.book.get("subject",""))
            self.doi.setText(self.book.get("doi_code",""))
            self.doi.setReadOnly(True)
            self.publisher.setText(self.book.get("publisher",""))
            self.health.setText(self.book.get("health describtion",""))

        form.addRow("Title:", self.name)
        form.addRow("Subject:", self.subject)
        form.addRow("doi Code:", self.doi)
        form.addRow("Publisher:", self.publisher)
        form.addRow("Health Notes:", self.health)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        ok = QPushButton("Save" if self.book else "Add")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.on_ok)
        cancel.clicked.connect(self.reject)
        btn_layout.addWidget(ok)
        btn_layout.addWidget(cancel)
        form.addRow(btn_layout)

    def on_ok(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Error", "Book title is required.")
            return
        if not self.doi.text().strip().isdigit():
            QMessageBox.warning(self, "Error", "doi code must be numeric.")
            return
        self.accept()

    def data(self):
        return {"name": self.name.text().strip(), "subject": self.subject.text().strip(),
                "doi_code": self.doi.text().strip(), "publisher": self.publisher.text().strip(),
                "health_desc": self.health.text().strip()}


class BookDetailDialog(QDialog):
    def __init__(self, book, parent=None, on_delete=None, on_edit=None):
        super().__init__(parent)
        self.book = book
        self.on_delete = on_delete
        self.on_edit = on_edit
        self.updated = False
        self.setWindowTitle("Book Details")
        self.resize(560, 360)
        self.setup_ui()

    def setup_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)
        for k in ("name","subject","doi_code","publisher","health_desc"):
            lbl = QLabel(f"{k}: {self.book.get(k,'')}")
            lbl.setStyleSheet("font-size:13px;")
            v.addWidget(lbl)

        h = QHBoxLayout()
        borrow_btn = QPushButton("Borrow")
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")

        borrow_btn.clicked.connect(self.on_borrow)
        edit_btn.clicked.connect(self.on_edit_clicked)
        delete_btn.clicked.connect(self.on_delete_clicked)
        close_btn.clicked.connect(self.reject)

        h.addWidget(borrow_btn)
        h.addWidget(edit_btn)
        h.addWidget(delete_btn)
        h.addWidget(close_btn)
        v.addLayout(h)

    def on_borrow(self):
        dlg = BorrowDialog(self.book, parent=self)
        if dlg.exec():
            QMessageBox.information(self, "Saved", "Borrow recorded.")

    def on_edit_clicked(self):
        if callable(self.on_edit):
            self.on_edit(self.book)
            self.updated = True
            self.accept()

    def on_delete_clicked(self):
        if callable(self.on_delete):
            ok = QMessageBox.question(self, "Delete", f"Are you sure you want to delete '{self.book.get('name','')}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok == QMessageBox.StandardButton.Yes:
                self.on_delete(self.book)
                self.accept()

class ManageMembersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Members")
        self.resize(560, 440)
        self.setup_ui()

    def setup_ui(self):
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or national ID...")
        self.search.textChanged.connect(self.refresh_list)
        h.addWidget(self.search)
        add_btn = QPushButton("Add Member")
        add_btn.clicked.connect(self.add_member)
        h.addWidget(add_btn)
        v.addLayout(h)

        self.listw = QListWidget()
        v.addWidget(self.listw, stretch=1)

        btn_h = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        edit_btn.clicked.connect(self.edit_member)
        delete_btn.clicked.connect(self.delete_member)
        btn_h.addStretch(1)
        btn_h.addWidget(edit_btn)
        btn_h.addWidget(delete_btn)
        v.addLayout(btn_h)

        ensure_csv_file(MEMBERS_CSV, ["name","national_id","age","join_date","subscription_end","desc"])
        self.members = load_csv(MEMBERS_CSV)
        self.refresh_list()

    def refresh_list(self):
        q = self.search.text().strip().lower()
        self.listw.clear()
        for m in self.members:
            name = m.get("name","")
            nid = m.get("national_id","")
            join = m.get("join_date","")
            if not q or q in name.lower() or q in nid:
                item_text = f"{name} — {nid} — {join}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, m)
                self.listw.addItem(item)

    def add_member(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Member")
        dlg.resize(420, 320)
        form = QFormLayout(dlg)
        name = QLineEdit()
        nid = QLineEdit()
        age = QSpinBox()
        age.setRange(0, 150)
        join = QDateEdit(QDate.currentDate())
        join.setCalendarPopup(True)
        sub_end = QDateEdit(QDate.currentDate())
        sub_end.setCalendarPopup(True)
        desc = QLineEdit()

        form.addRow("Name:", name)
        form.addRow("National ID:", nid)
        form.addRow("Age:", age)
        form.addRow("Join Date:", join)
        form.addRow("Subscription End:", sub_end)
        form.addRow("Notes:", desc)

        btn_h = QHBoxLayout()
        ok = QPushButton("Save")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(lambda: self._add_save(dlg, name, nid, age, join, sub_end, desc))
        cancel.clicked.connect(dlg.reject)
        btn_h.addWidget(ok)
        btn_h.addWidget(cancel)
        form.addRow(btn_h)

        dlg.exec()

    def _add_save(self, dlg, name_w, nid_w, age_w, join_w, subend_w, desc_w):
        n = name_w.text().strip()
        i = nid_w.text().strip()
        if not n or not i:
            QMessageBox.warning(self, "Error", "Name and National ID are required.")
            return
        if any(m.get("national_id","")==i for m in self.members):
            QMessageBox.warning(self, "Error", "National ID already exists.")
            return
        rec = {"name": n, "national_id": i, "age": str(age_w.value()),
               "join_date": join_w.date().toString("yyyy-MM-dd"),
               "subscription_end": subend_w.date().toString("yyyy-MM-dd"),
               "desc": desc_w.text().strip()}
        self.members.append(rec)
        save_csv(MEMBERS_CSV, self.members, ["name","national_id","age","join_date","subscription_end","desc"])
        dlg.accept()
        self.refresh_list()

    def edit_member(self):
        item = self.listw.currentItem()
        if not item:
            QMessageBox.warning(self, "Error", "Select a member first.")
            return
        m = item.data(Qt.ItemDataRole.UserRole)
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Member")
        dlg.resize(420, 360)
        form = QFormLayout(dlg)
        name = QLineEdit(m.get("name",""))
        nid = QLineEdit(m.get("national_id",""))
        nid.setReadOnly(True)
        age = QSpinBox(); age.setRange(0,150)
        try:
            age.setValue(int(m.get("age","0")))
        except:
            age.setValue(0)
        join = QDateEdit(QDate.fromString(m.get("join_date", QDate.currentDate().toString("yyyy-MM-dd")),"yyyy-MM-dd"))
        join.setCalendarPopup(True)
        sub_end = QDateEdit(QDate.fromString(m.get("subscription_end", QDate.currentDate().toString("yyyy-MM-dd")),"yyyy-MM-dd"))
        sub_end.setCalendarPopup(True)
        desc = QLineEdit(m.get("desc",""))

        form.addRow("Name:", name)
        form.addRow("National ID:", nid)
        form.addRow("Age:", age)
        form.addRow("Join Date:", join)
        form.addRow("Subscription End:", sub_end)
        form.addRow("Notes:", desc)

        btn_h = QHBoxLayout()
        save_btn = QPushButton("Save")
        delete_btn = QPushButton("Delete")
        cancel_btn = QPushButton("Cancel")
        btn_h.addStretch(1)
        btn_h.addWidget(save_btn)
        btn_h.addWidget(delete_btn)
        btn_h.addWidget(cancel_btn)
        form.addRow(btn_h)

        save_btn.clicked.connect(lambda: self._save_edit_member(dlg, m, name, age, join, sub_end, desc))
        cancel_btn.clicked.connect(dlg.reject)
        delete_btn.clicked.connect(lambda: self._delete_from_edit(dlg, m))

        dlg.exec()

    def _save_edit_member(self, dlg, m, name_w, age_w, join_w, subend_w, desc_w):
        m["name"] = name_w.text().strip()
        m["age"] = str(age_w.value())
        m["join_date"] = join_w.date().toString("yyyy-MM-dd")
        m["subscription_end"] = subend_w.date().toString("yyyy-MM-dd")
        m["desc"] = desc_w.text().strip()
        save_csv(MEMBERS_CSV, self.members, ["name","national_id","age","join_date","subscription_end","desc"])
        dlg.accept()
        self.refresh_list()

    def delete_member(self):
        item = self.listw.currentItem()
        if not item:
            QMessageBox.warning(self, "Error", "Select a member first.")
            return
        m = item.data(Qt.ItemDataRole.UserRole)
        ok = QMessageBox.question(self, "Delete", f"Are you sure you want to delete '{m.get('name','')}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok == QMessageBox.StandardButton.Yes:
            self.members = [x for x in self.members if x.get("national_id","") != m.get("national_id","")]
            save_csv(MEMBERS_CSV, self.members, ["name","national_id","age","join_date","subscription_end","desc"])
            self.refresh_list()

    def _delete_from_edit(self, dlg, member):
        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        loans = load_csv(LOANS_CSV)
        member_loans = [l for l in loans if l.get("receiver_national_id","") == member.get("national_id","")]
        outstanding = [l for l in member_loans if l.get("returned","").lower() not in ("yes","true")]
        if outstanding:
            cnt = len(outstanding)
            ok = QMessageBox.question(self, "Member has outstanding loans",
                                      f"This member has {cnt} outstanding loan(s). Delete member and all their loan records?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return
            loans = [l for l in loans if l.get("receiver_national_id","") != member.get("national_id","")]
            save_csv(LOANS_CSV, loans, LOAN_FIELDS)
        else:
            ok = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete '{member.get('name','')}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return

        self.members = [x for x in self.members if x.get("national_id","") != member.get("national_id","")]
        save_csv(MEMBERS_CSV, self.members, ["name","national_id","age","join_date","subscription_end","desc"])
        dlg.accept()
        self.refresh_list()
        QMessageBox.information(self, "Deleted", "Member (and related loans, if any) deleted.")


class BorrowDialog(QDialog):
    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle("Borrow Book")
        self.resize(520, 420)
        self.setup_ui()

    def setup_ui(self):
        main = QVBoxLayout(self)
        form = QFormLayout()
        self.librarian = QLineEdit()
        form.addRow("Librarian Name:", self.librarian)
        lbl_book = QLabel(self.book.get("name",""))
        form.addRow("Book:", lbl_book)
        main.addLayout(form)

        search_h = QHBoxLayout()
        self.search_member = QLineEdit()
        self.search_member.setPlaceholderText("Search member by name or national ID...")
        self.search_member.textChanged.connect(self.refresh_members)
        search_h.addWidget(self.search_member)
        main.addLayout(search_h)

        self.member_list = QListWidget()
        main.addWidget(self.member_list, stretch=1)

        date_form = QFormLayout()
        self.borrow_date = QDateEdit(QDate.currentDate()); self.borrow_date.setCalendarPopup(True)
        self.return_date = QDateEdit(QDate.currentDate()); self.return_date.setCalendarPopup(True)
        date_form.addRow("Borrow Date:", self.borrow_date)
        date_form.addRow("Return Date:", self.return_date)
        main.addLayout(date_form)

        btn_h = QHBoxLayout()
        btn_h.addStretch(1)
        ok = QPushButton("Save")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.on_submit)
        cancel.clicked.connect(self.reject)
        btn_h.addWidget(ok)
        btn_h.addWidget(cancel)
        main.addLayout(btn_h)

        ensure_csv_file(MEMBERS_CSV, ["name","national_id","age","join_date","subscription_end","desc"])
        self.members = load_csv(MEMBERS_CSV)
        self.refresh_members()

    def refresh_members(self):
        q = self.search_member.text().strip().lower()
        self.member_list.clear()
        for m in self.members:
            if not q or q in m.get("name","").lower() or q in m.get("national_id",""):
                item = QListWidgetItem(f"{m.get('name','')} — {m.get('national_id','')}")
                item.setData(Qt.ItemDataRole.UserRole, m)
                self.member_list.addItem(item)

    def on_submit(self):
        item = self.member_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Error", "Select a receiver first.")
            return
        mem = item.data(Qt.ItemDataRole.UserRole)
        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        loans = load_csv(LOANS_CSV)
        loans.append({"book_name": self.book.get("name",""),
                      "doi_code": self.book.get("doi_code",""),
                      "receiver_name": mem.get("name",""),
                      "receiver_national_id": mem.get("national_id",""),
                      "borrow_date": self.borrow_date.date().toString("yyyy-MM-dd"),
                      "return_date": self.return_date.date().toString("yyyy-MM-dd"),
                      "librarian": self.librarian.text().strip(),
                      "returned": "No"})
        save_csv(LOANS_CSV, loans, LOAN_FIELDS)
        self.accept()


class ManageLoansDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Loans")
        self.resize(980, 520)
        self.setup_ui()

    def setup_ui(self):
        v = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["Book Title","doi Code","Receiver","National ID","Borrow Date","Return Date","Librarian","Status","Actions"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.table)

        h = QHBoxLayout()
        self.btn_mark_returned = QPushButton("Mark Selected Returned")
        self.btn_delete = QPushButton("Delete Selected Loan")
        self.btn_refresh = QPushButton("Refresh")
        h.addWidget(self.btn_mark_returned)
        h.addWidget(self.btn_delete)
        h.addStretch(1)
        h.addWidget(self.btn_refresh)
        v.addLayout(h)

        self.btn_mark_returned.clicked.connect(self.mark_selected_returned)
        self.btn_delete.clicked.connect(self.delete_selected_loan)
        self.btn_refresh.clicked.connect(self.load_loans)

        self.load_loans()

    def load_loans(self):
        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        loans = load_csv(LOANS_CSV)
        self.table.setRowCount(len(loans))
        for r, l in enumerate(loans):
            self.table.setItem(r,0,QTableWidgetItem(l.get("book_name","")))
            self.table.setItem(r,1,QTableWidgetItem(l.get("doi_code","")))
            self.table.setItem(r,2,QTableWidgetItem(l.get("receiver_name","")))
            self.table.setItem(r,3,QTableWidgetItem(l.get("receiver_national_id","")))
            self.table.setItem(r,4,QTableWidgetItem(l.get("borrow_date","")))
            self.table.setItem(r,5,QTableWidgetItem(l.get("return_date","")))
            self.table.setItem(r,6,QTableWidgetItem(l.get("librarian","")))
            self.table.setItem(r,7,QTableWidgetItem(l.get("returned","")))

            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0,0,0,0)
            btn_toggle = QPushButton("Toggle")
            btn_delete = QPushButton("Delete")
            btn_toggle.setFixedWidth(80)
            btn_delete.setFixedWidth(80)
            layout.addWidget(btn_toggle)
            layout.addWidget(btn_delete)
            btn_toggle.clicked.connect(lambda ch, row=r: self.toggle_returned(row))
            btn_delete.clicked.connect(lambda ch, row=r: self.delete_loan_by_row(row))
            self.table.setCellWidget(r,8,container)

    def toggle_returned(self, row):
        loans = load_csv(LOANS_CSV)
        if 0 <= row < len(loans):
            cur = loans[row].get("returned","No")
            loans[row]["returned"] = "Yes" if cur.lower() not in ("yes","true") else "No"
            save_csv(LOANS_CSV, loans, LOAN_FIELDS)
            self.load_loans()

    def delete_loan_by_row(self, row):
        loans = load_csv(LOANS_CSV)
        if 0 <= row < len(loans):
            item = loans[row]
            ok = QMessageBox.question(self, "Delete Loan", f"Delete loan of '{item.get('book_name','')}' to {item.get('receiver_name','')}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok == QMessageBox.StandardButton.Yes:
                del loans[row]
                save_csv(LOANS_CSV, loans, LOAN_FIELDS)
                self.load_loans()

    def mark_selected_returned(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.warning(self, "Error", "Select at least one row.")
            return
        loans = load_csv(LOANS_CSV)
        rows = [s.row() for s in sel]
        changed = False
        for r in rows:
            if 0 <= r < len(loans):
                if loans[r].get("returned","").lower() not in ("yes","true"):
                    loans[r]["returned"] = "Yes"
                    changed = True
        if changed:
            save_csv(LOANS_CSV, loans, LOAN_FIELDS)
            self.load_loans()
        else:
            QMessageBox.information(self, "Info", "Selected loans were already marked returned.")

    def delete_selected_loan(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.warning(self, "Error", "Select at least one row.")
            return
        loans = load_csv(LOANS_CSV)
        rows = sorted([s.row() for s in sel], reverse=True)
        any_removed = False
        for r in rows:
            if 0 <= r < len(loans):
                item = loans[r]
                ok = QMessageBox.question(self, "Delete Loan", f"Delete loan of '{item.get('book_name','')}' to {item.get('receiver_name','')}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ok == QMessageBox.StandardButton.Yes:
                    del loans[r]
                    any_removed = True
        if any_removed:
            save_csv(LOANS_CSV, loans, LOAN_FIELDS)
            self.load_loans()


class LibrarianWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Librarian Panel")
        self.setContentsMargins(8,8,8,8)
        self.setup_ui()

    def setup_ui(self):
        main = QVBoxLayout()
        main.setSpacing(10)
        self.setLayout(main)

        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        main.addLayout(self.toolbar)

        self.btn_add = QPushButton("Add Book"); self.btn_add.setFixedHeight(36); self.btn_add.clicked.connect(self.add_book)
        self.btn_members = QPushButton("Members"); self.btn_members.setFixedHeight(36); self.btn_members.clicked.connect(self.open_members)
        self.btn_loans = QPushButton("Loans"); self.btn_loans.setFixedHeight(36); self.btn_loans.clicked.connect(self.open_loans)
        self.btn_delete = QPushButton("Delete Book"); self.btn_delete.setFixedHeight(36); self.btn_delete.clicked.connect(self.delete_selected_book)
        self.btn_addloan = QPushButton("Add Loan"); self.btn_addloan.setFixedHeight(36); self.btn_addloan.clicked.connect(self.add_loan)
        btn_back = QPushButton("Back to Menu"); btn_back.setFixedHeight(36); btn_back.clicked.connect(lambda: (find_stacked_widget_ancestor(self) and find_stacked_widget_ancestor(self).setCurrentIndex(0)))

        self.toolbar.addWidget(self.btn_add)
        self.toolbar.addWidget(self.btn_members)
        self.toolbar.addWidget(self.btn_addloan)
        self.toolbar.addWidget(self.btn_loans)
        self.toolbar.addWidget(self.btn_delete)
        self.toolbar.addWidget(btn_back)
        self.toolbar.addStretch(1)

        search_h = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by title or doi code...")
        self.search_input.textChanged.connect(self.refresh_table)
        search_h.addWidget(self.search_input)
        main.addLayout(search_h)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Title","Subject","doi Code","Publisher","Health Notes"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.cellDoubleClicked.connect(self.open_detail_by_row)
        main.addWidget(self.table, stretch=1)

        ensure_csv_file(BOOKS_CSV, ["name","subject","doi_code","publisher","health_desc"])
        self.books = load_csv(BOOKS_CSV)
        self.refresh_table()

    def add_book(self):
        dlg = AddEditBookDialog(parent=self)
        if dlg.exec():
            b = dlg.data()
            if any(x.get("doi_code","")==b["doi_code"] for x in self.books):
                QMessageBox.warning(self, "Error", "Duplicate doi code.")
                return
            self.books.append(b)
            save_csv(BOOKS_CSV, self.books, ["name","subject","doi_code","publisher","health_desc"])
            self.refresh_table()

    def add_loan(self):
        sel = self.table.selectionModel().selectedRows()
        book = None
        if sel:
            row = sel[0].row()
            txt = self.search_input.text().strip().lower()
            visible = []
            if txt:
                for b in self.books:
                    if txt in b.get("name","").lower() or txt in b.get("doi_code",""):
                        visible.append(b)
            else:
                visible = self.books
            if 0 <= row < len(visible):
                book = visible[row]

        if book is None:
            items = [b.get("name","") + (f" — {b.get('doi_code','')}" if b.get('doi_code') else "") for b in self.books]
            if not items:
                QMessageBox.warning(self, "No Books", "There are no books in the system to lend.")
                return
            item, ok = QInputDialog.getItem(self, "Select Book", "Book:", items, 0, False)
            if not ok or not item:
                return
            name_part = item.split(" — ")[0].strip()
            for b in self.books:
                if b.get("name","") == name_part:
                    book = b
                    break
            if book is None:
                QMessageBox.warning(self, "Error", "Selected book not found.")
                return

        dlg = BorrowDialog(book, parent=self)
        if dlg.exec():
            QMessageBox.information(self, "Saved", "Borrow recorded.")

    def open_members(self):
        dlg = ManageMembersDialog(self)
        dlg.exec()

    def open_loans(self):
        dlg = ManageLoansDialog(self)
        dlg.exec()

    def refresh_table(self):
        txt = self.search_input.text().strip().lower()
        rows = []
        if txt:
            for b in self.books:
                if txt in b.get("name","").lower() or txt in b.get("doi_code",""):
                    rows.append(b)
        else:
            rows = self.books
        self.table.setRowCount(len(rows))
        for r, book in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(book.get("name","")))
            self.table.setItem(r, 1, QTableWidgetItem(book.get("subject","")))
            self.table.setItem(r, 2, QTableWidgetItem(book.get("doi_code","")))
            self.table.setItem(r, 3, QTableWidgetItem(book.get("publisher","")))
            self.table.setItem(r, 4, QTableWidgetItem(book.get("health_desc","")))

    def _find_book_by_doi(self, doi):
        for i, b in enumerate(self.books):
            if b.get("doi_code","") == doi:
                return i, b
        return None, None

    def open_detail_by_row(self, row, col):
        txt = self.search_input.text().strip().lower()
        visible = []
        if txt:
            for b in self.books:
                if txt in b.get("name","").lower() or txt in b.get("doi_code",""):
                    visible.append(b)
        else:
            visible = self.books
        if 0 <= row < len(visible):
            book = visible[row]
            dlg = BookDetailDialog(book, parent=self, on_delete=self._on_delete_book, on_edit=self._on_edit_book)
            dlg.exec()
            self.books = load_csv(BOOKS_CSV)
            self.refresh_table()

    def _on_edit_book(self, book):
        dlg = AddEditBookDialog(book=book, parent=self)
        if dlg.exec():
            new = dlg.data()
            idx, _ = self._find_book_by_doi(book.get("doi_code",""))
            if idx is not None:
                self.books[idx] = new
                save_csv(BOOKS_CSV, self.books, ["name","subject","doi_code","publisher","health_desc"])
                QMessageBox.information(self, "Success", "Edit saved.")

    def _on_delete_book(self, book):
        doi = book.get("doi_code","")
        self.books = [b for b in self.books if b.get("doi_code","") != doi]
        save_csv(BOOKS_CSV, self.books, ["name","subject","doi_code","publisher","health_desc"])

        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        loans = load_csv(LOANS_CSV)
        before_count = len(loans)
        loans = [l for l in loans if l.get("doi_code","") != doi]
        removed_count = before_count - len(loans)
        save_csv(LOANS_CSV, loans, LOAN_FIELDS)

        if removed_count > 0:
            QMessageBox.information(self, "Success", f"Book deleted and {removed_count} related loan(s) were removed.")
        else:
            QMessageBox.information(self, "Success", "Book deleted. No related loans found.")

    def delete_selected_book(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.warning(self, "Error", "Select a row first.")
            return
        row = sel[0].row()
        txt = self.search_input.text().strip().lower()
        visible = []
        if txt:
            for b in self.books:
                if txt in b.get("name","").lower() or txt in b.get("doi_code",""):
                    visible.append(b)
        else:
            visible = self.books
        if 0 <= row < len(visible):
            book = visible[row]
            ok = QMessageBox.question(self, "Delete", f"Are you sure you want to delete '{book.get('name')}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok == QMessageBox.StandardButton.Yes:
                self._on_delete_book(book)
                self.refresh_table()


class AdminWindow(LibrarianWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Admin Panel")
        self.add_admin_buttons()

    def add_admin_buttons(self):
        change_btn = QPushButton("Change Librarian Password"); change_btn.clicked.connect(self.change_librarian_pass)
        backup_btn = QPushButton("Backup (CSV)"); backup_btn.clicked.connect(self.backup_books)
        import_btn = QPushButton("Import CSV"); import_btn.clicked.connect(self.import_books)
        add_user_btn = QPushButton("Add Librarian Username"); add_user_btn.clicked.connect(self.add_librarian_ui)
        del_user_btn = QPushButton("Delete Librarian Username"); del_user_btn.clicked.connect(self.delete_librarian_ui)
        reset_btn = QPushButton("Reset App (keep librarians)"); reset_btn.clicked.connect(self.reset_app_confirm)

        self.toolbar.insertWidget(0, import_btn)
        self.toolbar.insertWidget(0, backup_btn)
        self.toolbar.insertWidget(0, change_btn)
        self.toolbar.insertWidget(0, add_user_btn)
        self.toolbar.insertWidget(0, del_user_btn)
        self.toolbar.insertWidget(0, reset_btn)

    def change_librarian_pass(self):
        text, ok = QInputDialog.getText(self, "Change Librarian Password", "Enter new password:", QLineEdit.EchoMode.Password)
        if ok and text.strip():
            try:
                LIBRARIAN_PASS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(LIBRARIAN_PASS_FILE, "w", encoding="utf-8") as f:
                    f.write(text.strip())
                make_writable(LIBRARIAN_PASS_FILE)
                QMessageBox.information(self, "Success", "Password changed.")
            except Exception as e:
                debug_print("change_librarian_pass error:", e)
                QMessageBox.warning(self, "Error", f"Could not save password file: {e}")

    def backup_books(self):
        folder = QFileDialog.getExistingDirectory(self, "Select backup folder")
        if folder:
            try:
                target = Path(folder) / BOOKS_CSV.name
                shutil.copy(BOOKS_CSV, target)
                QMessageBox.information(self, "Success", f"Books CSV copied to {target}")
            except Exception as e:
                debug_print("backup_books error:", e)
                QMessageBox.warning(self, "Error", str(e))

    def import_books(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select books CSV", filter="CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    imported = list(reader)
                if imported and all(k in imported[0] for k in ("name","subject","doi_code","publisher","health_desc")):
                    existing = {b.get("doi_code","") for b in self.books}
                    new = [b for b in imported if b.get("doi_code","") not in existing]
                    self.books.extend(new)
                    save_csv(BOOKS_CSV, self.books, ["name","subject","doi_code","publisher","health_desc"])
                    self.refresh_table()
                    QMessageBox.information(self, "Success", f"{len(new)} new book(s) imported.")
                else:
                    QMessageBox.warning(self, "Error", "CSV format is not valid.")
            except Exception as e:
                debug_print("import_books error:", e)
                QMessageBox.warning(self, "Error", str(e))

    def add_librarian_ui(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Librarian Username")
        dlg.resize(420, 220)
        form = QFormLayout(dlg)
        username = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username:", username)
        form.addRow("Password:", password)
        ok = QPushButton("Add")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(lambda: self._add_librarian_from_ui(dlg, username, password))
        cancel.clicked.connect(dlg.reject)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(ok)
        h.addWidget(cancel)
        form.addRow(h)
        dlg.exec()

    def _add_librarian_from_ui(self, dlg, username_w, password_w):
        u = username_w.text().strip()
        p = password_w.text().strip()
        if not u or not p:
            QMessageBox.warning(self, "Error", "Username and password required.")
            return
        ok, msg = add_librarian(u, p)
        if not ok:
            QMessageBox.warning(self, "Error", msg)
            return
        QMessageBox.information(self, "Added", "Librarian username added.")
        dlg.accept()

    def delete_librarian_ui(self):
        username, ok = QInputDialog.getText(self, "Delete Librarian", "Enter username to delete:")
        if not ok or not username:
            return
        removed = delete_librarian(username)
        if removed > 0:
            QMessageBox.information(self, "Deleted", f"Removed {removed} librarian(s).")
        else:
            QMessageBox.information(self, "Not found", "Username not found.")

    def reset_app_confirm(self):
        ok = QMessageBox.question(self, "Reset App", "This will delete all app data (books, members, loans). Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return
        pwd, ok2 = QInputDialog.getText(self, "Confirm Reset", "Enter admin password to confirm:", QLineEdit.EchoMode.Password)
        if not ok2:
            return
        try:
            if bcrypt.checkpw(pwd.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8')):
                self.perform_reset_app()
                QMessageBox.information(self, "Reset", "Application data reset. Librarians preserved.")
            else:
                QMessageBox.warning(self, "Failed", "Admin password incorrect. Reset aborted.")
        except Exception as e:
            debug_print("reset_app_confirm bcrypt error:", e)
            QMessageBox.warning(self, "Failed", "Error validating admin password. Reset aborted.")

    def perform_reset_app(self):
        for p in (BOOKS_CSV, MEMBERS_CSV, LOANS_CSV, LIBRARIAN_PASS_FILE):
            try:
                if p.exists():
                    p.unlink()
            except Exception as e:
                debug_print("perform_reset_app unlink failed for", p, ":", e ,"           if you belive it's wrong contact admin!!!")
        ensure_csv_file(BOOKS_CSV, ["name","subject","doi_code","publisher","health_desc"])
        ensure_csv_file(MEMBERS_CSV, ["name","national_id","age","join_date","subscription_end","desc"])
        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        ensure_librarians_json_exists()


class MainApp(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Library Management System")
        self.resize(900, 640)

        self.page_login = LoginWindow(self.show_librarian, self.show_admin)
        self.page_librarian = LibrarianWindow()
        self.page_admin = AdminWindow()

        self.addWidget(self.page_login)      
        self.addWidget(self.page_librarian)  
        self.addWidget(self.page_admin)      
        self.setCurrentIndex(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_scaling()

    def update_scaling(self):
        try:
            app = QApplication.instance()
            screen = app.primaryScreen().availableGeometry()
            screen_w = max(300, screen.width())
            screen_h = max(200, screen.height())
        except Exception:
            screen_w = max(300, self.width())
            screen_h = max(200, self.height())

        w = max(400, min(self.width(), screen_w))
        h = max(300, min(self.height(), screen_h))
        scale = min(w / 900.0, h / 640.0)
        base_font_px = max(10, int(12 * scale))
        button_padding = max(6, int(6 * scale))

        app = QApplication.instance()
        style = f"""
            QWidget {{ color: #111; background: #ffffff; font-family: "Tahoma", "Segoe UI", sans-serif; font-size: {base_font_px}px; }}
            QPushButton {{ background: #1976d2; color: white; border-radius: 6px; padding: {button_padding}px {button_padding*2}px; }}
            QPushButton:disabled {{ background: #bbb; color: #555; }}
            QLineEdit {{ padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-size: {base_font_px}px; }}
            QTableWidget {{ gridline-color: #ddd; font-size: {base_font_px}px; }}
        """
        try:
            app.setStyleSheet(style)
        except Exception:
            pass

        try:
            lw = self.page_librarian.table
            if lw:
                total = max(200, self.width() - 200)
                lw.setColumnWidth(0, int(total * 0.30))
                lw.setColumnWidth(1, int(total * 0.20))
                lw.setColumnWidth(2, int(total * 0.15))
                lw.setColumnWidth(3, int(total * 0.20))
                lw.setColumnWidth(4, int(total * 0.15))
                lw.verticalHeader().setDefaultSectionSize(max(20, int(24 * scale)))
        except Exception:
            pass

    def show_login(self):
        self.setCurrentIndex(0)

    def show_librarian(self):
        self.page_librarian.books = load_csv(BOOKS_CSV)
        self.page_librarian.refresh_table()
        self.setCurrentIndex(1)

    def show_admin(self):
        self.page_admin.books = load_csv(BOOKS_CSV)
        self.page_admin.refresh_table()
        self.setCurrentIndex(2)


if __name__ == "__main__":
    try:
        ensure_csv_file(BOOKS_CSV, ["name","subject","doi_code","publisher","health_desc"])
        ensure_csv_file(MEMBERS_CSV, ["name","national_id","age","join_date","subscription_end","desc"])
        ensure_csv_file(LOANS_CSV, LOAN_FIELDS)
        ensure_librarians_json_exists()

        app = QApplication(sys.argv)

        main = MainApp()
        try:
            screen = app.primaryScreen().availableGeometry()
            sw, sh = screen.width(), screen.height()
            desired_w = min(int(sw * 0.9), max(900, int(sw * 0.8)))
            desired_h = min(int(sh * 0.9), max(640, int(sh * 0.8)))
            main.resize(desired_w, desired_h)
            main.move(int((sw - desired_w) / 2), int((sh - desired_h) / 2))
        except Exception:
            pass

        main.show()
        main.update_scaling()
        sys.exit(app.exec())
    except Exception as e:
        print("Unhandled exception starting app:", e)
        traceback.print_exc()
        try:
            QMessageBox.critical(None, "Fatal Error", f"Application failed to start:\n{e}")
        except Exception:
            pass
