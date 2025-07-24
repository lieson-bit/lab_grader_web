from fastapi import FastAPI, Request, Response, HTTPException
import os
import yaml
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File
from dotenv import load_dotenv
from itsdangerous import TimestampSigner, BadSignature
import re

load_dotenv()
app = FastAPI()
COURSES_DIR = "courses"
CREDENTIALS_FILE = "credentials.json"  # Файл с учетными данными Google API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешить запросы с любых источников
    allow_credentials=True,
    allow_methods=["*"],  # Разрешить все HTTP-методы
    allow_headers=["*"],  # Разрешить все заголовки
)
signer = TimestampSigner(SECRET_KEY)


class AuthRequest(BaseModel):
    login: str
    password: str


class StudentRegistration(BaseModel):
    name: str = Field(..., min_length=1)
    surname: str = Field(..., min_length=1)
    patronymic: str = ""
    github: str = Field(..., min_length=1)


@app.get("/")
async def read_index():
    return FileResponse("dist/index.html")


@app.post("/api/admin/login")
def admin_login(data: AuthRequest, response: Response):
    if data.login == ADMIN_LOGIN and data.password == ADMIN_PASSWORD:
        token = signer.sign(data.login.encode()).decode()
        response.set_cookie(
            key="admin_session",
            value=token,
            httponly=True,
            max_age=3600,
            path="/",
            secure=False
        )
        return {"authenticated": True}
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")


