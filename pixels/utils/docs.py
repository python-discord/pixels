def get_doc(file_name: str) -> str:
    with open(f"/app/pixels/docs/{file_name}.md", encoding="UTF-8") as file:
        return file.read()

