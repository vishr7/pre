import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/projects", tags=["Projects"])

# Folder where research projects will be saved
DATA_FOLDER = Path(__file__).resolve().parent.parent / "data"
DATA_FOLDER.mkdir(exist_ok=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)

class ProjectFile(BaseModel):
    path: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=2_000_000)


class ProjectFiles(BaseModel):
    files: list[ProjectFile] = Field(max_length=200)


class ProjectFiles(BaseModel):
    files: list[ProjectFile]


@router.post("/")
def create_project(project: ProjectCreate):
    project_id = str(uuid4())

    new_project = {
        "id": project_id,
        "name": project.name,
        "files": []
    }

    # Save the project as a JSON file
    file_path = DATA_FOLDER / f"{project_id}.json"

    with open(file_path, "w") as file:
        json.dump(new_project, file, indent=4)

    return new_project


@router.get("/{project_id}")
def get_project(project_id: str):
    # Check that the project ID is valid
    try:
        project_id = str(UUID(project_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    file_path = DATA_FOLDER / f"{project_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    with open(file_path, "r") as file:
        return json.load(file)


@router.put("/{project_id}/files")


def save_project_files(project_id: str, project_files: ProjectFiles):
    # Check that the project exists
    try:
        project_id = str(UUID(project_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")
    file_path = DATA_FOLDER / f"{project_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    # Check that the file paths are safe
    for project_file in project_files.files:
        path = Path(project_file.path)

        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in project_file.path
            or not project_file.path.strip()
        ):
            raise HTTPException(status_code=400, detail="Invalid file path")

    # Read the existing project
    with open(file_path, "r") as file:
        project = json.load(file)

    # Replace the project's files with the updated list
    project["files"] = [
        project_file.model_dump()
        for project_file in project_files.files
    ]

    # Save the updated project
    with open(file_path, "w") as file:
        json.dump(project, file, indent=4)

    return project
