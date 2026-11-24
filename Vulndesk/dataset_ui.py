from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class TweetRecordTableModel(QAbstractTableModel):
    HEADERS = ["Tweet", "Topic", "Uploaded", "File"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = list(rows or [])

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("tweet_text") or ""
            if col == 1:
                return row.get("topic_text") or ""
            if col == 2:
                dt = row.get("uploaded_at")
                return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
            if col == 3:
                return row.get("file_name") or ""

        if role == Qt.FontRole and col == 1:
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.TextAlignmentRole and col == 2:
            return Qt.AlignCenter

        return None

    def get_row(self, row_index: int):
        return self._rows[row_index]


class TopicRecordTableModel(QAbstractTableModel):
    HEADERS = ["Topic", "Uploaded", "File"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = list(rows or [])

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("topic_text") or ""
            if col == 1:
                dt = row.get("uploaded_at")
                return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
            if col == 2:
                return row.get("file_name") or ""

        if role == Qt.FontRole and col == 0:
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.TextAlignmentRole and col == 1:
            return Qt.AlignCenter

        return None

    def get_row(self, row_index: int):
        return self._rows[row_index]


class DatasetPage(QWidget):
    def __init__(self):
        super().__init__()

        root = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tweet text or topic...")
        self.search_input.setMinimumWidth(260)

        self.topic_combo = QComboBox()
        self.topic_combo.addItem("ALL")
        self.topic_combo.setMinimumWidth(220)

        self.upload_date_combo = QComboBox()
        self.upload_date_combo.addItem("ALL")
        self.upload_date_combo.setMinimumWidth(180)
        self.upload_date_combo.setMinimumContentsLength(12)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["50", "100", "250", "500"])
        self.page_size_combo.setCurrentText("100")
        self.page_size_combo.setMinimumWidth(90)

        self.apply_button = QPushButton("Apply")
        self.reset_button = QPushButton("Reset")
        self.refresh_button = QPushButton("Refresh")

        filter_row.addWidget(QLabel("Search"))
        filter_row.addWidget(self.search_input, 2)
        filter_row.addWidget(QLabel("Topic"))
        filter_row.addWidget(self.topic_combo, 1)
        filter_row.addWidget(QLabel("Tanggal Upload Twitter"))
        filter_row.addWidget(self.upload_date_combo)
        filter_row.addWidget(QLabel("Page"))
        filter_row.addWidget(self.page_size_combo)
        filter_row.addWidget(self.apply_button)
        filter_row.addWidget(self.reset_button)
        filter_row.addWidget(self.refresh_button)
        filter_row.addStretch()

        action_row = QHBoxLayout()
        self.upload_tweets_button = QPushButton("Upload tweet_topics.csv")
        self.upload_topics_button = QPushButton("Upload topics_master.csv")
        self.delete_tweets_button = QPushButton("Delete tweet_topics")
        self.delete_topics_button = QPushButton("Delete topics_master")
        self.delete_tweets_button.setMinimumWidth(170)
        self.delete_topics_button.setMinimumWidth(170)
        self.upload_tweets_button.setMinimumWidth(180)
        self.upload_topics_button.setMinimumWidth(180)

        action_row.addStretch()
        action_row.addWidget(self.delete_topics_button)
        action_row.addWidget(self.delete_tweets_button)
        action_row.addWidget(self.upload_topics_button)
        action_row.addWidget(self.upload_tweets_button)

        self.summary_label = QLabel("Uploads: 0 | Tweets: 0 | Topics: 0")
        self.summary_label.setStyleSheet("font-weight: 600;")

        self.tweet_table = QTableView()
        self.tweet_model = TweetRecordTableModel()
        self.tweet_table.setModel(self.tweet_model)

        self.topics_table = QTableView()
        self.topics_model = TopicRecordTableModel()
        self.topics_table.setModel(self.topics_model)

        for table in (self.tweet_table, self.topics_table):
            table.setSelectionBehavior(QTableView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setAlternatingRowColors(True)
            table.setSortingEnabled(False)
            table.setWordWrap(False)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setTextElideMode(Qt.ElideRight)

        tweet_header = self.tweet_table.horizontalHeader()
        tweet_header.setSectionResizeMode(QHeaderView.Interactive)
        tweet_header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.tweet_table.setColumnWidth(1, 220)
        self.tweet_table.setColumnWidth(2, 170)
        self.tweet_table.setColumnWidth(3, 220)

        topic_header = self.topics_table.horizontalHeader()
        topic_header.setSectionResizeMode(QHeaderView.Interactive)
        topic_header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.topics_table.setColumnWidth(1, 170)
        self.topics_table.setColumnWidth(2, 220)

        self.tweet_detail = QTextEdit()
        self.tweet_detail.setReadOnly(True)
        self.tweet_detail.setMinimumHeight(120)
        self.tweet_detail.setPlaceholderText("Select a tweet row to see full text and topic details.")

        tweet_widget = QWidget()
        tweet_layout = QVBoxLayout(tweet_widget)
        tweet_layout.addWidget(QLabel("Tweets"))
        tweet_layout.addWidget(self.tweet_table, 1)

        tweet_pagination = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.page_label = QLabel("Page 1 / 1")
        self.total_label = QLabel("0 tweets")
        tweet_pagination.addWidget(self.prev_button)
        tweet_pagination.addWidget(self.next_button)
        tweet_pagination.addWidget(self.page_label)
        tweet_pagination.addStretch()
        tweet_pagination.addWidget(self.total_label)
        tweet_layout.addLayout(tweet_pagination)
        tweet_layout.addWidget(self.tweet_detail)

        topic_widget = QWidget()
        topic_layout = QVBoxLayout(topic_widget)
        topic_layout.addWidget(QLabel("Topics master"))
        topic_layout.addWidget(self.topics_table, 1)
        self.topics_total_label = QLabel("0 topics")
        topic_layout.addWidget(self.topics_total_label)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(tweet_widget)
        splitter.addWidget(topic_widget)
        splitter.setSizes([620, 260])

        root.addLayout(filter_row)
        root.addLayout(action_row)
        root.addWidget(self.summary_label)
        root.addWidget(splitter, 1)
