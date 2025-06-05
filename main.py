import os
import re
import pandas as pd
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from openai import OpenAI
from io import BytesIO, StringIO
import requests
from bs4 import BeautifulSoup

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extract_brand(brand_col, name_col):
    if pd.notnull(brand_col) and str(brand_col).strip():
        return str(brand_col).strip()
    # Если нет бренда — пробуем из имени до первой цифры/размера
    m = re.match(r"([A-Za-zа-яА-Я0-9\- ]+)", str(name_col))
    return m.group(1).strip() if m else str(name_col).split()[0]

def generate_description(title, category):
    system_prompt = (
        "Ты — профессиональный копирайтер. Напиши уникальное продающее описание на немецком языке, "
        "для интернет-магазина, с учетом SEO. Укажи бренд, категорию и ключевые свойства, не дублируй название."
    )
    user_prompt = f"Товар: {title}\nКатегория: {category}"
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return resp.choices[0].message.content.strip()

def generate_seo_title(title, brand, category):
    return f"{brand} {title} jetzt online kaufen | {category}"

def generate_seo_description(title, brand, category):
    return f"Entdecke {brand} {title} in der Kategorie {category} – jetzt im Onlineshop zum besten Preis bestellen!"

def fetch_images_from_page(url):
    # Парсим страницу, собираем все большие картинки (jpg/png)
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        imgs = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            # Приводим к абсолютному урлу
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = re.match(r"^https?://[^/]+", url).group(0) + src
            elif not src.startswith("http"):
                src = url.rstrip("/") + "/" + src
            # Фильтруем по размеру/расширению
            if re.search(r"\.(jpe?g|png)$", src, re.IGNORECASE):
                imgs.append(src)
        # deduplicate
        return list(dict.fromkeys(imgs))
    except Exception:
        return []

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(file.file)
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file.file)
    else:
        return {"error": "Только .csv или .xlsx/.xls"}

    # Ожидаем эти поля, уточни если что-то не так!
    col_sku = "Artikelnummer"
    col_ean = "EAN"
    col_qty = "Available Qty"
    col_brand = "Brand"
    col_name = "Brand"
    col_title = "Brand"
    col_content = "Content"
    col_price = "Price"
    col_cat = "Main category"
    col_subcat = "Subcategory"
    col_bekijk = "Bekijk"
    col_origin = "Origin of product"

    result = []
    for idx, row in df.iterrows():
        sku = str(row.get(col_sku, ""))
        ean = str(row.get(col_ean, ""))
        qty = int(row.get(col_qty, 0)) if not pd.isnull(row.get(col_qty, 0)) else 0
        brand = extract_brand(row.get(col_brand, ""), row.get(col_title, ""))
        title = str(row.get(col_title, ""))
        content = str(row.get(col_content, ""))
        price = str(row.get(col_price, "")).replace(",", ".")
        main_cat = str(row.get(col_cat, ""))
        sub_cat = str(row.get(col_subcat, ""))
        origin = str(row.get(col_origin, ""))
        link = str(row.get(col_bekijk, ""))

        # Генерация полей
        handle = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        desc = generate_description(title, main_cat)
        seo_title = generate_seo_title(title, brand, main_cat)
        seo_desc = generate_seo_description(title, brand, main_cat)
        tags = ", ".join(filter(None, [main_cat, sub_cat, origin]))
        images = fetch_images_from_page(link)

        if not images:
            images = [""]  # Чтобы была хоть одна строка

        for img_idx, img in enumerate(images):
            result.append({
                "Handle": handle,
                "Title": title,
                "Body (HTML)": desc,
                "Vendor": brand,
                "Type": main_cat,
                "Tags": tags,
                "Published": "TRUE",
                "Option1 Name": "Inhalt",
                "Option1 Value": content,
                "Variant SKU": sku,
                "Variant Grams": "",
                "Variant Inventory Tracker": "shopify",
                "Variant Inventory Qty": qty,
                "Variant Inventory Policy": "deny",
                "Variant Fulfillment Service": "manual",
                "Variant Price": price,
                "Variant Compare At Price": "",
                "Variant Requires Shipping": "TRUE",
                "Variant Taxable": "TRUE",
                "Variant Barcode": ean,
                "Image Src": img,
                "Image Position": str(img_idx+1) if img else "",
                "Image Alt Text": f"{brand} {title}",
                "Gift Card": "FALSE",
                "SEO Title": seo_title,
                "SEO Description": seo_desc,
                "Status": "active"
            })

    out_df = pd.DataFrame(result)
    output = StringIO()
    out_df.to_csv(output, index=False)
    output.seek(0)
    return StreamingResponse(
        BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shopify_upload.csv"}
    )

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <h1>Shopify Generator</h1>
    <form action="/upload" enctype="multipart/form-data" method="post">
    <input name="file" type="file">
    <input type="submit">
    </form>
    """
