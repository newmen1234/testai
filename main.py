import os
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
import pandas as pd
from io import BytesIO, StringIO
from openai import OpenAI

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extract_brand(name):
    return name.split()[0]

def generate_description(title):
    system_prompt = "Ты — профессиональный копирайтер. Напиши уникальное продающее описание товара на немецком языке, основываясь на названии товара. Не дублируй название, делай текст уникальным и емким."
    user_prompt = f"Название товара: {title}"
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return resp.choices[0].message.content.strip()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if file.filename.endswith('.csv'):
        df = pd.read_csv(file.file)
    elif file.filename.endswith('.xlsx'):
        df = pd.read_excel(file.file)
    else:
        return {"error": "Только .csv или .xlsx"}

    title_col = next((col for col in df.columns if "name" in col.lower() or "title" in col.lower()), df.columns[0])
    img_col = next((col for col in df.columns if "img" in col.lower() or "photo" in col.lower()), None)
    price_col = next((col for col in df.columns if "price" in col.lower()), None)

    result = []
    for _, row in df.iterrows():
        title = str(row[title_col])
        brand = extract_brand(title)
        description = generate_description(title)
        img = str(row[img_col]) if img_col else ""
        price = row[price_col] if price_col else ""

        result.append({
            "Handle": title.lower().replace(" ", "-"),
            "Title": title,
            "Body (HTML)": description,
            "Vendor": brand,
            "Type": "",
            "Tags": "",
            "Published": "TRUE",
            "Option1 Name": "Title",
            "Option1 Value": title,
            "Variant SKU": "",
            "Variant Grams": "",
            "Variant Inventory Tracker": "",
            "Variant Inventory Qty": "100",
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Price": price,
            "Variant Compare At Price": "",
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "TRUE",
            "Variant Barcode": "",
            "Image Src": img,
            "Image Position": "1" if img else "",
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
