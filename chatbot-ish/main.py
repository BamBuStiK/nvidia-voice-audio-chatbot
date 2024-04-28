import shutil
from fastapi.responses import FileResponse
import os
import httpx
from fastapi import FastAPI, WebSocket, Request, File, UploadFile, HTTPException, Response
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from typing import List
import asyncio
import run_spleeter
import zipfile
from fastapi import Path


app = FastAPI()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_DIR = os.path.join(BASE_DIR, "uploaded_files")
DOWN_DIR = os.path.join(BASE_DIR, "processed_files")


os.makedirs(FILE_DIR, exist_ok=True)


templates = Jinja2Templates(directory="templates")


@app.get("/")
async def client(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/files/", response_model=List[str])
async def list_files():
    return [
        f for f in os.listdir(FILE_DIR) if os.path.isfile(os.path.join(FILE_DIR, f))
    ]


@app.get("/download/")
async def download_files():
    # List all files in the DOWN_DIR directory
    files_list = [
        f for f in os.listdir(DOWN_DIR) if os.path.isfile(os.path.join(DOWN_DIR, f))
    ]
    if not files_list:
        raise HTTPException(status_code=404, detail="No files found")
    print(files_list)
    return files_list


@app.get("/download/all")
async def download_all_files():
    des_name = "all_processed_files.zip"
    zip_path = os.path.join(DOWN_DIR, des_name)

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in os.listdir(DOWN_DIR):
            file_path = os.path.join(DOWN_DIR, f)
            # Ensure the current file is not the zip file being created
            if os.path.isfile(file_path) and f != des_name:
                zipf.write(file_path, arcname=f)

    return FileResponse(path=zip_path, filename=des_name, media_type='application/octet-stream')


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(DOWN_DIR, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='application/octet-stream')
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.post("/upload/")
async def handle_file_upload(file: UploadFile = File(...)):
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in ["wav", "mp3"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    file_location = os.path.join(FILE_DIR, file.filename)
    with open(file_location, "wb+") as file_object:
        file_object.write(await file.read())
        print(f"File '{file.filename}' saved at '{file_location}'")
    AUDIO_FILENAME = file.filename
    return {"info": f"File '{file.filename}' saved at '{file_location}'"}


@app.get("/search/")
async def search_files(query: str):
    matching_files = [
        f
        for f in os.listdir(FILE_DIR)
        if query.lower() in f.lower() and os.path.isfile(os.path.join(FILE_DIR, f))
    ]
    if not matching_files:
        raise HTTPException(status_code=404, detail="No matching files found")
    return matching_files


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text(
        "Welcome to the oooo service!"
    )
    while True:  # Start of the main interaction loop
        # Present service options to the user at the start of each loop iteration

        await websocket.send_text(
            "Choose an option:\n"
            "1. Audio Separation\n"
            "2. Finding Info\n"
            "3. Recommend New Songs"
        )

        data = await websocket.receive_text()

        if data == "1":
            await websocket.send_text("You selected Audio Separation. Please upload your file.")
            filename_data = await websocket.receive_text()

            if filename_data.startswith("uploaded:"):
                filename = filename_data.split("uploaded:")[1]
                await websocket.send_text(f"You've uploaded {filename}.")
                await websocket.send_text("Wait for Separation...")
                spl = run_spleeter.run_spleeter(filename)

                if spl == 1:
                    await websocket.send_text("An error occurred during separation.")
                else:
                    await websocket.send_text("Separation Complete. Download will start soon.")
                    await asyncio.sleep(2)
                    await websocket.send_text("Downloading files.")
            else:
                await websocket.send_text("No file uploaded.")

        elif data == "2":
            await websocket.send_text("You selected Finding Info. Please enter the song name or part of it to search.")
            song_query = await websocket.receive_text()
            try:
                search_results = await search_song_vocadb(song_query)
                if not search_results:
                    await websocket.send_text("No matching songs found.")
                else:
                    result_messages = "\n".join(
                        [f"{song['name']} by {', '.join(artist['name'] for artist in song['artists'])}" for song in search_results]
                    )
                    await websocket.send_text(f"Found songs:\n{result_messages}")
            except httpx.ConnectError as e:
                await websocket.send_text(f"Could not connect to VocaDB API: {str(e)}")
            except Exception as e:
                await websocket.send_text(f"Error during search: {str(e)}")

        elif data == "3":
            await websocket.send_text("You selected Recommend New Songs.")

        else:
            await websocket.send_text(f"Unrecognized option: {data}. Please select 1, 2, or 3.")
            continue

        # Ask if they want to continue with another service
        await websocket.send_text("Do you want to continue with another service with same audio? (yes/no)")
        continue_operation = await websocket.receive_text()
        if continue_operation.lower() != 'yes':
            await websocket.send_text("Thank you for using our service. Goodbye!")
            break  # Exit the loop

    await websocket.close()


async def search_song_vocadb(query: str) -> List[dict]:
    url = "https://vocadb.net/api/songs/"
    params = {"query": query, "fields": "Artists", "lang": "English"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()["items"]


def test_vocadb_api():

    url = "https://api.vocadb.net/api/songs"
    params = {"query": "test song", "fields": "Artists", "lang": "English"}
    try:
        with httpx.Client() as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            print(response.json())
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred: {e.response.status_code}")
    except httpx.RequestError as e:
        print(f"Request error occurred: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    import uvicorn

    test_vocadb_api()
    uvicorn.run("main:app", host="127.0.0.1", port=8000,
                log_level="debug", reload=True)
