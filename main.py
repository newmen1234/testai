from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from openai import OpenAI

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class Prompt(BaseModel):
    prompt: str

@app.post("/chat")
async def chat(data: Prompt):
    chat_completion = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": data.prompt}]
    )
    return {"response": chat_completion.choices[0].message.content}

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return f.read()
