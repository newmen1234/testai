import os
import re
import pandas as pd
from fastapi import FastAPI, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from openai import OpenAI
from io import BytesIO, StringIO
import requests
from bs4 import BeautifulSoup

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROGRESS = {}

def fetch_images_from_page(url):
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        imgs = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = re.match(r"^https?://[^/]+", url).group(0) + src
            elif not src.startswith("http"):
                src = url.rstrip("/") + "/" + src
            if re.search(r"\.(jpe?g|png)$", src, re.IGNORECASE):
                imgs.append(src)
        return list(dict.fromkeys(imgs))
    except Exception:
        return []

def extract_brand_from_title(title, brand_list):
    # Находит бренды по наличию в начале названия товара
    for b in sorted(brand_list, key=lambda x: -len(x)):
        if title.lower().startswith(b.lower()):
            return b
    # Если не найдено — Unknown
    return "Unknown"

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

def get_brand_list(df):
    # Собираем список уникальных брендов (максимально длинных, для поиска в начале названия)
    col_brand = "Brand"
    brands = df[col_brand].dropna().astype(str).unique().tolist()
    brands = sorted(set([b.strip() for b in brands if b.strip()]), key=lambda x: -len(x))
    return brands

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(file.file)
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file.file)
    else:
        return {"error": "Только .csv или .xlsx/.xls"}

    col_sku = "Artikelnummer"
    col_ean = "EAN"
    col_qty = "Available Qty"
    col_brand = "Brand"
    col_title = "Brand"
    col_content = "Content"
    col_price = "Price"
    col_cat = "Main category"
    col_subcat = "Subcategory"
    col_bekijk = "Bekijk"
    col_origin = "Origin of product"

    brand_list = get_brand_list(df)
    result = []
    total = len(df)
    processed = 0

    for idx, row in df.iterrows():
        sku = str(row.get(col_sku, ""))
        ean = str(row.get(col_ean, ""))
        qty = int(row.get(col_qty, 0)) if not pd.isnull(row.get(col_qty, 0)) else 0
        title = str(row.get(col_title, ""))
        content = str(row.get(col_content, ""))
        price = str(row.get(col_price, "")).replace(",", ".")
        main_cat = str(row.get(col_cat, ""))
        sub_cat = str(row.get(col_subcat, ""))
        origin = str(row.get(col_origin, ""))
        link = str(row.get(col_bekijk, ""))

        brand = extract_brand_from_title(title, brand_list)
        handle = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        desc = generate_description(title, main_cat)
        seo_title = generate_seo_title(title, brand, main_cat)
        seo_desc = generate_seo_description(title, brand, main_cat)
        tags = ", ".join(filter(None, [main_cat, sub_cat, origin]))
        images = fetch_images_from_page(link)

        # Только с картинками!
        if images:
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
                    "Image Position": str(img_idx+1),
                    "Image Alt Text": f"{brand} {title}",
                    "Gift Card": "FALSE",
                    "SEO Title": seo_title,
                    "SEO Description": seo_desc,
                    "Status": "active"
                })
        processed += 1

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
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Shopify Generator</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100">
  <div class="flex items-center justify-center min-h-screen">
    <div class="bg-white p-8 rounded-xl shadow-2xl w-full max-w-md">
      <h1 class="text-2xl font-bold mb-6 text-center">Загрузка товаров для Shopify</h1>
      <form id="uploadForm" enctype="multipart/form-data">
        <input id="fileInput" name="file" type="file" class="mb-4 block w-full text-sm"/>
        <button type="submit" class="w-full bg-blue-600 text-white rounded-xl px-4 py-2 font-semibold transition hover:bg-blue-700">Загрузить и обработать</button>
      </form>
      <div id="progressContainer" class="hidden mt-4">
        <div class="w-full bg-gray-200 rounded-full h-3 mb-2">
          <div id="progressBar" class="bg-blue-600 h-3 rounded-full" style="width: 0%"></div>
        </div>
        <div class="text-center text-gray-700 text-sm" id="progressText"></div>
      </div>
      <a id="downloadLink" href="#" class="hidden mt-6 w-full block text-center bg-green-500 text-white rounded-xl px-4 py-2 font-semibold hover:bg-green-600">Скачать Shopify CSV</a>
    </div>
  </div>
  <script>
    const form = document.getElementById('uploadForm');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const downloadLink = document.getElementById('downloadLink');
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      progressContainer.classList.remove('hidden');
      progressBar.style.width = '0%';
      progressText.textContent = 'Обработка файла...';

      const fileInput = document.getElementById('fileInput');
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      const res = await fetch('/upload', { method: 'POST', body: formData });

      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        downloadLink.href = url;
        downloadLink.download = "shopify_upload.csv";
        downloadLink.classList.remove('hidden');
        progressBar.style.width = '100%';
        progressText.textContent = 'Готово!';
      } else {
        progressText.textContent = 'Ошибка при обработке файла';
        downloadLink.classList.add('hidden');
      }
    });
  </script>
</body>
</html>
    """
