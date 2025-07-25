import sqlite3
import pathlib
import gspread
from datetime import datetime, timedelta
from collections import defaultdict
from google.oauth2.service_account import Credentials
import json
import requests
from pathlib import Path
from configs import DB_FILE
from google.auth.transport.requests import Request

DB_FILE = DB_FILE  # ✅ просто в корне проекта
SERVICE_ACCOUNT_FILE = Path("credentials.json")
SPREADSHEET_NAME = "UserData"
SHEET_NAME = "отчет по товарам"

SPREADSHEET_ID = "1Xl_LaWjwBBDPldkmoK-WfVfXNYmQe_ExxURV05QLJuw"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid=0"

STATUS_MAP = {
    "confirmed": "Подтвержден",
    "pending_payment": "В ожидании оплаты",
    "rejected": "Отклонен", 
    "preparing": "В обработке",
    "shipped": "Отправлен",
    "delivered": "Доставлен",
    "cancelled_by_client": "Отменен клиентом",
    None: "Неизвестен"
}

def fetch_products_detailed():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT p.id, p.name, p.category_id, p.sub_category_id, b.name as brand_name
        FROM products p
        LEFT JOIN brands b ON p.brand_id = b.id
        ORDER BY p.id
    """)
    products = c.fetchall()

    c.execute("""
        SELECT pv.product_id, pv.size_id, pv.color_id, pv.quantity,
               s.name as size_name, co.name as color_name, pv.price
        FROM product_variants pv
        LEFT JOIN sizes s ON pv.size_id = s.id
        LEFT JOIN colors co ON pv.color_id = co.id
    """)
    variants = c.fetchall()
    conn.close()

    colors_dict = defaultdict(set)
    sizes_dict = defaultdict(set)
    total_quantity = defaultdict(int)
    pairs_quantity = defaultdict(lambda: defaultdict(int))
    pairs_price = defaultdict(dict)

    for product_id, size_id, color_id, qty, size_name, color_name, price in variants:
        colors_dict[product_id].add(color_name)
        sizes_dict[product_id].add(size_name)
        total_quantity[product_id] += qty
        pairs_quantity[product_id][(size_name, color_name)] += qty
        pairs_price[product_id][(size_name, color_name)] = price

    data = [
        ["id", "Название", "id категории", "id подкатегории", "Бренд", "Цвета", "Размеры", "Кол-ва (размер/цвет/цена)", "Общее кол-во"]
    ]
    for p in products:
        pid, name, cat_id, subcat_id, brand = p
        colors = ", ".join(sorted(filter(None, colors_dict[pid])))
        sizes = ", ".join(sorted(filter(None, sizes_dict[pid])))
        scq = "; ".join(
            f"{size}/{color}: {qty}шт ({pairs_price[pid][(size, color)]}₸)"
            for (size, color), qty in pairs_quantity[pid].items()
        )
        total = total_quantity[pid]
        data.append([pid, name, cat_id, subcat_id, brand, colors, sizes, scq, total])
    return data


def export_to_gsheet(data):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=[
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ])
    client = gspread.authorize(creds)

    # Открываем или создаём таблицу
    try:
        spreadsheet = client.open(SPREADSHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        spreadsheet = client.create(SPREADSHEET_NAME)
        spreadsheet.share(creds.service_account_email, perm_type='user', role='writer')
        spreadsheet.share(None, perm_type='anyone', role='reader')  # разрешает всем доступ


    # Получаем или создаём нужный лист
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows="200", cols="20")

    worksheet.clear()
    worksheet.append_rows(data)

    # Получаем sheetId для batch_update
    sheet_id = worksheet._properties['sheetId']

    # Установить ширину первых 8 столбцов (можно поправить endIndex)
    spreadsheet.batch_update({
        "requests": [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 8
                    },
                    "properties": {
                        "pixelSize": 220
                    },
                    "fields": "pixelSize"
                }
            }
        ]
    })

    # Включить перенос текста для всех ячеек
    spreadsheet.batch_update({
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP"
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy"
                }
            }
        ]
    })

    print("✅ Размеры столбцов выставлены, перенос текста включён!")




def get_gsheet_url():
    return GOOGLE_SHEET_URL

def download_xlsx(spreadsheet_id: str, filename: str = "report.xlsx"):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=[
        'https://www.googleapis.com/auth/drive.readonly'
    ])
    access_token = creds.token
    if not access_token:
        creds.refresh(Request())
        access_token = creds.token

    xlsx_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    headers = {"Authorization": f"Bearer {access_token}"}

    r = requests.get(xlsx_url, headers=headers)
    if r.status_code == 200:
        with open(filename, "wb") as f:
            f.write(r.content)
        return filename
    else:
        print("❌ Ошибка скачивания XLSX:", r.status_code, r.text)
        return None



def download_products_xlsx():
    return download_xlsx(SPREADSHEET_ID, filename="otchet_po_tovaram.xlsx")


# --- ОТЧЕТЫ ПО ЗАКАЗАМ ---

def fetch_orders_report(period: str):
    # period: "today", "3days", "7days", "30days"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now()
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "3days":
        since = now - timedelta(days=3)
    elif period == "7days":
        since = now - timedelta(days=7)
    elif period == "30days":
        since = now - timedelta(days=30)
    else:
        conn.close()
        return None

    c.execute("""
        SELECT id, user_name, user_address, user_phone, cart, total_price, status, created_at
        FROM orders
        WHERE datetime(created_at) >= ?
        ORDER BY created_at DESC
    """, (since.strftime("%Y-%m-%d %H:%M:%S"),))
    orders = c.fetchall()
    conn.close()
    return orders

def make_orders_report_text(orders, period: str):
    if not orders:
        return f"За указанный период ({period}) заказов не найдено."

    lines = [f"📝 Отчёт по заказам за {period}:"]
    total_sum = 0
    total_count = 0
    for o in orders:
        oid, uname, addr, phone, cart_json, total, status, created = o
        try:
            cart = json.loads(cart_json)
        except Exception:
            cart = {}
        total_qty = sum(item.get("quantity", 0) for item in cart.values())
        items_str = "; ".join(f'{item["name"]} x{item["quantity"]}' for item in cart.values())
        rus_status = STATUS_MAP.get(status, "Неизвестен")
        lines.append(
            f"— №{oid} | {uname} | {rus_status} | {round(total)}₸ | Товаров: {total_qty} | {created[:16]}\n    {items_str}"
        )
        total_sum += total
        total_count += total_qty
    lines.append(f"\nВсего заказов: {len(orders)}\nВсего единиц товаров: {total_count}\nОбщая сумма: {round(total_sum)}₸")
    return "\n".join(lines)
def prepare_orders_report_data(orders, period: str):
    data = [["ID", "Имя", "Адрес", "Телефон", "Статус", "Дата", "Сумма", "Кол-во товаров", "Состав корзины"]]
    if not orders:
        return data + [["", "", "", "", "", "", "", "", f"Нет заказов за период: {period}"]]
    for o in orders:
        oid, uname, addr, phone, cart_json, total, status, created = o
        try:
            cart = json.loads(cart_json)
        except Exception:
            cart = {}
        total_qty = sum(item.get("quantity", 0) for item in cart.values())
        items_str = "; ".join(f'{item["name"]} x{item["quantity"]}' for item in cart.values())
        rus_status = STATUS_MAP.get(status, "Неизвестен")
        data.append([
            oid, uname, addr, phone, rus_status,
            created[:16], round(total), total_qty, items_str
        ])
    return data

def prepare_orders_data_for_gsheet(period: str):
    orders = fetch_orders_report(period)
    data = [["ID", "Имя", "Телефон", "Адрес", "Статус", "Дата", "Товары", "Итог (₸)", "Кол-во товаров"]]
    for o in orders:
        oid, uname, addr, phone, cart_json, total, status, created = o
        try:
            cart = json.loads(cart_json)
        except:
            cart = {}
        items_str = "; ".join(
            f'{item["name"]} x{item["quantity"]} (Бренд: {item.get("brand", "Не указано")})'
            for item in cart.values()
        )

        total_qty = sum(item.get("quantity", 0) for item in cart.values())
        rus_status = STATUS_MAP.get(status, "Неизвестен")
        data.append([oid, uname, phone, addr, rus_status, created[:16], items_str, round(total), total_qty])
    return data



def export_orders_to_gsheet(data, sheet_title):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=[
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ])
    client = gspread.authorize(creds)

    spreadsheet = client.create(sheet_title)
    spreadsheet.share(None, perm_type='anyone', role='reader')  # Доступ по ссылке!

    worksheet = spreadsheet.sheet1
    worksheet.update_title(sheet_title)
    worksheet.append_rows(data)

    # Оформление
    sheet_id = worksheet._properties['sheetId']
    spreadsheet.batch_update({
        "requests": [
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 10},
                    "properties": {"pixelSize": 220},  # увеличено с 200
                    "fields": "pixelSize"
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id},
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                    "fields": "userEnteredFormat.wrapStrategy"
                }
            }
        ]
    })

    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={sheet_id}"
    return spreadsheet.id, sheet_url


import xlsxwriter

def export_to_excel_xlsxwriter(data, filename="report.xlsx"):
    workbook = xlsxwriter.Workbook(filename)
    worksheet = workbook.add_worksheet("Отчет")

    wrap_format = workbook.add_format({
        'text_wrap': True,
        'valign': 'top'
    })

    # Запись данных
    for row_idx, row in enumerate(data):
        for col_idx, value in enumerate(row):
            worksheet.write(row_idx, col_idx, str(value), wrap_format)

    # Автоширина по колонкам
    for col_idx in range(len(data[0])):
        max_width = max(len(str(row[col_idx])) for row in data if len(row) > col_idx)
        worksheet.set_column(col_idx, col_idx, min(max_width * 1.1, 60))  # до 60 символов ширина

    # Установка высоты строки
    for row_idx, row in enumerate(data):
        max_lines = 1
        for cell in row:
            lines = str(cell).count('\n') + max(1, len(str(cell)) // 40)
            max_lines = max(max_lines, lines)
        worksheet.set_row(row_idx, max_lines * 15)

    workbook.close()
    print(f"✅ Excel (XlsxWriter) файл сохранён: {filename}")




if __name__ == "__main__":
    print("📦 Жүктелуде... Тауар мәліметтерін жинап жатырмыз...")
    data = fetch_products_detailed()

    # Терминалға шығару (отладка үшін)
    for row in data:
        print(" | ".join(str(x) for x in row))

    # Google Sheets-ке экспорт
    print("📤 Google Sheets-ке экспорт...")
    export_to_gsheet(data)
    print("✅ Подробные данные о товарах экспортированы в Google Sheets!")

    # Excel-ге экспорт (ЖАҢА — xlsxwriter қолданады)
    print("📥 Excel файлына экспорт...")
    export_to_excel_xlsxwriter(data, filename="otchet_tovary.xlsx")
    print("✅ Файл сақталды: otchet_tovary.xlsx")

