import requests
import logging
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
async def verify_golang():

    logging.warning("Received request!")
    r = requests.get("http://frontend.mofaas-version-generation.10.255.30.133.sslip.io/")
    logging.warning(r.text)

    return r.text


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
