APP_STYLESHEET = """
QMainWindow, QWidget { background: #f6f7fb; color: #182230; font-size: 14px; }
QFrame#Sidebar { background: #1e1b4b; border: none; }
QLabel#Brand { background: transparent; color: #ffffff; font-size: 22px; font-weight: 700; padding: 20px 14px; }
QLabel#SidebarFooter { background: transparent; color: #c7d2fe; padding: 8px 12px; }
QFrame#Sidebar QPushButton#NavButton { background: transparent; color: #e0e7ff; text-align: left; border: none; border-radius: 8px; padding: 11px 14px; }
QFrame#Sidebar QPushButton#NavButton:hover { background: #312e81; color: #ffffff; }
QFrame#Sidebar QPushButton#NavButton:checked { background: #4f46e5; color: #ffffff; font-weight: 600; }
QFrame#Card { background: white; border: 1px solid #e4e8ef; border-radius: 12px; }
QWidget#AssistantPanel { background: white; border-left: 1px solid #d7dce5; }
QLabel#PageTitle { font-size: 25px; font-weight: 700; color: #111827; }
QLabel#Metric { font-size: 28px; font-weight: 700; color: #2563eb; }
QLabel#Word { font-size: 38px; font-weight: 700; color: #111827; }
QLabel#Phonetic { color: #64748b; font-size: 17px; }
QPushButton#PrimaryButton { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 10px 18px; font-weight: 600; }
QPushButton#PrimaryButton:hover { background: #1d4ed8; }
QPushButton#SecondaryButton { background: white; color: #334155; border: 1px solid #cbd5e1; border-radius: 8px; padding: 9px 14px; }
QPushButton#SecondaryButton:hover { background: #eef2ff; color: #312e81; border-color: #818cf8; }
QPushButton#LinkButton { background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; border-radius: 7px; padding: 6px 10px; }
QPushButton#LinkButton:hover { background: #e0e7ff; border-color: #818cf8; }
QPushButton#AdvancedRetryButton { background: #eef2ff; color: #4338ca; border: 1px solid #c7d2fe; border-radius: 8px; padding: 8px 14px; font-weight: 600; }
QPushButton#AdvancedRetryButton:hover { background: #e0e7ff; border-color: #818cf8; }
QPushButton#RatingButton { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px 14px; }
QPushButton#RatingButton:hover { border-color: #2563eb; color: #2563eb; }
QPushButton#FavoriteButton { background: #fff7ed; color: #9a3412; border: 1px solid #fed7aa; border-radius: 8px; padding: 7px 14px; }
QPushButton#FavoriteButton:hover { background: #ffedd5; border-color: #fb923c; }
QPushButton#MasteredButton { background: #ecfdf5; color: #166534; border: 1px solid #86efac; border-radius: 8px; padding: 7px 14px; }
QPushButton#MasteredButton:hover { background: #dcfce7; border-color: #22c55e; }
QFrame#LearningAids { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; }
QScrollArea#LearningAidsScroll, QWidget#LearningAidsContent { background: transparent; border: none; }
QLabel#LearningAidTitle { color: #334155; font-weight: 700; }
QLabel#LearningAidStatus { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; border-radius: 7px; padding: 3px 7px; font-size: 12px; }
QPushButton#LearningAidReportButton { background: transparent; color: #475569; border: 1px solid #cbd5e1; border-radius: 7px; padding: 5px 10px; }
QPushButton#LearningAidReportButton:hover { background: #f1f5f9; color: #1e293b; }
QDialog#WordDetailDialog { background: #f8fafc; }
QFrame#WordDetailComparison { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 9px; }
QLabel#WordDetailComparisonTitle { color: #4338ca; font-size: 12px; font-weight: 700; }
QLabel#WordDetailComparisonWord { color: #1e1b4b; font-size: 17px; font-weight: 700; }
QLabel#WordDetailWord { font-size: 30px; font-weight: 700; color: #111827; }
QLabel#WordDetailPhonetic { color: #64748b; font-size: 16px; }
QLabel#WordDetailMeaning { color: #1e293b; font-size: 18px; font-weight: 600; }
QLabel#WordDetailLevel { color: #64748b; }
QLabel#WordDetailStatus { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; border-radius: 7px; padding: 5px 8px; }
QLabel#WordDetailSectionTitle { color: #334155; font-weight: 700; padding-top: 5px; }
QLabel#WordDetailText { color: #475569; line-height: 1.4; }
QLabel#WordDetailLoading { color: #64748b; padding: 20px; }
QPushButton#WordDetailBackButton, QPushButton#WordDetailCloseButton { background: white; color: #334155; border: 1px solid #cbd5e1; border-radius: 7px; padding: 6px 12px; }
QPushButton#WordDetailBackButton:hover, QPushButton#WordDetailCloseButton:hover { background: #eef2ff; color: #312e81; border-color: #818cf8; }
QScrollArea#WordDetailScroll { background: white; border: 1px solid #e2e8f0; border-radius: 9px; }
QListWidget#WordbookList { background: white; border: 1px solid #d7dce5; border-radius: 10px; padding: 6px; }
QListWidget#WordbookList::item { color: #1e293b; border-bottom: 1px solid #eef2f7; padding: 11px 10px; }
QListWidget#WordbookList::item:selected { background: #eef2ff; color: #312e81; }
QListWidget#MasteredList { background: white; border: 1px solid #d7dce5; border-radius: 10px; padding: 6px; }
QListWidget#MasteredList::item { color: #1e293b; border-bottom: 1px solid #eef2f7; padding: 11px 10px; }
QListWidget#MasteredList::item:selected { background: #ecfdf5; color: #166534; }
QListWidget#VocabularyList { background: white; border: 1px solid #d7dce5; border-radius: 10px; padding: 6px; }
QListWidget#VocabularyList::item { color: #1e293b; border-bottom: 1px solid #eef2f7; padding: 11px 10px; }
QListWidget#VocabularyList::item:selected { background: #eef2ff; color: #312e81; }
QPushButton#ChoiceButton { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 12px; text-align: left; }
QPushButton#ChoiceButton:hover { border-color: #2563eb; background: #eff6ff; }
QLineEdit, QTextEdit { background: white; border: 1px solid #d7dce5; border-radius: 8px; padding: 9px; }
"""