@app.get("/api/admin/check-auth")
def check_auth(request: Request):
    cookie = request.cookies.get("admin_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="Нет сессии")

    try:
        login = signer.unsign(cookie, max_age=3600).decode()
    except BadSignature:
        raise HTTPException(status_code=401, detail="Невалидная или просроченная сессия")

    if login != ADMIN_LOGIN:
        raise HTTPException(status_code=401, detail="Невалидная сессия")

    return {"authenticated": True}


@app.post("/api/admin/logout")
def logout(response: Response):
    response.delete_cookie("admin_session", path="/")
    return {"message": "Logged out"}


@app.get("/courses")
def get_courses():
    courses = []
    for index, filename in enumerate(sorted(os.listdir(COURSES_DIR)), start=1):
        file_path = os.path.join(COURSES_DIR, filename)
        if filename.endswith(".yaml") and os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    data = yaml.safe_load(file)
                except yaml.YAMLError as e:
                    print(f"Ошибка при разборе YAML в {filename}: {e}")
                    continue

                if not isinstance(data, dict) or "course" not in data:
                    print(f"Пропускаем файл {filename}: неверная структура")
                    continue

                course_info = data["course"]
                courses.append({
                    "id": str(index),
                    "name": course_info.get("name", "Unknown"),
                    "semester": course_info.get("semester", "Unknown"),
                    "logo": course_info.get("logo", "/assets/default.png"),
                    "email": course_info.get("email", ""),
                })
    return courses


def parse_lab_id(lab_id: str) -> int:
    match = re.search(r"\d+", lab_id)
    if not match:
        raise HTTPException(status_code=400, detail="Некорректный lab_id")
    return int(match.group(0))


@app.get("/courses/{course_id}")
def get_course(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        return {
            "id": course_id,
            "config": filename,
            "name": course_info.get("name", "Unknown"),
            "semester": course_info.get("semester", "Unknown"),
            "email": course_info.get("email", "Unknown"),
            "github-organization": course_info.get("github", {}).get("organization", "Unknown"),
            "google-spreadsheet": course_info.get("google", {}).get("spreadsheet", "Unknown"),
        }


@app.delete("/courses/{course_id}")
def delete_course(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"message": "Курс успешно удален"}
    else:
        raise HTTPException(status_code=404, detail="Файл курса не найден")


class EditCourseRequest(BaseModel):
    content: str


@app.get("/courses/{course_id}/edit")
def edit_course_get(course_id: str):
    """Получить YAML содержимое курса для редактирования"""
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл курса не найден")

    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    return {"filename": filename, "content": content}


@app.put("/courses/{course_id}/edit")
def edit_course_put(course_id: str, data: EditCourseRequest):
    """Сохранить изменения в YAML файле курса"""
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)

    try:
        yaml.safe_load(data.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Ошибка в YAML формате: {str(e)}")

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(data.content)

    return {"message": "Изменения успешно сохранены"}


@app.get("/courses/{course_id}/groups")
def get_course_groups(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        info_sheet = course_info.get("google", {}).get("info-sheet")

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not found in course config")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet_names = [sheet.title for sheet in spreadsheet.worksheets() if sheet.title != info_sheet]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sheets: {str(e)}")

    return sheet_names


@app.get("/courses/{course_id}/groups/{group_id}/labs")
def get_course_labs(course_id: str, group_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        labs = [lab["short-name"] for lab in course_info.get("labs", {}).values() if "short-name" in lab]

    if not spreadsheet_id or not labs:
        raise HTTPException(status_code=400, detail="Missing spreadsheet ID or labs in config")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.worksheet(group_id)

        headers = sheet.row_values(2)[2:]
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Group not found in spreadsheet: {str(e)}")

    available_labs = [lab for lab in labs if lab in headers]
    return available_labs


@app.post("/courses/{course_id}/groups/{group_id}/register")
def register_student(course_id: str, group_id: str, student: StudentRegistration):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        student_col = course_info.get("google", {}).get("student-name-column", 2)

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not found in course config")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.worksheet(group_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Group not found in spreadsheet")

    full_name = f"{student.surname} {student.name} {student.patronymic}".strip()

    student_list = sheet.col_values(student_col)[2:]

    if full_name not in student_list:
        raise HTTPException(status_code=404, detail="Студент не найден")

    row_idx = student_list.index(full_name) + 3

    header_row = sheet.row_values(1)
    try:
        github_col_idx = header_row.index("GitHub") + 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Столбец 'GitHub' не найден в таблице")

    try:
        github_response = requests.get(f"https://api.github.com/users/{student.github}")
        if github_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Пользователь GitHub не найден")
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка проверки GitHub пользователя")

    existing_github = sheet.cell(row_idx, github_col_idx).value

    if not existing_github:
        sheet.update_cell(row_idx, github_col_idx, student.github)
        return {"status": "registered", "message": "Аккаунт GitHub успешно задан"}

    if existing_github == student.github:
        return {
            "status": "already_registered",
            "message": "Этот аккаунт GitHub уже был указан ранее для этого же студента"
        }

    raise HTTPException(status_code=409,
                        detail="Аккаунт GitHub уже был указан ранее. Для изменения аккаунта обратитесь к преподавателю")


def normalize_lab_id(lab_id: str) -> str:
    """Возвращает нормализованную строку вида ЛР1, ЛР2 и т.д."""
    number = parse_lab_id(lab_id)
    return f"ЛР{number}"


class GradeRequest(BaseModel):
    github: str = Field(..., min_length=1)


@app.post("/courses/{course_id}/groups/{group_id}/labs/{lab_id}/grade")
def grade_lab(course_id: str, group_id: str, lab_id: str, request: GradeRequest):
    # Загрузка конфигурации курса
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        org = course_info.get("github", {}).get("organization")
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        student_col = course_info.get("google", {}).get("student-name-column", 2)
        lab_offset = course_info.get("google", {}).get("lab-column-offset", 1)

    labs = course_info.get("labs", {})
    normalized_lab_id = lab_id[2:]
    lab_config = labs.get(normalized_lab_id, {})
    repo_prefix = lab_config.get("github-prefix")
    required_files = lab_config.get("files", [])
    test_files = lab_config.get("tests", [])

    if not all([org, spreadsheet_id, repo_prefix]):
        raise HTTPException(status_code=400, detail="Missing course configuration")

    username = request.github
    repo_name = f"{repo_prefix}-{username}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    
    # 1. Проверка наличия обязательных файлов
    missing_files = []
    for file in required_files:
        file_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/{file}"
        if requests.get(file_url, headers=headers).status_code != 200:
            missing_files.append(file)
    
    if missing_files:
        raise HTTPException(
            status_code=400,
            detail=f"⚠️ Отсутствуют обязательные файлы: {', '.join(missing_files)}"
        )
    
    # 2. Проверка тестовых файлов (если указаны)
    if test_files:
        missing_tests = []
        for test in test_files:
            test_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/{test}"
            if requests.get(test_url, headers=headers).status_code != 200:
                missing_tests.append(test)

        if missing_tests:
            raise HTTPException(
                status_code=400,
                detail=f"⚠️ Отсутствуют тестовые файлы: {', '.join(missing_tests)}"
            )

    # 3. Проверка CI workflows
    workflows_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/.github/workflows"
    if requests.get(workflows_url, headers=headers).status_code != 200:
        raise HTTPException(status_code=400, detail="⚠️ Папка .github/workflows не найдена. CI не настроен")

    # 4. Проверка коммитов и изменений файлов
    commits_url = f"https://api.github.com/repos/{org}/{repo_name}/commits"
    commits_resp = requests.get(commits_url, headers=headers)
    if commits_resp.status_code != 200 or not commits_resp.json():
        raise HTTPException(status_code=404, detail="Нет коммитов в репозитории")

    # Получаем информацию о последнем коммите
    latest_commit = commits_resp.json()[0]
    latest_sha = latest_commit["sha"]
    commit_url = f"https://api.github.com/repos/{org}/{repo_name}/commits/{latest_sha}"
    commit_data = requests.get(commit_url, headers=headers).json()
    commit_files = commit_data.get("files", [])
    commit_author = latest_commit.get("author", {}).get("login")

    if commit_author and commit_author.lower() == username.lower():
        for f in commit_files:
            # Запрет изменения тестовых файлов
            if test_files:
                # Проверка отдельных тестовых файлов
                if any(f["filename"] == test_file for test_file in test_files if not test_file.endswith('/')) and f[
                    "status"] in ("removed", "modified"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"🚨 Запрещено изменять тестовый файл: {f['filename']}"
                    )

                # Проверка файлов в тестовых директориях
                if any(f["filename"].startswith(test_file.rstrip('/') + '/') for test_file in test_files if
                       test_file.endswith('/')) and f["status"] in ("removed", "modified"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"🚨 Запрещено изменять файлы в тестовой директории: {f['filename']}"
                    )

    check_url = f"https://api.github.com/repos/{org}/{repo_name}/commits/{latest_sha}/check-runs"
    check_resp = requests.get(check_url, headers=headers)
    if check_resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Проверки CI не найдены")

    check_runs = check_resp.json().get("check_runs", [])
    if not check_runs:
        return {"status": "pending", "message": "Нет активных CI-проверок ⏳"}

    summary = []
    passed_count = 0

    for check in check_runs:
        name = check.get("name", "Unnamed check")
        conclusion = check.get("conclusion")
        html_url = check.get("html_url")
        if conclusion == "success":
            emoji = "✅"
            passed_count += 1
        elif conclusion == "failure":
            emoji = "❌"
        else:
            emoji = "⏳"
        summary.append(f"{emoji} {name} — {html_url}")

    total_checks = len(check_runs)
    result_string = f"{passed_count}/{total_checks} тестов пройдено"
    final_result = "✓" if passed_count == total_checks else "✗"

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet(group_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Группа не найдена в Google Таблице")

    header_row = sheet.row_values(1)
    try:
        github_col_idx = header_row.index("GitHub") + 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Столбец 'GitHub' не найден")

    github_values = sheet.col_values(github_col_idx)[2:]
    if username not in github_values:
        raise HTTPException(status_code=404, detail="GitHub логин не найден в таблице. Зарегистрируйтесь.")

    lab_number = parse_lab_id(lab_id)
    row_idx = github_values.index(username) + 3
    lab_col = student_col + lab_number + lab_offset

    current_value = sheet.cell(row_idx, lab_col).value

    if not current_value or str(current_value).strip() == "":
        sheet.update_cell(row_idx, lab_col, final_result)
    print("result:", final_result)
    return {
        "status": "updated",
        "result": final_result,
        "message": f"Результат CI: {'✅ Все проверки пройдены' if final_result == '✓' else '❌ Обнаружены ошибки'}",
        "passed": result_string,
        "checks": summary,
        "files_checked": {
            "required": required_files,
            "tests": test_files
        }
    }


@app.post("/courses/upload")
async def upload_course(file: UploadFile = File(...)):
    if not file.filename.endswith(".yaml") and not file.filename.endswith(".yml"):
        raise HTTPException(status_code=400, detail="Только YAML файлы разрешены")
    file_location = os.path.join(COURSES_DIR, file.filename)

    if os.path.exists(file_location):
        raise HTTPException(status_code=400, detail="Файл с таким именем уже существует")

    content = await file.read()
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail="Некорректный YAML файл")

    with open(file_location, "wb") as f:
        f.write(content)

    return {"detail": "Курс успешно загружен"}