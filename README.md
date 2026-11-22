# AttendanceSystem-v2

מערכת נוכחות מקומית למפגשים, קורסים וקבוצות. גרסת בסיס (MVP) ללא שרת, ענן, הרשמה או ספריות חיצוניות. הרישום נשמר בקובץ SQLite במחשב שבו מריצים את הכלי.

## שימוש ראשוני

דרוש Python 3.10 ומעלה. כל הפקודות מבוצעות מתיקיית הפרויקט:

```bash
python3 attendance.py init
python3 attendance.py add-person --id student-001 --name "ישראל ישראלי"
python3 attendance.py add-person --id student-002 --name "דוגמה שנייה"
python3 attendance.py add-session --id lesson-01 --date 2026-11-22 --title "מפגש פתיחה"
python3 attendance.py mark --session lesson-01 --person student-001 --status present
python3 attendance.py mark --session lesson-01 --person student-002 --status excused --note "דיווח מראש"
python3 attendance.py report --session lesson-01
python3 attendance.py export --session lesson-01 --output attendance-report.csv
```

סטטוס תקין הוא `present`, `late`, `absent` או `excused`. משתתף שלא סומן יופיע כ-`unmarked` ולא ייחשב אוטומטית כנעדר. הפקודה `mark` מאפשרת לתקן סטטוס קיים. הפקודות `people` ו-`sessions` מציגות רשומות קיימות. תאריך מוגדר בפורמט ISO: `YYYY-MM-DD`.

כברירת מחדל מסד הנתונים נוצר בתור `attendance.sqlite3` בתיקייה הנוכחית. ניתן לבחור נתיב נפרד לפני שם הפעולה:

```bash
python3 attendance.py --db ./private/attendance.sqlite3 init
python3 attendance.py --db ./private/attendance.sqlite3 people
```

התיקייה `private` חייבת להתקיים מראש; אפשר גם להגדיר `ATTENDANCE_DB` במשתנה סביבה. קובץ המסד מקבל הרשאות `0600` במערכות POSIX. הגנה זו אינה תחליף להצפנת דיסק, גיבוי או הרשאות משתמש במערכת ההפעלה.

## התנהגות וייצוא

- מזהי משתתפים ומפגשים ייחודיים. אי אפשר לסמן משתתף או מפגש שאינו קיים.
- כל צמד משתתף–מפגש נשמר פעם אחת; סימון חוזר מעדכן אותו.
- סיכום מפגש כולל כל המשתתפים והסטטוס שלהם, גם אם טרם סומנו.
- הייצוא הוא CSV בקידוד UTF-8 עם BOM לתאימות עם Excel, כולל מזהה מפגש, תאריך, כותרת, מזהה משתתף, שם, סטטוס והערה.
- קובץ CSV קיים אינו מוחלף בלי `--overwrite`. הייצוא נכתב לקובץ זמני פרטי ואז מוחלף רק לאחר סיום הכתיבה.
- כשל בפקודה מחזיר exit code 1 ומדפיס הודעה ל-stderr; שגיאת שימוש בארגומנטים מחזירה 2.

## פרטיות ומגבלות

המאגר מכיל שמות והערות שעשויים להיות מידע אישי. **אין להעלות את קובץ ה-SQLite, קובצי WAL/SHM או דוחות ה-CSV ל-GitHub**. ה-`.gitignore` מסנן את הקבצים הנפוצים, אך יש לבדוק לפני `git add`. אין שרת אינטרנט, משתמשים, הרשאות תפקידים, הזדהות או סנכרון בין מחשבים. השימוש מיועד למפעיל מקומי יחיד, לא לרישום נוכחות רב-משתמשי בו-זמנית.

המימוש נמצא בענף פיתוח וממתין לבדיקות קבלה מרוכזות ולמיזוג על ידי בעל המאגר.
