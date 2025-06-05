import os
import re
import pandas as pd
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from openai import OpenAI
from io import BytesIO, StringIO
import requests
from bs4 import BeautifulSoup
import time

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_IMAGE = "https://store.moma.org/cdn/shop/files/cb53004d-5f7b-47cd-81ed-0103369d43cb_3072_28314069-17ff-44bc-952f-f2c1eefbb036_1296x.jpg"

def find_image_duckduckgo(ean):
    query = str(ean)
    url = f"https://duckduckgo.com/?q={requests.utils.quote(query)}&t=h_&iar=images&iax=images&ia=images"
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()
    session.get("https://duckduckgo.com/", headers=headers)
    time.sleep(1)
    resp = session.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    imgs = [img["src"] for img in soup.find_all("img") if img.get("src") and img["src"].startswith("http")]
    return imgs[0] if imgs else ""

def find_title_column(df):
    priority = ["name", "назв", "product", "товар", "brand", "title"]
    for col in df.columns:
        for key in priority:
            if key in col.lower():
                return col
    return df.columns[0]

def extract_brands_from_titles(titles):
    split_titles = [re.split(r"[\s,|/-]", t, maxsplit=3) for t in titles]
    possible_brands = set()
    for st in split_titles:
        for l in range(1, 4):
            brand = " ".join(st[:l]).strip()
            if len(brand) > 2:
                possible_brands.add(brand)
    brands_freq = {b: sum([t.lower().startswith(b.lower()) for t in titles]) for b in possible_brands}
    brands = sorted(brands_freq, key=lambda b: (-brands_freq[b], -len(b)))
    return brands

def extract_brand_from_title(title, brands):
    for b in brands:
        if title.lower().startswith(b.lower()):
            return b
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

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(file.file)
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file.file)
    else:
        return {"error": "Только .csv или .xlsx/.xls"}

    col_title = find_title_column(df)
    col_sku = next((c for c in df.columns if "sku" in c.lower() or "арт" in c.lower()), None)
    col_ean = next((c for c in df.columns if "ean" in c.lower() or "баркод" in c.lower()), None)
    col_qty = next((c for c in df.columns if "qty" in c.lower() or "нал" in c.lower()), None)
    col_content = next((c for c in df.columns if "content" in c.lower() or "объем" in c.lower()), None)
    col_price = next((c for c in df.columns if "price" in c.lower() or "цена" in c.lower()), None)
    col_cat = next((c for c in df.columns if "category" in c.lower() or "катег" in c.lower()), None)
    col_subcat = next((c for c in df.columns if "subcat" in c.lower() or "подкат" in c.lower()), None)
    col_origin = next((c for c in df.columns if "origin" in c.lower() or "страна" in c.lower()), None)

    titles = df[col_title].astype(str).tolist()
    brands = extract_brands_from_titles(titles)

    result = []
    for idx, row in df.iterrows():
        title = str(row.get(col_title, ""))
        brand = extract_brand_from_title(title, brands)
        sku = str(row.get(col_sku, "")) if col_sku else ""
        ean = str(row.get(col_ean, "")) if col_ean else ""
        qty_raw = row.get(col_qty, 0) if col_qty else 0
        try:
            qty = int(float(str(qty_raw).replace(",", ".").replace("-", "0").strip()))
        except Exception:
            qty = 0
        content = str(row.get(col_content, "")) if col_content else ""
        price = str(row.get(col_price, "")).replace(",", ".") if col_price else ""
        main_cat = str(row.get(col_cat, "")) if col_cat else ""
        sub_cat = str(row.get(col_subcat, "")) if col_subcat else ""
        origin = str(row.get(col_origin, "")) if col_origin else ""

        handle = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        desc = generate_description(title, main_cat)
        seo_title = generate_seo_title(title, brand, main_cat)
        seo_desc = generate_seo_description(title, brand, main_cat)
        tags = ", ".join(filter(None, [main_cat, sub_cat, origin]))

        image_url = find_image_duckduckgo(ean)
        if not image_url:
            image_url = DEFAULT_IMAGE
        images = [image_url]

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
